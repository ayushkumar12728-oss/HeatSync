"""Tests for the serving context: preprocessor cache round-trip + encoding types."""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest


@pytest.fixture()
def tiny_dataset(tmp_path):
    """A tiny CSV with the two categorical columns stored as floats.

    The numeric features are noisy (not perfectly correlated with the target)
    so the leakage detector keeps them - mirroring the real dataset.
    """
    rng = np.random.default_rng(7)
    n = 8
    green = rng.uniform(5, 55, n)
    impervious = rng.uniform(20, 80, n)
    target = 30 + 0.05 * impervious - 0.02 * green + rng.normal(0, 0.3, n)
    green[2] = np.nan  # exercise median imputation
    csv = tmp_path / "training_dataset.csv"
    pd.DataFrame({
        "Grid_ID": range(1, n + 1),
        "LandCoverClass": [1.0, 2.0, 1.0, 3.0, 4.0, 1.0, 2.0, 3.0],
        "VegDensityClass": [1.0, 2.0, 2.0, 3.0, 5.0, 4.0, 1.0, 2.0],
        "GreenCover": green,
        "ImperviousSurfaceRatio": impervious,
        "Target_LST": target,
    }).to_csv(csv, index=False)
    return csv


@pytest.fixture()
def settings(tmp_path, tiny_dataset):
    from backend.config.settings import Settings

    report = tmp_path / "leakage_report.json"
    report.write_text(json.dumps({
        "kept": ["LandCoverClass", "VegDensityClass", "GreenCover",
                 "ImperviousSurfaceRatio"],
    }), encoding="utf-8")
    return Settings(
        dataset_csv=tiny_dataset,
        dataset_geojson=tmp_path / "nope.geojson",
        leakage_report=report,
        preprocessor_cache=tmp_path / "serving" / "preprocessor.json",
        model_pkl=tmp_path / "missing.pkl",  # never touched in these tests
    )


def test_cache_round_trip_preserves_float_encoding_keys(settings):
    """Float-typed categorical values must survive the JSON cache round-trip."""
    from backend.services.serving import ServingContext

    first = ServingContext(settings)
    encodings = first.preprocessor.encodings
    assert set(encodings["LandCoverClass"].keys()) == {1.0, 2.0, 3.0, 4.0}
    assert settings.preprocessor_cache.exists()  # cache written

    second = ServingContext(settings)
    restored = second.preprocessor.encodings
    assert restored == encodings  # float keys restored exactly


def test_transform_rows_imputes_missing_and_codes(settings):
    from backend.services.serving import ServingContext

    serving = ServingContext(settings)
    X = serving.transform_rows([
        {"LandCoverClass": 1.0, "VegDensityClass": 2.0, "GreenCover": 10.0,
         "ImperviousSurfaceRatio": 30.0},
        {"GreenCover": 20.0},  # categoricals + impervious imputed
    ])
    assert X.shape == (2, 4)
    assert X.iloc[1]["LandCoverClass"] == serving.preprocessor.encodings["LandCoverClass"][1.0]


def test_transform_rows_handles_unseen_categorical(settings):
    from backend.services.serving import ServingContext

    serving = ServingContext(settings)
    X = serving.transform_rows([{"LandCoverClass": 99.0, "VegDensityClass": 1.0,
                                 "GreenCover": 10.0, "ImperviousSurfaceRatio": 30.0}])
    # unseen value falls back to the most common training code (1.0 -> code of value 1.0)
    known = set(serving.preprocessor.encodings["LandCoverClass"].values())
    assert X.iloc[0]["LandCoverClass"] in known
