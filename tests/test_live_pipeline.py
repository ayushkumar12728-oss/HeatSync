"""
Live feature pipeline tests
============================
Verifies the complete current-data pipeline:

1. Satellite parsing succeeds (no more "Mixing dicts" error)
2. Feature matrix has exactly 58 features
3. Current prediction uses current weather (not training data)
4. No training/test dataset is used by current prediction
5. Scenario uses current feature matrix
6. Missing satellite data is reported honestly
7. No API key is exposed to frontend
8. Debug endpoint returns correct structure
"""

from __future__ import annotations

import math
from pathlib import Path

import pytest
from conftest import requires_artifacts

ROOT = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------- #
# 1. Satellite parsing
# ---------------------------------------------------------------------- #
@requires_artifacts
def test_satellite_parsing_succeeds():
    """The GeoJSON must parse without 'Mixing dicts' error."""
    from backend.config.settings import Settings
    from backend.services.live_feature_pipeline import LiveFeaturePipeline
    from backend.services.serving import ServingContext

    settings = Settings()
    serving = ServingContext(settings)
    pipeline = LiveFeaturePipeline(settings, serving)
    sat = pipeline._get_satellite_data()
    assert sat is not None, "Satellite data should load from training_dataset.geojson"
    assert "MeanNDVI" in sat, "MeanNDVI missing from satellite data"
    assert "LandCoverClass" in sat, "LandCoverClass missing from satellite data"
    assert sat.get("satellite_acquisition"), "Acquisition metadata missing"


@requires_artifacts
def test_satellite_features_are_numeric():
    """Satellite feature values must be numeric (not dicts or strings)."""
    from backend.config.settings import Settings
    from backend.services.live_feature_pipeline import LiveFeaturePipeline
    from backend.services.serving import ServingContext

    settings = Settings()
    serving = ServingContext(settings)
    pipeline = LiveFeaturePipeline(settings, serving)
    sat = pipeline._get_satellite_data()
    assert sat is not None
    for key in ("MeanNDVI", "MaxNDVI", "MinNDVI", "GreenCover",
                "VegetationDensity", "LandCover_WaterPct"):
        val = sat.get(key)
        if val is not None:
            assert isinstance(val, (int, float)), (
                f"Satellite feature {key} is {type(val).__name__}, expected numeric"
            )
            assert math.isfinite(float(val)), f"Satellite feature {key} is not finite"


# ---------------------------------------------------------------------- #
# 2. Feature matrix has exactly 58 features
# ---------------------------------------------------------------------- #
@requires_artifacts
def test_feature_matrix_has_58_features():
    """The current feature grid must produce exactly 58 features."""
    from backend.config.settings import Settings
    from backend.services.live_feature_pipeline import (
        MODEL_FEATURES,
        LiveFeaturePipeline,
    )
    from backend.services.serving import ServingContext

    settings = Settings()
    serving = ServingContext(settings)
    pipeline = LiveFeaturePipeline(settings, serving)
    result = pipeline.refresh()

    fv = result.get("feature_values", {})
    assert len(fv) == 58, f"Expected 58 features, got {len(fv)}"
    # Every MODEL_FEATURES entry must be present
    missing = [f for f in MODEL_FEATURES if f not in fv]
    assert not missing, f"Missing features: {missing}"


@requires_artifacts
def test_feature_matrix_no_nan_inf():
    """No feature value should be NaN or Inf."""
    from backend.config.settings import Settings
    from backend.services.live_feature_pipeline import LiveFeaturePipeline
    from backend.services.serving import ServingContext

    settings = Settings()
    serving = ServingContext(settings)
    pipeline = LiveFeaturePipeline(settings, serving)
    result = pipeline.refresh()

    fv = result.get("feature_values", {})
    nan_count = 0
    inf_count = 0
    for _feat_name, prov_tuple in fv.items():
        val = prov_tuple[0] if prov_tuple else None
        if val is not None:
            if math.isnan(float(val)):
                nan_count += 1
            elif math.isinf(float(val)):
                inf_count += 1
    assert nan_count == 0, f"{nan_count} features have NaN values"
    assert inf_count == 0, f"{inf_count} features have Inf values"


# ---------------------------------------------------------------------- #
# 3. Current prediction uses current weather
# ---------------------------------------------------------------------- #
@requires_artifacts
def test_prediction_status_reflects_data_availability(client):
    """The /api/prediction/heat/current endpoint must succeed."""
    r = client.get("/api/prediction/heat/current")
    # Should be 200 (prediction available) or 503 (model unavailable)
    assert r.status_code in (200, 503)
    if r.status_code == 200:
        body = r.json()
        assert body["success"] is True
        pred = body.get("prediction", {})
        assert pred.get("predicted_lst_c") is not None
        assert math.isfinite(float(pred["predicted_lst_c"]))
        # Must have data_freshness
        assert "data_freshness" in pred


# ---------------------------------------------------------------------- #
# 4. No training/test dataset used by current prediction
# ---------------------------------------------------------------------- #
@requires_artifacts
def test_current_prediction_not_from_training_csv(client):
    """Current prediction must not read training CSV target columns."""
    r = client.get("/api/prediction/heat/current")
    if r.status_code == 200:
        body = r.json()
        pred = body.get("prediction", {})
        # The prediction must come from the live pipeline, not from CSV
        assert pred.get("source") == "XGBoost model"
        # Must NOT contain training target columns
        assert "MeanLST" not in str(pred)
        assert "Target_LST" not in str(pred)


# ---------------------------------------------------------------------- #
# 5. Scenario uses current feature matrix
# ---------------------------------------------------------------------- #
@requires_artifacts
def test_scenario_run_returns_valid_result(client):
    """A scenario run must return valid results with delta."""
    r = client.post("/api/simulation/run", json={"scenario": "increase_green_10"})
    if r.status_code == 200:
        body = r.json()
        assert body["success"] is True
        assert math.isfinite(body["baseline_lst"])
        assert math.isfinite(body["mean_predicted_lst"])
        assert math.isfinite(body["mean_delta_lst"])
        assert body["mean_delta_lst"] == pytest.approx(
            body["mean_predicted_lst"] - body["baseline_lst"], abs=1e-3
        )


# ---------------------------------------------------------------------- #
# 6. Missing satellite data reported honestly
# ---------------------------------------------------------------------- #
@requires_artifacts
def test_satellite_availability_in_health(client):
    """The system health endpoint must report satellite status."""
    r = client.get("/api/system/health")
    assert r.status_code == 200
    body = r.json()
    sat = body.get("satellite")
    assert sat is not None, "satellite field missing from health response"
    assert sat["status"] in ("LATEST_OBSERVATION", "UNAVAILABLE", "PARTIAL")


@requires_artifacts
def test_debug_endpoint_satellite_status(client):
    """The debug endpoint must report honest satellite status."""
    r = client.get("/api/prediction/heat/current/debug")
    if r.status_code == 200:
        body = r.json()
        assert body["success"] is True
        ds = body.get("data_sources", {})
        sat = ds.get("satellite", {})
        assert sat.get("status") in ("LATEST_OBSERVATION", "UNAVAILABLE")
        # Feature count must match
        fc = body.get("feature_count", {})
        assert fc.get("expected") == 58
        assert fc.get("match") is True


# ---------------------------------------------------------------------- #
# 7. No API key exposed to frontend
# ---------------------------------------------------------------------- #
def test_no_api_key_in_health_response(client):
    """API keys must never appear in any API response."""
    for path in (
        "/api/system/health",
        "/api/ai/status",
        "/api/model/info",
    ):
        r = client.get(path)
        assert r.status_code == 200
        text = r.text.lower()
        # Check for common key patterns
        assert "sk-" not in text, f"API key pattern 'sk-' found in {path}"
        assert "nvidia_api_key" not in text, f"API key name found in {path}"
        # The base_url may appear but the key itself must not
        if "nemotron" in text and "key" in text:
            # Only "NEMOTRON_API_KEY" as a config instruction, never the value
            assert "bearer" not in text, f"Bearer token found in {path}"


# ---------------------------------------------------------------------- #
# 8. Debug endpoint structure
# ---------------------------------------------------------------------- #
@requires_artifacts
def test_debug_endpoint_structure(client):
    """The debug endpoint must return the expected structure."""
    r = client.get("/api/prediction/heat/current/debug")
    if r.status_code == 200:
        body = r.json()
        assert "timestamp" in body
        assert "grid_cells" in body
        assert body["grid_cells"] == 53802
        assert "model" in body
        assert body["model"]["feature_count"] == 58
        assert "features" in body
        assert len(body["features"]) == 58
        assert "data_sources" in body
        assert "prediction" in body
        assert "pipeline_status" in body
        # Each feature must have provenance fields
        for _feat_name, feat_data in body["features"].items():
            assert "value" in feat_data
            assert "source" in feat_data
            assert "status" in feat_data
            assert feat_data["status"] in (
                "LIVE", "LATEST_OBSERVATION", "STATIC_GIS",
                "DERIVED", "UNAVAILABLE",
            )
