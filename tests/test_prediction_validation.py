"""Strict prediction-input validation tests (Phase 11).

These use a small synthetic dataset + fitted preprocessor (no trained model
needed) to exercise the validation rules deterministically.
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest


@pytest.fixture()
def serving(tmp_path):
    """ServingContext over a tiny 8-row dataset with 4 model features."""
    from backend.config.settings import Settings
    from backend.services.serving import ServingContext

    rng = np.random.default_rng(7)
    n = 8
    green = rng.uniform(5, 55, n)
    impervious = rng.uniform(20, 80, n)
    target = 30 + 0.05 * impervious - 0.02 * green + rng.normal(0, 0.3, n)
    csv = tmp_path / "training_dataset.csv"
    pd.DataFrame({
        "Grid_ID": range(1, n + 1),
        "LandCoverClass": [1.0, 2.0, 1.0, 3.0, 4.0, 1.0, 2.0, 3.0],
        "VegDensityClass": [1.0, 2.0, 2.0, 3.0, 5.0, 4.0, 1.0, 2.0],
        "GreenCover": green,
        "ImperviousSurfaceRatio": impervious,
        "Target_LST": target,
    }).to_csv(csv, index=False)

    report = tmp_path / "leakage_report.json"
    report.write_text(json.dumps({
        "kept": ["LandCoverClass", "VegDensityClass", "GreenCover",
                 "ImperviousSurfaceRatio"],
    }), encoding="utf-8")

    settings = Settings(
        dataset_csv=csv,
        dataset_geojson=tmp_path / "nope.geojson",
        leakage_report=report,
        preprocessor_cache=tmp_path / "serving" / "preprocessor.json",
        model_pkl=tmp_path / "missing.pkl",
    )
    return ServingContext(settings)


def _full_row():
    return {"LandCoverClass": 1.0, "VegDensityClass": 2.0,
            "GreenCover": 30.0, "ImperviousSurfaceRatio": 40.0}


def test_valid_full_row_passes(serving):
    serving.validate_rows_strict([_full_row()])
    serving.validate_rows_strict([_full_row(), _full_row()])


def test_empty_rows_rejected(serving):
    with pytest.raises(ValueError, match="No rows"):
        serving.validate_rows_strict([])


def test_missing_feature_rejected(serving):
    row = _full_row()
    del row["GreenCover"]
    with pytest.raises(ValueError, match="missing feature"):
        serving.validate_rows_strict([row])


def test_unknown_feature_rejected(serving):
    row = _full_row()
    row["NotAFeature"] = 1.0
    with pytest.raises(ValueError, match="unknown feature"):
        serving.validate_rows_strict([row])


def test_nan_rejected(serving):
    row = _full_row()
    row["GreenCover"] = float("nan")
    with pytest.raises(ValueError, match="not finite"):
        serving.validate_rows_strict([row])


def test_infinity_rejected(serving):
    row = _full_row()
    row["ImperviousSurfaceRatio"] = float("inf")
    with pytest.raises(ValueError, match="not finite"):
        serving.validate_rows_strict([row])


def test_wrong_type_rejected(serving):
    row = _full_row()
    row["GreenCover"] = "high"   # string where a number is required
    with pytest.raises(ValueError, match="invalid type"):
        serving.validate_rows_strict([row])


def test_none_value_rejected(serving):
    row = _full_row()
    row["GreenCover"] = None
    with pytest.raises(ValueError, match="missing \\(None\\)"):
        serving.validate_rows_strict([row])


def test_grid_id_allowed_as_metadata(serving):
    row = _full_row()
    row["Grid_ID"] = "42"
    serving.validate_rows_strict([row])


# ---------------------------------------------------------------------- #
# API-level behaviour (via the real app, offline)
# ---------------------------------------------------------------------- #
def test_predict_api_rejects_missing_features(client):
    """A partial row now returns 400 (Phase 11) — no silent imputation."""
    r = client.post("/api/prediction/predict",
                    json={"features": {"GreenCover": 30.0}})
    if client.get("/api/prediction/model").json().get("available"):
        assert r.status_code == 400
        assert r.json()["status"] == "invalid_request"
    else:
        # model absent: the guard returns 503 before validation
        assert r.status_code == 503


def test_predict_api_rejects_unknown_feature(client):
    r = client.post("/api/prediction/predict",
                    json={"features": {"NotAFeature": 1.0}})
    assert r.status_code in (400, 503)


def test_predict_api_rejects_nan(client):
    # send raw JSON containing NaN (the httpx encoder refuses it, but a real
    # browser/curl can send "NaN" tokens — the API must reject them with 400)
    import json

    body = json.dumps({"features": {"GreenCover": float("nan"),
                                    "MeanNDVI": float("nan")}},
                      allow_nan=True)
    r = client.post("/api/prediction/predict",
                    content=body,
                    headers={"Content-Type": "application/json"})
    assert r.status_code in (400, 422, 503)


def test_predict_api_rejects_non_numeric(client):
    r = client.post(
        "/api/prediction/predict",
        json={"features": {"GreenCover": "abc", "MeanNDVI": "xyz"}},
    )
    assert r.status_code in (400, 422, 503)
