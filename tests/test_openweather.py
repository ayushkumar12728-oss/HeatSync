"""Tests for the OpenWeather live-data probes (parsing, caching, errors).

Network is mocked via monkeypatching ``requests.get`` — these tests never hit
the real provider, so they are deterministic and offline.
"""

from __future__ import annotations

import pytest

from backend.config.settings import Settings
from backend.services import live_data


def _settings() -> Settings:
    return Settings(enable_live_probes=True, live_probe_timeout_seconds=5.0,
                    live_weather_cache_seconds=60, live_aqi_cache_seconds=60)


class _Resp:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def _fake_get(monkeypatch, payload, status_code=200):
    import requests
    monkeypatch.setattr(requests, "get", lambda *a, **k: _Resp(payload, status_code))


# ---------------------------------------------------------------------- #
# Weather parsing
# ---------------------------------------------------------------------- #
WEATHER_PAYLOAD = {
    "coord": {"lat": 20.252, "lon": 85.788},
    "weather": [{"id": 804, "main": "Clouds", "description": "overcast clouds"}],
    "main": {"temp": 28.08, "feels_like": 32.79, "humidity": 83, "pressure": 1002,
             "grnd_level": 998},
    "wind": {"speed": 4.12, "deg": 270},
    "clouds": {"all": 100},
    "visibility": 10000,
    "dt": 1786973469,
    "sys": {"sunrise": 1786924628, "sunset": 1786970710},
    "timezone": 19800,
}


def test_probe_weather_parses_real_fields(monkeypatch):
    _fake_get(monkeypatch, WEATHER_PAYLOAD)
    data = live_data.probe_weather(_settings())

    assert data["available"] is True
    assert data["status"] == "available"
    assert data["source"] == "OpenWeather"

    current = data["current"]
    # OpenWeather-native fields (Phase 5)
    assert current["temperature"] == 28.08
    assert current["feels_like"] == 32.79
    assert current["humidity"] == 83
    assert current["pressure"] == 1002
    assert current["wind_speed"] == 4.12
    assert current["wind_direction"] == 270
    assert current["cloud_cover"] == 100
    assert current["visibility"] == 10000
    assert current["weather_condition"] == "Clouds"
    assert current["weather_description"] == "overcast clouds"
    assert current["sunrise"] is not None and current["sunset"] is not None
    assert current["timestamp"] is not None
    # legacy aliases the frontend reads
    assert current["temperature_2m"] == 28.08
    assert current["wind_speed_10m"] == pytest.approx(4.12 * 3.6)
    # observed / retrieved timestamps
    assert data["observed_at"] is not None
    assert data["retrieved_at"] is not None
    assert data["observed_at"] != data["retrieved_at"]  # different moments


def test_probe_weather_rain_absent_is_zero_not_missing(monkeypatch):
    """OpenWeather omits rain/snow keys when there is none -> 0.0, never None."""
    payload = dict(WEATHER_PAYLOAD)
    payload.pop("rain", None)
    payload.pop("snow", None)
    _fake_get(monkeypatch, payload)
    data = live_data.probe_weather(_settings())
    assert data["current"]["rain"] == 0.0
    assert data["current"]["snow"] == 0.0


def test_probe_weather_missing_core_fields_is_incomplete(monkeypatch):
    payload = dict(WEATHER_PAYLOAD)
    payload["main"] = {}  # no temperature
    _fake_get(monkeypatch, payload)
    data = live_data.probe_weather(_settings())
    assert data["available"] is False
    assert data["reason"] == "incomplete_response"


def test_probe_weather_401_is_auth_error(monkeypatch):
    _fake_get(monkeypatch, {"detail": "Invalid API key"}, status_code=401)
    data = live_data.probe_weather(_settings())
    assert data["available"] is False
    assert data["reason"] == "auth_error"


def test_probe_weather_429_is_rate_limit(monkeypatch):
    _fake_get(monkeypatch, {"detail": "limit"}, status_code=429)
    data = live_data.probe_weather(_settings())
    assert data["available"] is False
    assert data["reason"] == "rate_limit"


def test_probe_weather_timeout(monkeypatch):
    import requests

    def _boom(*a, **k):
        raise requests.exceptions.Timeout("timed out")

    monkeypatch.setattr(requests, "get", _boom)
    data = live_data.probe_weather(_settings())
    assert data["available"] is False
    assert data["reason"] == "provider_timeout"


def test_probe_weather_connection_error(monkeypatch):
    import requests

    def _boom(*a, **k):
        raise requests.exceptions.ConnectionError("dns failure")

    monkeypatch.setattr(requests, "get", _boom)
    data = live_data.probe_weather(_settings())
    assert data["available"] is False
    assert data["reason"] == "provider_unavailable"


def test_probe_weather_invalid_json(monkeypatch):
    class _Resp:
        status_code = 200

        def json(self):
            raise ValueError("invalid json")

    import requests
    monkeypatch.setattr(requests, "get", lambda *a, **k: _Resp())
    data = live_data.probe_weather(_settings())
    assert data["available"] is False
    assert data["reason"] == "provider_unavailable"


# ---------------------------------------------------------------------- #
# Air quality parsing
# ---------------------------------------------------------------------- #
AQI_PAYLOAD = {
    "coord": {"lat": 20.252, "lon": 85.788},
    "list": [{
        "main": {"aqi": 2},
        "components": {"co": 189, "no": 0, "no2": 5.03, "o3": 40.87,
                       "so2": 2.14, "pm2_5": 13.1, "pm10": 15.34, "nh3": 1.21},
        "dt": 1786973469,
    }],
}


def test_probe_air_quality_parses_real_fields(monkeypatch):
    _fake_get(monkeypatch, AQI_PAYLOAD)
    data = live_data.probe_air_quality(_settings())

    assert data["available"] is True
    assert data["source"] == "OpenWeather"
    current = data["current"]
    assert current["aqi"] == 2
    assert current["aqi_label"] == "Fair"
    assert current["co"] == 189
    assert current["no"] == 0          # real zero is kept as 0 (not missing)
    assert current["no2"] == 5.03
    assert current["o3"] == 40.87
    assert current["so2"] == 2.14
    assert current["pm2_5"] == 13.1
    assert current["pm10"] == 15.34
    assert current["nh3"] == 1.21
    # never fabricated
    assert current["us_aqi"] is None
    assert data["observed_at"] is not None


def test_probe_air_quality_missing_aqi_is_incomplete(monkeypatch):
    payload = dict(AQI_PAYLOAD)
    payload["list"][0]["main"] = {}
    _fake_get(monkeypatch, payload)
    data = live_data.probe_air_quality(_settings())
    assert data["available"] is False
    assert data["reason"] == "incomplete_response"


def test_probe_air_quality_invalid_aqi_value(monkeypatch):
    payload = dict(AQI_PAYLOAD)
    payload["list"][0]["main"] = {"aqi": 99}
    _fake_get(monkeypatch, payload)
    data = live_data.probe_air_quality(_settings())
    assert data["available"] is False
    assert data["reason"] == "incomplete_response"


def test_probe_air_quality_empty_list(monkeypatch):
    _fake_get(monkeypatch, {"coord": {}, "list": []})
    data = live_data.probe_air_quality(_settings())
    assert data["available"] is False
    assert data["reason"] == "incomplete_response"


def test_probe_air_quality_403(monkeypatch):
    _fake_get(monkeypatch, {"detail": "Forbidden"}, status_code=403)
    data = live_data.probe_air_quality(_settings())
    assert data["available"] is False
    assert data["reason"] == "auth_error"


# ---------------------------------------------------------------------- #
# No-key state
# ---------------------------------------------------------------------- #
def test_probe_without_key_is_configuration_required(monkeypatch):
    monkeypatch.delenv("OPENWEATHER_API_KEY", raising=False)
    # ensure the .env fallback is bypassed for this test
    monkeypatch.setattr(live_data, "_env", lambda name, default=None: None)
    data = live_data.probe_weather(_settings())
    assert data["available"] is False
    assert data["reason"] == "configuration_required"

    data = live_data.probe_air_quality(_settings())
    assert data["available"] is False
    assert data["reason"] == "configuration_required"


# ---------------------------------------------------------------------- #
# Caching
# ---------------------------------------------------------------------- #
def test_cached_weather_serves_second_call_from_cache(monkeypatch):
    import requests

    calls = {"n": 0}
    real = _Resp(WEATHER_PAYLOAD)

    def _counting(*a, **k):
        calls["n"] += 1
        return real

    live_data.clear_caches()
    settings = _settings()
    monkeypatch.setattr(requests, "get", _counting)
    monkeypatch.setenv("OPENWEATHER_CACHE_SECONDS", "120")

    first = live_data.get_weather(settings)
    second = live_data.get_weather(settings)
    assert calls["n"] == 1          # cached: provider called once
    assert first["available"] is True
    assert "cache_age_seconds" in second


def test_cached_weather_respects_ttl(monkeypatch):
    import requests

    calls = {"n": 0}
    real = _Resp(WEATHER_PAYLOAD)

    def _counting(*a, **k):
        calls["n"] += 1
        return real

    live_data.clear_caches()
    settings = Settings(enable_live_probes=True, live_probe_timeout_seconds=5.0,
                        live_weather_cache_seconds=60)
    monkeypatch.setattr(requests, "get", _counting)
    monkeypatch.setenv("OPENWEATHER_CACHE_SECONDS", "60")

    live_data.get_weather(settings)          # provider call 1
    live_data.get_weather(settings)          # served from cache
    assert calls["n"] == 1

    # force the cache entry to expire, then the provider is called again
    cache = live_data._weather_cache
    assert cache is not None
    cache._ts -= cache.ttl + 1
    live_data.get_weather(settings)          # provider call 2
    assert calls["n"] == 2
