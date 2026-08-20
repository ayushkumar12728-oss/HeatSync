"""
End-to-end system verification (hackathon readiness gate)
==========================================================
Verifies the complete, already-trained pipeline in one place without
retraining anything:

1. trained model artifacts exist and load
2. the 58 model features resolve against the leakage report / dataset
3. a real prediction row flows through the serving pipeline
4. the canonical scenarios run against the live model
5. GIS artefacts are present and readable
6. SHAP explainability artefacts are present
7. the backend routes respond
8. the Nemotron unavailable state is handled gracefully

No test here depends on a live NVIDIA API key.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from conftest import DATASET_CSV, MODEL_PKL, requires_artifacts

ROOT = Path(__file__).resolve().parent.parent

SHAP_DIR = ROOT / "data" / "outputs" / "plots" / "SHAP"
LEAKAGE_REPORT = ROOT / "data" / "outputs" / "reports" / "leakage_report.json"

# Leakage / identifier columns that must never reach the model.
FORBIDDEN_FEATURES = {"Target_LST", "MeanLST", "MaxLST", "MinLST", "Grid_ID"}


# ---------------------------------------------------------------------- #
# 1. Model artefacts
# ---------------------------------------------------------------------- #
def test_model_artifacts_exist():
    assert MODEL_PKL.exists(), "models/best_model.pkl missing"
    assert (ROOT / "models" / "best_model.onnx").exists(), "models/best_model.onnx missing"


@requires_artifacts
def test_model_loads_and_shape():
    import joblib

    model = joblib.load(MODEL_PKL)
    names = getattr(model, "feature_names_in_", None)
    assert model is not None
    assert names is not None and len(names) == 58
    assert model.get_booster().num_features() == 58


def test_model_checksum_matches_documented():
    """Regression guard: the deployed PKL must keep its documented SHA256."""
    if not MODEL_PKL.exists():
        pytest.skip("model absent")
    digest = hashlib.sha256(MODEL_PKL.read_bytes()).hexdigest()
    assert digest == "2baee888574e3b29e2c8ded3553daa01c9ac4f5107421e65a9a76d75175740c0"


# ---------------------------------------------------------------------- #
# 2. Feature metadata
# ---------------------------------------------------------------------- #
@requires_artifacts
def test_feature_metadata_consistent():
    report = json.loads(LEAKAGE_REPORT.read_text(encoding="utf-8"))
    kept = report.get("kept") or report.get("selected_features")
    assert len(kept) == 58
    assert not (FORBIDDEN_FEATURES & set(kept)), (
        f"leakage columns leaked into features: {FORBIDDEN_FEATURES & set(kept)}"
    )

    df = pd.read_csv(DATASET_CSV)
    assert set(kept) <= set(df.columns), "kept features missing from the dataset"


# ---------------------------------------------------------------------- #
# 3. Prediction pipeline
# ---------------------------------------------------------------------- #
@requires_artifacts
def test_prediction_pipeline_real_row(client):
    features = client.get("/api/prediction/features").json()["features"]
    assert len(features) == 58
    assert not (FORBIDDEN_FEATURES & set(features))

    df = pd.read_csv(DATASET_CSV, nrows=1)
    row = {k: (None if pd.isna(df.iloc[0][k]) else df.iloc[0][k]) for k in features}
    r = client.post("/api/prediction/predict", json={"features": row})
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    assert body["model"] == "XGBRegressor"
    assert body["model_version"]
    result = body["predictions"][0]
    assert result["predicted_lst_c"] is not None
    assert np.isfinite(result["predicted_lst_c"])
    assert result["uhi_class"]


# ---------------------------------------------------------------------- #
# 4. Scenario engine
# ---------------------------------------------------------------------- #
@requires_artifacts
def test_all_canonical_scenarios_run(client):
    names = [sc["name"] for sc in client.get("/api/simulation/scenarios").json()]
    expected = {
        "increase_green_10", "increase_green_20", "decrease_buildings_10",
        "decrease_buildings_20", "increase_trees", "increase_parks",
        "increase_water",
    }
    assert expected <= set(names)

    for name in names:
        r = client.post("/api/simulation/run", json={"scenario": name})
        assert r.status_code == 200, f"{name}: {r.text}"
        body = r.json()
        assert np.isfinite(body["baseline_lst"])
        assert np.isfinite(body["mean_predicted_lst"])
        # delta is always scenario minus baseline - never hardcoded.
        # mean(delta) vs mean(perturbed) - mean(baseline) can differ by
        # floating-point accumulation on a 53k-row grid, so use 1e-3.
        assert body["mean_delta_lst"] == pytest.approx(
            body["mean_predicted_lst"] - body["baseline_lst"], abs=1e-3
        )
        assert 0 <= body["pct_cells_cooler"] <= 100


@requires_artifacts
def test_increase_green_20_regression(client):
    """Regression check: greening by 20% must cool the grid (not forced)."""
    body = client.post(
        "/api/simulation/run", json={"scenario": "increase_green_20"}
    ).json()
    assert body["mean_delta_lst"] < 0
    assert body["pct_cells_cooler"] > 50


# ---------------------------------------------------------------------- #
# 5. GIS artefacts
# ---------------------------------------------------------------------- #
def test_gis_artefacts_exist():
    required = [
        "data/processed/ndvi/ndvi.tif",
        "data/processed/lst/LST.tif",
        "data/processed/landcover/landcover.tif",
        "data/processed/elevation/Elevation.tif",
        "data/processed/aqi/rasters/AQI.tif",
        "data/processed/greencover/green_cover.tif",
        "data/predictions/Predicted_LST.geojson",
        "data/predictions/Predicted_LST.tif",
        "data/predictions/Predicted_LST.png",
    ]
    missing = [p for p in required if not (ROOT / p).exists()]
    assert not missing, f"missing GIS artefacts: {missing}"


def test_osm_layers_valid():
    layers_dir = ROOT / "data" / "raw" / "osm" / "layers"
    assert layers_dir.exists()
    web_layers = sorted(layers_dir.glob("web_3d_*.geojson"))
    assert len(web_layers) >= 5
    for path in web_layers:
        fc = json.loads(path.read_text(encoding="utf-8"))
        assert fc.get("type") == "FeatureCollection"


# ---------------------------------------------------------------------- #
# 6. SHAP artefacts
# ---------------------------------------------------------------------- #
def test_shap_artefacts_exist():
    required = [
        "global_importance.png",
        "summary_plot.png",
        "global_shap_importance.csv",
    ]
    missing = [name for name in required if not (SHAP_DIR / name).exists()]
    assert not missing, f"missing SHAP artefacts: {missing}"


def test_shap_importance_endpoint(client):
    r = client.get("/api/explainability/importance")
    if (ROOT / "data" / "outputs" / "plots" / "SHAP"
            / "global_shap_importance.csv").exists():
        assert r.status_code == 200
        assert r.json()["count"] == 58
    else:
        assert r.status_code == 404


# ---------------------------------------------------------------------- #
# 7. Backend routes
# ---------------------------------------------------------------------- #
def test_backend_routes_respond(client):
    for path in (
        "/api/health",
        "/api/health/ready",
        "/api/model/info",
        "/api/data/layers",
        "/api/data/boundary",
        "/api/monitoring/status",
        "/api/environment/summary",
        "/api/dashboard/summary",
        "/api/simulation/scenarios",
    ):
        r = client.get(path)
        assert r.status_code == 200, f"{path} -> {r.status_code}"


# ---------------------------------------------------------------------- #
# 8. Nemotron unavailable state
# ---------------------------------------------------------------------- #
def test_nemotron_unavailable_state_is_graceful(client):
    """No API key -> configuration_required, never a crash or a fake call."""
    r = client.get("/api/ai/status")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] in ("configuration_required", "configured")
    assert body["available"] == (body["status"] == "configured")

    r = client.post("/api/ai/ask", json={"question": "Why is this area hot?"})
    assert r.status_code == 200
    body = r.json()
    if body["status"] == "configuration_required":
        assert body["success"] is False
        assert body["answer"] is None
        assert "NEMOTRON_API_KEY" in body["message"]
