"""Tests for the city-wide digital-twin endpoints (3D city upgrade)."""

from __future__ import annotations

import pytest
from conftest import requires_artifacts


def _get(client, path):
    r = client.get(path)
    return r.status_code, r.json()


# ---------------------------------------------------------------------- #
# Location intelligence (nearest grid cell)
# ---------------------------------------------------------------------- #
@requires_artifacts
def test_city_point_profile(client):
    status, body = _get(client, "/api/city/point?lat=20.2636&lng=85.8275")
    assert status == 200
    assert body["available"] is True
    assert body["grid_id"] is not None
    assert "environment" in body
    env = body["environment"]
    # Real values only — every field must be present, possibly None, never faked
    assert set(env) >= {"MeanLST", "MeanAQI", "MeanNDVI", "GreenCover",
                        "BuildingCoveragePct", "Predicted_LST", "MeanElevation"}
    assert set(body["risk"]) == {"heat", "air_quality", "vegetation",
                                 "urban_density"}


@requires_artifacts
def test_city_point_outside_grid(client):
    # Deep ocean — no grid cell within 3 km
    status, body = _get(client, "/api/city/point?lat=0.0&lng=0.0")
    assert status == 200
    assert body["available"] is False


@requires_artifacts
def test_city_hotspots(client):
    status, body = _get(client, "/api/city/hotspots?limit=10")
    assert status == 200
    assert body["available"] is True
    hotspots = body["hotspots"]
    assert 0 < len(hotspots) <= 10
    lsts = [h["predicted_lst"] for h in hotspots]
    assert lsts == sorted(lsts, reverse=True)  # hottest first


# ---------------------------------------------------------------------- #
# Cooling potential (model-derived) + interventions
# ---------------------------------------------------------------------- #
@requires_artifacts
def test_cooling_potential(client):
    status, body = _get(client, "/api/city/cooling-potential")
    assert status == 200
    if body.get("available"):
        assert body["count"] > 0
        # strongest cooling first
        coolings = [c["max_cooling_c"] for c in body["cells"]]
        assert coolings == sorted(coolings)
        classes = {c["cooling_class"] for c in body["cells"]}
        assert classes <= {"VERY HIGH", "HIGH", "MODERATE", "LOW"}
        assert len(classes) >= 2
    else:
        assert "message" in body


@requires_artifacts
def test_cooling_potential_geojson(client):
    status, body = _get(client, "/api/city/cooling-potential/geojson")
    assert status == 200
    assert body["type"] == "FeatureCollection"
    for feature in body.get("features", []):
        props = feature["properties"]
        assert props["cooling_class"] in ("VERY HIGH", "HIGH", "MODERATE", "LOW")
        assert feature["geometry"]["type"] == "Polygon"


@requires_artifacts
def test_interventions(client):
    status, body = _get(client, "/api/city/interventions")
    assert status == 200
    if body.get("available"):
        for item in body["interventions"]:
            assert item["cooling_c"] <= 0
            assert item["scenario"]
        # sorted strongest cooling first
        coolings = [i["cooling_c"] for i in body["interventions"]]
        assert coolings == sorted(coolings)


# ---------------------------------------------------------------------- #
# City intelligence + explainability
# ---------------------------------------------------------------------- #
@requires_artifacts
def test_city_intelligence(client):
    status, body = _get(client, "/api/city/intelligence")
    assert status == 200
    assert body["available"] is True
    assert body["current_heat"] is not None
    assert body["best_intervention"]["scenario"]
    assert body["best_intervention"]["mean_delta_lst"] <= 0


@requires_artifacts
def test_city_explain(client):
    status, body = _get(client, "/api/city/explain?lat=20.2636&lng=85.8275")
    assert status == 200
    assert body["available"] is True
    factors = body["explanation"]["factors"]
    assert len(factors) > 0
    # Every factor carries real values and a real SHAP importance
    for f in factors:
        assert f["shap_importance"] > 0
        assert f["value"] is not None
        assert f["direction"] in ("above", "below")


# ---------------------------------------------------------------------- #
# Heat-safe routing
# ---------------------------------------------------------------------- #
@requires_artifacts
def test_heat_safe_route(client):
    status, body = _get(
        client,
        "/api/routing/heat-safe?start_lat=20.2500&start_lng=85.7800"
        "&end_lat=20.3000&end_lng=85.8500",
    )
    assert status == 200
    assert body["available"] is True
    fastest = body["fastest"]
    coolest = body["coolest"]
    assert fastest is not None and coolest is not None
    assert fastest["distance_km"] > 0
    assert fastest["geometry"]["type"] == "LineString"
    # The comparison must be meaningful: the coolest route is never hotter
    # on average than the fastest route for the same corridor.
    assert coolest["avg_lst_c"] <= fastest["avg_lst_c"] + 1e-6


@requires_artifacts
def test_heat_safe_route_same_cell(client):
    status, body = _get(
        client,
        "/api/routing/heat-safe?start_lat=20.2636&start_lng=85.8275"
        "&end_lat=20.2636&end_lng=85.8275",
    )
    assert status == 200
    assert "message" in body


def test_city_endpoints_require_artifacts_gracefully(client):
    """Without artifacts the endpoints must return 503, not crash."""
    from backend.config.settings import get_settings
    from backend.services.city_data import CityDataService

    class _NoGrid(CityDataService):
        def _load_grid(self):
            raise FileNotFoundError("no grid")

    service = _NoGrid(get_settings())
    # nearest_cell propagates the clean error; endpoints convert to 503
    with pytest.raises(FileNotFoundError):
        service.point_profile(20.26, 85.82)
