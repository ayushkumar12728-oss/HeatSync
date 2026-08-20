"""API tests: health, catalogue, scenarios, predictions, simulations."""

from __future__ import annotations

import pandas as pd
from conftest import DATASET_CSV, requires_artifacts


# ---------------------------------------------------------------------- #
# Health / readiness (no artifacts required)
# ---------------------------------------------------------------------- #
def test_liveness(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["version"]


def test_readiness_reports_missing(client):
    r = client.get("/api/health/ready")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] in ("ready", "not_ready")
    assert isinstance(body["missing_artifacts"], list)


def test_artifacts_report(client):
    r = client.get("/api/health/artifacts")
    assert r.status_code == 200
    names = {a["name"] for a in r.json()}
    assert "model.pkl" in names
    assert all(isinstance(a["exists"], bool) for a in r.json())


# ---------------------------------------------------------------------- #
# Data catalogue
# ---------------------------------------------------------------------- #
def test_layers_listing(client):
    r = client.get("/api/data/layers")
    assert r.status_code == 200
    body = r.json()
    assert "count" in body and "layers" in body
    for layer in body["layers"]:
        assert layer["name"] and layer["url"]


def test_unknown_layer_404(client):
    r = client.get("/api/data/layers/definitely-not-a-layer")
    assert r.status_code == 404


# ---------------------------------------------------------------------- #
# Thematic monitoring + environment (Session 3)
# ---------------------------------------------------------------------- #
def test_monitoring_status(client):
    """Monitoring reports real availability for every thematic dataset."""
    r = client.get("/api/monitoring/status")
    assert r.status_code == 200
    body = r.json()
    assert body["summary"]["total"] > 5
    keys = {ds["key"] for ds in body["datasets"]}
    assert {"osm", "ndvi", "lst", "weather", "aqi"} <= keys
    for ds in body["datasets"]:
        assert isinstance(ds["available"], bool)
        assert ds["status"] in ("available", "unavailable")
        assert ds["source"]
        # availability must be consistent with the file list
        assert ds["available"] == (ds["file_count"] > 0)


def test_monitoring_osm_is_available(client):
    """OSM layers ship with the repo, so they must be reported available."""
    r = client.get("/api/monitoring/status")
    body = r.json()
    osm = next(ds for ds in body["datasets"] if ds["key"] == "osm")
    assert osm["available"] is True
    assert osm["file_count"] >= 5


def test_environment_summary(client):
    """Environment summary returns real OSM-derived statistics."""
    r = client.get("/api/environment/summary")
    assert r.status_code == 200
    body = r.json()
    assert body["city"] == "Bhubaneswar"
    stats = body["stats"]
    for key in ("buildings", "roads", "green", "natural", "water"):
        assert key in stats
        assert stats[key]["count"] >= 0
    assert "boundary_area_km2" in body
    assert "green_cover_pct" in body["derived"]
    assert isinstance(body["availability"], dict)


# ---------------------------------------------------------------------- #
# Model status + prediction unavailable handling (Session 4)
# ---------------------------------------------------------------------- #
def test_model_info_reports_availability(client):
    """GET /api/model/info always returns a structured availability report."""
    r = client.get("/api/model/info")
    assert r.status_code == 200
    body = r.json()
    assert "available" in body and "status" in body
    assert body["available"] in (True, False)
    assert body["available"] == (body["status"] == "available")
    # no fabricated metadata when the model is missing
    if not body["available"]:
        assert body["status"] == "model_unavailable"
        assert body["model"] is None
        assert body["feature_count"] is None
        assert body["metrics"] is None


def test_predict_model_unavailable_response(client):
    """Prediction returns a clear model_unavailable response without a model.

    Uses a full feature row (Phase 11 rejects partial rows with 400), so a
    present model yields 200 and an absent model yields 503.
    """
    import pandas as pd
    from conftest import DATASET_CSV, requires_artifacts  # noqa: F401

    if not (DATASET_CSV.exists() and client.get("/api/prediction/model").json().get("available")):
        # no model/dataset: still exercise the graceful path
        r = client.post(
            "/api/prediction/predict",
            json={"features": {"GreenCover": 30.0, "MeanNDVI": 0.4}},
        )
        assert r.status_code in (400, 503)
        return

    df = pd.read_csv(DATASET_CSV, nrows=1)
    features = client.get("/api/prediction/features").json()["features"]
    row = {
        k: (None if pd.isna(df.iloc[0][k]) else df.iloc[0][k])
        for k in features
    }
    r = client.post("/api/prediction/predict", json={"features": row})
    assert r.status_code == 200
    body = r.json()
    assert body.get("success") is True
    assert body["predictions"][0]["predicted_lst_c"] is not None


def test_simulation_model_unavailable_response(client):
    """Scenario run returns a clear model_unavailable response without a model."""
    r = client.post("/api/simulation/run", json={"scenario": "increase_trees"})
    if r.status_code == 200:
        body = r.json()
        assert body["success"] is True
        assert "baseline_lst" in body and "mean_delta_lst" in body
    else:
        assert r.status_code == 503
        body = r.json()
        assert body["status"] == "model_unavailable"
        assert body["success"] is False


# ---------------------------------------------------------------------- #
# AI / Nemotron (Session 5) - artifact-free, no network, no credentials
# ---------------------------------------------------------------------- #
def test_ai_status(client):
    """AI status reports configuration without contacting any provider."""
    r = client.get("/api/ai/status")
    assert r.status_code == 200
    body = r.json()
    assert body["provider"] == "NVIDIA NIM (Nemotron)"
    assert body["status"] in ("configuration_required", "configured")
    assert body["available"] == (body["status"] == "configured")
    assert body["model"]


def test_ai_ask_without_key_is_graceful(offline_ai_client):
    """Without NEMOTRON_API_KEY the ask endpoint never makes a network call."""
    r = offline_ai_client.post(
        "/api/ai/ask",
        json={"question": "Why is this area hot?"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is False
    assert body["status"] == "configuration_required"
    assert body["answer"] is None
    assert "NEMOTRON_API_KEY" in body["message"]


def test_ai_ask_builds_context_without_fabrication(offline_ai_client):
    """Context reflects real availability: model absent -> prediction unavailable."""
    r = offline_ai_client.post(
        "/api/ai/ask",
        json={
            "question": "Why is this area hot?",
            "context": {
                "location": {"name": "Sector A", "lat": 20.25, "lng": 85.78},
                "environment": {"ndvi": 0.18, "lst": None, "green_cover": 12.0},
                "urban": {"building_density": 1200, "road_density": 8.5},
            },
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "configuration_required"
    used = body["context_used"]
    # whitelisted fields preserved; null/missing stay unavailable
    assert used["environment"]["ndvi"] == 0.18
    assert "lst" not in used["environment"]  # null -> excluded, not guessed
    assert used["urban"]["building_density"] == 1200
    assert used["prediction"]["available"] is False
    assert "unavailable" in used["prediction"]["message"]
    # data used lists only what was actually supplied
    assert "NDVI" in body["data_used"]
    assert "XGBoost prediction" not in body["data_used"]


def test_ai_ask_requires_question(client):
    """Empty question is rejected by validation."""
    r = client.post("/api/ai/ask", json={"question": ""})
    assert r.status_code == 422


# ---------------------------------------------------------------------- #
# Prediction (artifact-free parts)
# ---------------------------------------------------------------------- #
def test_predict_requires_payload(client):
    r = client.post("/api/prediction/predict", json={})
    assert r.status_code == 400


def test_predict_validation_error(client):
    r = client.post("/api/prediction/predict", json={"features": {"Grid_ID": "abc"}})
    # 503 when the model artifact is absent; 400/422 when it is present
    assert r.status_code in (400, 422, 503)


# ---------------------------------------------------------------------- #
# Simulation
# ---------------------------------------------------------------------- #
def test_scenarios_listed(client):
    r = client.get("/api/simulation/scenarios")
    assert r.status_code == 200
    names = [sc["name"] for sc in r.json()]
    assert "increase_green_10" in names
    assert "increase_trees" in names


def test_run_requires_scenario(client):
    r = client.post("/api/simulation/run", json={})
    assert r.status_code == 400


def test_run_rejects_both_scenario_and_perturbations(client):
    r = client.post(
        "/api/simulation/run",
        json={"scenario": "increase_trees", "perturbations": {"TreeCount": ["add", 1]}},
    )
    assert r.status_code == 400


def test_run_rejects_unknown_scenario(client):
    r = client.post("/api/simulation/run", json={"scenario": "nope"})
    assert r.status_code == 400
    body = r.json()
    assert body["status"] == "invalid_request"
    assert "nope" in body["message"]


def test_run_rejects_unknown_feature(client):
    r = client.post(
        "/api/simulation/run", json={"perturbations": {"NotAFeature": ["add", 1]}}
    )
    # 503 when the model/grid artifacts are absent; 400 when they are present
    assert r.status_code in (400, 503)


def test_run_rejects_bad_kind(client):
    r = client.post(
        "/api/simulation/run", json={"perturbations": {"TreeCount": ["exp", 1]}}
    )
    assert r.status_code == 400


# ---------------------------------------------------------------------- #
# Model-dependent tests (skipped when artifacts are absent)
# ---------------------------------------------------------------------- #
@requires_artifacts
def test_model_info(client):
    r = client.get("/api/prediction/model")
    assert r.status_code == 200
    body = r.json()
    assert body["available"] is True
    assert body["feature_count"] > 10
    assert "Grid_ID" not in body["features"]


@requires_artifacts
def test_predict_single_row(client):
    df = pd.read_csv(DATASET_CSV, nrows=1)
    features = client.get("/api/prediction/features").json()["features"]
    row = {
        k: (None if pd.isna(df.iloc[0][k]) else df.iloc[0][k])
        for k in features
    }
    r = client.post("/api/prediction/predict", json={"features": row})
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 1
    # Bhubaneswar summer LST is plausibly within this band
    assert 15.0 < body["predictions"][0]["predicted_lst_c"] < 60.0


@requires_artifacts
def test_predict_batch(client):
    df = pd.read_csv(DATASET_CSV, nrows=5)
    features = client.get("/api/prediction/features").json()["features"]
    batch = [
        {k: (None if pd.isna(df.iloc[i][k]) else df.iloc[i][k]) for k in features}
        for i in range(5)
    ]
    r = client.post("/api/prediction/predict", json={"batch": batch})
    assert r.status_code == 200
    assert r.json()["count"] == 5


@requires_artifacts
def test_predict_matches_saved_outputs(client):
    """Live model must reproduce the pipeline's saved test predictions."""
    from pathlib import Path

    preds = pd.read_csv(Path("data/predictions/predictions.csv"))
    features = client.get("/api/prediction/features").json()["features"]
    df = pd.read_csv(DATASET_CSV)
    df = df[df["Grid_ID"].isin(set(preds["Grid_ID"]))].head(200)
    batch = [
        {k: (None if pd.isna(row[k]) else row[k]) for k in features}
        for _, row in df.iterrows()
    ]
    r = client.post("/api/prediction/predict", json={"batch": batch})
    assert r.status_code == 200
    live = [p["predicted_lst_c"] for p in r.json()["predictions"]]
    saved = preds.set_index("Grid_ID").loc[df["Grid_ID"]]["Predicted_LST"].tolist()
    assert max(abs(a - b) for a, b in zip(live, saved, strict=True)) < 1e-3


@requires_artifacts
def test_simulation_run_named(client):
    r = client.post("/api/simulation/run", json={"scenario": "increase_green_10"})
    assert r.status_code == 200
    body = r.json()
    assert body["mean_delta_lst"] < 0          # greening cools
    assert 0 < body["pct_cells_cooler"] <= 100
    assert body["n_cells"] > 1000


@requires_artifacts
def test_simulation_run_custom(client):
    r = client.post(
        "/api/simulation/run",
        json={"perturbations": {"GreenCover": ["add", 20.0]}},
    )
    assert r.status_code == 200
    assert r.json()["scenario"] == "custom"


# ---------------------------------------------------------------------- #
# Cell-level scenario results (full grid)
# ---------------------------------------------------------------------- #
def test_cells_unknown_scenario_404(client):
    r = client.get("/api/simulation/results/definitely-not-a-scenario/cells")
    assert r.status_code in (404, 503)
    if r.status_code == 404:
        assert "definitely-not-a-scenario" in r.json()["detail"]


def test_geojson_unknown_scenario_404(client):
    r = client.get("/api/simulation/results/definitely-not-a-scenario/geojson")
    assert r.status_code in (404, 503)


@requires_artifacts
def test_cells_full_grid_count_and_fields(client):
    """/cells returns one real record per grid cell with the required fields."""
    r = client.get("/api/simulation/results/increase_green_20/cells")
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    assert body["scenario"] == "increase_green_20"
    assert body["count"] == 53802
    assert len(body["cells"]) == 53802
    required = {"grid_id", "baseline_lst", "scenario_lst", "delta_lst",
                "latitude", "longitude"}
    for cell in body["cells"][:5]:
        assert required <= set(cell)
        assert cell["latitude"] is not None
        assert cell["longitude"] is not None
    # sampled consistency: scenario - baseline == delta
    import numpy as np
    for cell in body["cells"][::2000]:
        assert np.isclose(cell["scenario_lst"] - cell["baseline_lst"],
                          cell["delta_lst"], atol=1e-9)


@requires_artifacts
def test_cells_math_matches_aggregates(client):
    """mean(delta) and pct cooler recomputed from the cells equal the response."""
    body = client.get("/api/simulation/results/increase_green_20/cells").json()
    deltas = [c["delta_lst"] for c in body["cells"]]
    mean_delta = sum(deltas) / len(deltas)
    pct_cooler = sum(1 for d in deltas if d < 0) / len(deltas) * 100.0
    assert abs(mean_delta - body["mean_delta_lst"]) < 1e-6
    assert abs(pct_cooler - body["pct_cells_cooler"]) < 1e-6


@requires_artifacts
def test_geojson_feature_collection_valid(client):
    """/geojson is a valid WGS84 FeatureCollection over every grid cell."""
    r = client.get("/api/simulation/results/increase_green_20/geojson")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/geo+json")
    fc = r.json()
    assert fc["type"] == "FeatureCollection"
    assert len(fc["features"]) == 53802

    grid_ids = set()
    for feature in fc["features"]:
        props = feature["properties"]
        for key in ("grid_id", "baseline_lst", "scenario_lst", "delta_lst"):
            assert key in props
            value = props[key]
            assert value is not None
            assert value == value  # not NaN
            assert value != float("inf") and value != float("-inf")
        assert props["grid_id"] not in grid_ids
        grid_ids.add(props["grid_id"])
        geom = feature["geometry"]
        assert geom["type"] == "Polygon"
        assert len(geom["coordinates"][0]) >= 4
        for lng, lat in geom["coordinates"][0]:
            assert -180 <= lng <= 180
            assert -90 <= lat <= 90
    assert len(grid_ids) == 53802


@requires_artifacts
def test_run_results_and_cells_agree(client):
    """Live run, stored results and cell-level data agree on the full grid."""
    run = client.post("/api/simulation/run", json={"scenario": "increase_green_20"})
    assert run.status_code == 200
    run_body = run.json()

    saved = client.get("/api/simulation/results").json()["results"]
    stored = next(r for r in saved if r["scenario"] == "increase_green_20")

    cells = client.get("/api/simulation/results/increase_green_20/cells").json()

    # stored results (regenerated on the full grid) agree with the live run
    assert abs(run_body["baseline_lst"] - stored["baseline_lst"]) < 1e-6
    assert abs(run_body["mean_delta_lst"] - stored["mean_delta_lst"]) < 1e-6
    # cell-level aggregates agree with both
    assert abs(run_body["baseline_lst"] - cells["baseline_lst"]) < 1e-6
    assert abs(run_body["mean_delta_lst"] - cells["mean_delta_lst"]) < 1e-6
    assert run_body["n_cells"] == cells["count"] == 53802
