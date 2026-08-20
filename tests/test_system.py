"""System health endpoint tests (Phase 4).

The live probes (Open-Meteo weather / AQI, Nominatim) are disabled in tests
via UDT_ENABLE_LIVE_PROBES=false (see conftest), so these tests are fast,
deterministic and offline. The health response must still be structurally
complete and every value must derive from real disk state or configuration —
never hardcoded as "active".
"""

from __future__ import annotations

from conftest import requires_artifacts


def test_system_health_shape(client):
    r = client.get("/api/system/health")
    assert r.status_code == 200
    body = r.json()

    assert body["status"] in ("healthy", "degraded")
    assert "generated_at" in body

    # --- backend ---------------------------------------------------------
    assert body["backend"]["status"] == "online"
    assert body["backend"]["version"]

    # --- database --------------------------------------------------------
    db = body["database"]
    assert "enabled" in db  # either connected (True) or not configured (False)

    # --- model (real disk state, never fabricated) -----------------------
    model = body["model"]
    assert "status" in model and "available" in model
    assert model["available"] == (model["status"] == "available")
    if model["available"]:
        assert model["name"]  # e.g. XGBRegressor
        assert model["feature_count"] is not None and model["feature_count"] > 0
    else:
        assert model["name"] is None
        assert model["feature_count"] is None

    # --- GIS (real catalogue/directory counts) ---------------------------
    gis = body["gis"]
    assert gis["datasets_total"] > 5
    assert 0 <= gis["datasets_available"] <= gis["datasets_total"]
    assert gis["status"] in ("available", "partial", "unavailable")
    assert (gis["status"] == "available") == (
        gis["datasets_available"] == gis["datasets_total"]
    )

    # --- scenarios -------------------------------------------------------
    scenarios = body["scenarios"]
    assert isinstance(scenarios["count"], int)
    assert scenarios["ready"] == (scenarios["count"] > 0)
    assert "increase_green_10" in scenarios["names"]

    # --- satellite (from GeoJSON grid) ------------------------------------
    sat = body.get("satellite")
    if sat:
        assert sat["status"] in ("LATEST_OBSERVATION", "UNAVAILABLE", "PARTIAL")

    # --- live services (disabled in tests -> unavailable, with reason) ----
    for key in ("weather", "air_quality", "search"):
        item = body[key]
        assert item["status"] in ("unavailable", "available")
        if item["status"] == "unavailable":
            assert item.get("reason")  # truthful reason, never a fake "active"

    # --- AI ---------------------------------------------------------------
    ai = body["ai"]
    assert ai["provider"] == "NVIDIA NIM (Nemotron)"
    assert ai["status"] in ("configuration_required", "configured")
    assert ai["available"] == (ai["status"] == "configured")

    # live_probes_enabled reflects the backend setting (may be true or false
    # depending on environment — tests use os.environ.setdefault which only
    # takes effect when the var is not already set).
    assert body["live_probes_enabled"] in (True, False)


@requires_artifacts
def test_system_health_model_matches_model_info(client):
    """The health endpoint must agree with /api/model/info (single truth)."""
    health = client.get("/api/system/health").json()["model"]
    info = client.get("/api/model/info").json()
    assert health["available"] == info["available"]
    assert health["feature_count"] == info["feature_count"]
    assert health["name"] == info["model"]


def test_system_health_gis_matches_monitoring(client):
    """GIS counts in health must match the monitoring report (same source)."""
    health = client.get("/api/system/health").json()["gis"]
    monitoring = client.get("/api/monitoring/status").json()["summary"]
    assert health["datasets_total"] == monitoring["total"]
    assert health["datasets_available"] == monitoring["available"]


def test_system_health_scenarios_match_listing(client):
    """Scenario names in health must match /api/simulation/scenarios."""
    health = client.get("/api/system/health").json()["scenarios"]
    listing = {sc["name"] for sc in client.get("/api/simulation/scenarios").json()}
    assert set(health["names"]) == listing
    assert health["count"] == len(listing)


def test_weather_endpoint_offline_state(client):
    """With probes disabled, /api/system/weather reports unavailable clearly."""
    r = client.get("/api/system/weather")
    assert r.status_code == 200
    body = r.json()
    assert body["available"] is False
    assert body["status"] == "unavailable"
    assert "reason" in body


def test_air_quality_endpoint_offline_state(client):
    """With probes disabled, /api/system/air-quality reports unavailable."""
    r = client.get("/api/system/air-quality")
    assert r.status_code == 200
    body = r.json()
    assert body["available"] is False
    assert body["status"] == "unavailable"
    assert "reason" in body
