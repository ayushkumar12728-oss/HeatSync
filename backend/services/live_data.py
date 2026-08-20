"""
Live data probes (weather / air quality / search)
==================================================
Cached probes for the /api/system endpoints, backed by **OpenWeather** for
live weather and air quality (backend-only requests — the API key never
leaves the server) and OpenStreetMap Nominatim for search reachability.

* **Weather** — OpenWeather Current Weather API (``/data/2.5/weather``).
* **Air quality** — OpenWeather Air Pollution API (``/data/2.5/air_pollution``).
  AQI is the OpenWeather 1-5 index (1 = Good .. 5 = Very Poor) plus the real
  pollutant concentrations (µg/m³). Never fabricated: when the probe fails
  the result is a clear ``unavailable`` state with a stable reason category.
* **Search** — OpenStreetMap Nominatim reachability probe (the frontend
  searches through the backend ``/api/search`` proxy, never directly).

All probes run with a short timeout, cache results server-side for a bounded
TTL (so the UI never hammers the public APIs) and are safe to call from
FastAPI request handlers (thread-safe, one lock per cache slot).

Error categories (Phase 8)
--------------------------
Every failure maps to a stable ``reason`` so the frontend can show the right
state without seeing internals:

    configuration_required   no OPENWEATHER_API_KEY configured
    auth_error               HTTP 401/403 (invalid / denied key)
    not_found                HTTP 404
    rate_limit               HTTP 429
    provider_unavailable     HTTP 5xx, DNS, connection error
    provider_timeout         request timed out
    malformed_response       invalid JSON / unexpected shape
    incomplete_response      response parsed but required fields missing

The API key is only ever read from the backend environment / ``.env`` and is
never logged, returned, or sent to the browser.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

from backend.config.settings import Settings

log = logging.getLogger("backend.live_data")


def _sanitize_exc(exc: Exception) -> str:
    """Exception text without query strings (urllib3 embeds the request URL,
    which contains ``appid=...`` — that must never reach logs or responses)."""
    import re
    text = str(exc)
    # Strip ``?query`` from any URL-looking token (keeps host, drops params).
    text = re.sub(r"(https?://\S+?|/\S+?)\?[^\s)'\"]*", r"\1", text)
    # Belt and braces: redact any remaining appid=/api_key= value.
    text = re.sub(r"(appid|api[_-]?key|token)=[^\s&)'\"]+",
                  r"\1=REDACTED", text, flags=re.IGNORECASE)
    return text


# Study area: Bhubaneswar pilot zone (Khandagiri / ITER area).
PILOT_LAT = 20.2520
PILOT_LNG = 85.7880

OPENWEATHER_BASE = "https://api.openweathermap.org/data/2.5"
WEATHER_URL = f"{OPENWEATHER_BASE}/weather"
AQI_URL = f"{OPENWEATHER_BASE}/air_pollution"
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"

SOURCE = "OpenWeather"

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def _env(name: str, default: str | None = None) -> str | None:
    """Env var with a fallback to the project's .env file (like nemotron.py)."""
    value = os.environ.get(name)
    if value not in (None, ""):
        return value
    env_file = PROJECT_ROOT / ".env"
    if env_file.exists():
        try:
            for line in env_file.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line.startswith(name + "="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
        except OSError:
            pass
    return default


def _api_key() -> str | None:
    """The OpenWeather API key (backend env / .env only, never exposed)."""
    return _env("OPENWEATHER_API_KEY")


# ---------------------------------------------------------------------- #
# Structured error helpers
# ---------------------------------------------------------------------- #
def _unavailable(reason: str, **extra) -> dict:
    return {
        "available": False,
        "status": "unavailable",
        "source": SOURCE,
        "reason": reason,
        "checked_at": datetime.now(UTC).isoformat(),
        **extra,
    }


def _unavailable_from_exception(exc: Exception) -> dict:
    """Map a requests exception to a stable, safe reason (no internals)."""
    import requests

    if isinstance(exc, requests.exceptions.Timeout):
        return _unavailable("provider_timeout")
    if isinstance(exc, requests.exceptions.ConnectionError):
        return _unavailable("provider_unavailable", detail="connection_error")
    return _unavailable("provider_unavailable")


def _unavailable_from_status(status_code: int) -> dict:
    if status_code in (401, 403):
        return _unavailable("auth_error")
    if status_code == 404:
        return _unavailable("not_found")
    if status_code == 429:
        return _unavailable("rate_limit")
    if status_code >= 500:
        return _unavailable("provider_unavailable")
    return _unavailable("provider_unavailable")


class _TtlCache:
    """Minimal thread-safe cache: value + timestamp, refresh after TTL.

    Successful results are cached for ``ttl`` seconds; failed (``available ==
    False``) results are cached for a short ``negative_ttl`` (default 15 s) so
    a transient cold-start timeout does not poison the UI for the full TTL.
    """

    def __init__(self, ttl_seconds: int, negative_ttl_seconds: int = 15):
        self.ttl = ttl_seconds
        self.negative_ttl = negative_ttl_seconds
        self._lock = threading.Lock()
        self._ts: float = 0.0
        self._value: dict | None = None

    def _is_fresh(self, now: float) -> bool:
        if self._value is None:
            return False
        ttl = self.negative_ttl if not self._value.get("available") else self.ttl
        return (now - self._ts) < ttl

    def get(self, producer) -> dict:
        now = time.monotonic()
        with self._lock:
            fresh = self._is_fresh(now)
            if fresh:
                return dict(self._value, cache_age_seconds=int(now - self._ts))
        value = producer()
        with self._lock:
            self._ts = time.monotonic()
            self._value = value
        value["cache_age_seconds"] = 0
        return value

    @property
    def age(self) -> int:
        with self._lock:
            if self._value is None:
                return 0
            return int(time.monotonic() - self._ts)


def _get_requests():
    import requests  # lazy import (used only when probes are enabled)
    return requests


def _cache_seconds(settings: Settings, env_name: str, fallback: int) -> int:
    """Configurable cache TTL: env override (e.g. OPENWEATHER_CACHE_SECONDS),
    else the UDT_* setting, else the default."""
    raw = _env(env_name)
    if raw:
        try:
            return max(30, min(3600, int(raw)))
        except ValueError:
            log.warning("Ignoring non-integer %s=%r", env_name, raw)
    return int(fallback)


# ---------------------------------------------------------------------- #
# Weather (OpenWeather Current Weather)
# ---------------------------------------------------------------------- #
def _unix_to_iso(unix: int | None) -> str | None:
    if unix is None:
        return None
    try:
        return datetime.fromtimestamp(int(unix), tz=UTC).isoformat()
    except (ValueError, OSError, OverflowError):
        return None


def probe_weather(settings: Settings) -> dict:
    """Current weather for the study area (OpenWeather, real request)."""
    key = _api_key()
    if not key:
        return _unavailable(
            "configuration_required",
            message="Set OPENWEATHER_API_KEY in .env (see .env.example).",
        )
    params = {
        "lat": PILOT_LAT,
        "lon": PILOT_LNG,
        "appid": key,
        "units": "metric",
    }
    try:
        requests = _get_requests()
        response = requests.get(
            WEATHER_URL, params=params,
            timeout=settings.live_probe_timeout_seconds,
        )
        if response.status_code != 200:
            return _unavailable_from_status(response.status_code)
        data = response.json()
    except Exception as exc:  # network / timeout / invalid JSON
        log.warning("OpenWeather weather probe failed: %s", _sanitize_exc(exc))
        return _unavailable_from_exception(exc)

    main = data.get("main") or {}
    wind = data.get("wind") or {}
    clouds = data.get("clouds") or {}
    weather_list = data.get("weather") or []
    weather0 = weather_list[0] if weather_list else {}
    sys_info = data.get("sys") or {}
    rain = (data.get("rain") or {}).get("1h")
    snow = (data.get("snow") or {}).get("1h")
    dt = data.get("dt")
    sunrise = _unix_to_iso(sys_info.get("sunrise"))
    sunset = _unix_to_iso(sys_info.get("sunset"))
    observed_at = _unix_to_iso(dt)

    temperature = main.get("temp")
    feels_like = main.get("feels_like")
    humidity = main.get("humidity")
    pressure = main.get("pressure")
    wind_speed_ms = wind.get("speed")
    wind_speed_kmh = (wind_speed_ms * 3.6) if wind_speed_ms is not None else None
    cloud_cover = clouds.get("all")
    visibility = data.get("visibility")  # metres

    if temperature is None or observed_at is None:
        return _unavailable("incomplete_response",
                            message="OpenWeather weather response missing core fields.")

    # rain / snow: OpenWeather omits the key when there is no precipitation,
    # which means 0.0 (not missing) — the API only includes the field when
    # it rained/snowed. A present-but-unparseable value is kept as None.
    rain_mm = 0.0 if rain is None else float(rain)
    snow_mm = 0.0 if snow is None else float(snow)

    is_day: bool | None = None
    if dt is not None and sys_info.get("sunrise") and sys_info.get("sunset"):
        is_day = int(dt) < int(sys_info["sunset"]) and int(dt) >= int(sys_info["sunrise"])

    # OpenWeather condition id (e.g. 804 = overcast clouds). WMO code maps in
    # the UI are no longer used for this provider; condition text is returned.
    condition_id = weather0.get("id")

    return {
        "available": True,
        "status": "available",
        "source": SOURCE,
        "latitude": PILOT_LAT,
        "longitude": PILOT_LNG,
        "observed_at": observed_at,
        "retrieved_at": datetime.now(UTC).isoformat(),
        "timezone_offset_seconds": data.get("timezone"),
        "current": {
            # --- OpenWeather-native fields (Phase 5) ---------------------
            "temperature": temperature,
            "feels_like": feels_like,
            "humidity": humidity,
            "pressure": pressure,
            "wind_speed": wind_speed_ms,        # m/s
            "wind_speed_kmh": wind_speed_kmh,   # km/h
            "wind_direction": wind.get("deg"),
            "cloud_cover": cloud_cover,
            "visibility": visibility,           # m
            "rain": rain_mm,                    # mm/h (None if genuinely absent)
            "snow": snow_mm,                    # mm/h
            "weather_condition": weather0.get("main"),
            "weather_description": weather0.get("description"),
            "sunrise": sunrise,
            "sunset": sunset,
            "timestamp": observed_at,
            "weather_code": condition_id,
            "is_day": is_day,
            "uv_index": None,   # not provided by the Current Weather API
            # --- legacy normalized aliases (frontend contract) -----------
            "temperature_2m": temperature,
            "apparent_temperature": feels_like,
            "relative_humidity_2m": humidity,
            "wind_speed_10m": wind_speed_kmh,
            "wind_direction_10m": wind.get("deg"),
            "pressure_msl": pressure,
            "surface_pressure": main.get("grnd_level"),
            "precipitation": rain_mm,
        },
        "units": {
            "temperature": "°C",
            "wind_speed": "m/s",
            "wind_speed_10m": "km/h",
            "visibility": "m",
            "rain": "mm/h",
            "pressure": "hPa",
        },
        "hourly": None,  # Current Weather API has no hourly forecast block
    }


def cached_weather(settings: Settings) -> dict:
    """Weather probe with a bounded server-side cache."""
    ttl = _cache_seconds(settings, "OPENWEATHER_CACHE_SECONDS",
                         settings.live_weather_cache_seconds)
    cache: _TtlCache = _weather_cache
    if cache is None or cache.ttl != ttl:
        cache = _TtlCache(ttl)
        _set_weather_cache(cache)
    return cache.get(lambda: probe_weather(settings))


# module-level cache so it survives across requests
_weather_cache: _TtlCache | None = None


def _set_weather_cache(cache: _TtlCache) -> None:
    global _weather_cache
    _weather_cache = cache


# ---------------------------------------------------------------------- #
# Air quality (OpenWeather Air Pollution API)
# ---------------------------------------------------------------------- #
AQI_LABELS = {1: "Good", 2: "Fair", 3: "Moderate", 4: "Poor", 5: "Very Poor"}


def probe_air_quality(settings: Settings) -> dict:
    """Current AQI + pollutant concentrations (OpenWeather, real request)."""
    key = _api_key()
    if not key:
        return _unavailable(
            "configuration_required",
            message="Set OPENWEATHER_API_KEY in .env (see .env.example).",
        )
    params = {
        "lat": PILOT_LAT,
        "lon": PILOT_LNG,
        "appid": key,
    }
    try:
        requests = _get_requests()
        response = requests.get(
            AQI_URL, params=params,
            timeout=settings.live_probe_timeout_seconds,
        )
        if response.status_code != 200:
            return _unavailable_from_status(response.status_code)
        data = response.json()
    except Exception as exc:
        log.warning("OpenWeather air-quality probe failed: %s", _sanitize_exc(exc))
        return _unavailable_from_exception(exc)

    items = data.get("list") or []
    if not items:
        return _unavailable("incomplete_response",
                            message="OpenWeather air-quality returned no data.")
    entry = items[0]
    main_aqi = (entry.get("main") or {}).get("aqi")
    components = entry.get("components") or {}
    observed_at = _unix_to_iso(entry.get("dt"))

    # AQI 1-5 (OpenWeather scale) — 0 / missing / provider states are kept
    # distinct: a real reading is 1..5, anything else is missing.
    if main_aqi is None:
        return _unavailable("incomplete_response",
                            message="OpenWeather air-quality response missing AQI.")
    if not (1 <= int(main_aqi) <= 5):
        return _unavailable("incomplete_response",
                            message=f"OpenWeather returned unexpected AQI value {main_aqi!r}.")

    aqi = int(main_aqi)
    return {
        "available": True,
        "status": "available",
        "source": SOURCE,
        "latitude": PILOT_LAT,
        "longitude": PILOT_LNG,
        "observed_at": observed_at,
        "retrieved_at": datetime.now(UTC).isoformat(),
        "current": {
            # --- OpenWeather-native fields (Phase 6) ---------------------
            "aqi": aqi,                              # 1-5 OpenWeather index
            "aqi_scale": "OpenWeather 1-5 (1=Good .. 5=Very Poor)",
            "aqi_label": AQI_LABELS.get(aqi),
            "co": components.get("co"),              # µg/m³
            "no": components.get("no"),
            "no2": components.get("no2"),
            "o3": components.get("o3"),
            "so2": components.get("so2"),
            "pm2_5": components.get("pm2_5"),
            "pm10": components.get("pm10"),
            "nh3": components.get("nh3"),
            "us_aqi": None,      # not provided by this API — never fabricated
            "uv_index": None,    # not provided by this API
            # --- legacy normalized aliases (frontend contract) -----------
            "nitrogen_dioxide": components.get("no2"),
            "ozone": components.get("o3"),
            "sulphur_dioxide": components.get("so2"),
            "carbon_monoxide": components.get("co"),
        },
        "units": {
            "pollutants": "µg/m³",
            "aqi": "OpenWeather 1-5 index",
        },
    }


_aqi_cache: _TtlCache | None = None


def cached_air_quality(settings: Settings) -> dict:
    """Air-quality probe with a bounded server-side cache."""
    ttl = _cache_seconds(settings, "OPENWEATHER_CACHE_SECONDS",
                         settings.live_aqi_cache_seconds)
    global _aqi_cache
    if _aqi_cache is None or _aqi_cache.ttl != ttl:
        _aqi_cache = _TtlCache(ttl)
    return _aqi_cache.get(lambda: probe_air_quality(settings))


# ---------------------------------------------------------------------- #
# Search (Nominatim reachability probe — cached, never used for lookups)
# ---------------------------------------------------------------------- #
def probe_search(settings: Settings) -> dict:
    """Minimal Nominatim request to confirm the geocoding service is up."""
    params = {
        "q": "Bhubaneswar",
        "format": "json",
        "limit": 1,
        "viewbox": "85.70,20.08,85.95,20.45",
        "bounded": 1,
    }
    try:
        requests = _get_requests()
        response = requests.get(
            NOMINATIM_URL, params=params,
            timeout=settings.live_probe_timeout_seconds,
            headers={"Accept-Language": "en", "User-Agent": "heatsync-urban-digital-twin/1.0"},
        )
        response.raise_for_status()
        results = response.json()
    except Exception as exc:
        log.warning("Nominatim probe failed: %s", _sanitize_exc(exc))
        return _unavailable(f"Nominatim request failed: {_sanitize_exc(exc)}")

    return {
        "available": True,
        "status": "available",
        "source": "OpenStreetMap Nominatim",
        "provider": "OpenStreetMap Nominatim",
        "returned": len(results or []),
        "checked_at": datetime.now(UTC).isoformat(),
    }


_search_cache: _TtlCache | None = None


def cached_search(settings: Settings) -> dict:
    """Nominatim reachability probe with a bounded server-side cache."""
    global _search_cache
    if _search_cache is None or _search_cache.ttl != settings.search_probe_cache_seconds:
        _search_cache = _TtlCache(settings.search_probe_cache_seconds)
    return _search_cache.get(lambda: probe_search(settings))


# ---------------------------------------------------------------------- #
# Disabled-probe state (used when UDT_ENABLE_LIVE_PROBES=false)
# ---------------------------------------------------------------------- #
def live_probes_disabled() -> dict:
    return {
        "available": False,
        "status": "unavailable",
        "source": SOURCE,
        "reason": "Live probes disabled (UDT_ENABLE_LIVE_PROBES=false).",
        "checked_at": datetime.now(UTC).isoformat(),
    }


def get_weather(settings: Settings) -> dict:
    if not settings.enable_live_probes:
        return live_probes_disabled()
    return cached_weather(settings)


def get_air_quality(settings: Settings) -> dict:
    if not settings.enable_live_probes:
        return live_probes_disabled()
    return cached_air_quality(settings)


def get_search(settings: Settings) -> dict:
    if not settings.enable_live_probes:
        return live_probes_disabled()
    return cached_search(settings)


# Keep a stable public surface for callers/tests.
def clear_caches() -> None:
    """Reset all caches (used by tests)."""
    global _weather_cache, _aqi_cache, _search_cache
    _weather_cache = None
    _aqi_cache = None
    _search_cache = None


__all__ = [
    "PILOT_LAT",
    "PILOT_LNG",
    "SOURCE",
    "clear_caches",
    "get_air_quality",
    "get_search",
    "get_weather",
    "live_probes_disabled",
    "probe_air_quality",
    "probe_search",
    "probe_weather",
]
