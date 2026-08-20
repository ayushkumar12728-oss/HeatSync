"""Unit tests for the simulation engine (standalone, no trained model needed)."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scenario-engine"))

from engine import SimulationEngine


# ---------------------------------------------------------------------- #
# Fixtures
# ---------------------------------------------------------------------- #
def make_grid(n: int = 40) -> pd.DataFrame:
    rng = np.random.default_rng(0)
    return pd.DataFrame({
        "GreenCover": rng.uniform(0, 60, n),
        "MeanNDVI": rng.uniform(-0.2, 0.7, n),
        "TreeCount": rng.uniform(0, 200, n),
        "TreeDensity": rng.uniform(0, 50, n),
        "ImperviousSurfaceRatio": rng.uniform(20, 90, n),
        "BuildingCoveragePct": rng.uniform(5, 60, n),
        "HeatVulnerabilityIndex": rng.uniform(0.1, 0.9, n),
        "VegetationCoolingIndex": rng.uniform(0.0, 1.5, n),
        "GreenSpacePct": rng.uniform(0, 40, n),
        "GreenToBuiltRatio": rng.uniform(0, 2, n),
        "DistToPark": rng.uniform(10, 2000, n),
        "VegetationDensity": rng.uniform(0, 40, n),
    })


def linear_model(df: pd.DataFrame) -> np.ndarray:
    """Known model: greening cools, imperviousness warms."""
    return (35.0 - 0.05 * df["GreenCover"] - 2.0 * df["MeanNDVI"]
            + 0.01 * df["ImperviousSurfaceRatio"]).to_numpy()


@pytest.fixture(scope="module")
def engine() -> SimulationEngine:
    return SimulationEngine(predict_fn=linear_model)


# ---------------------------------------------------------------------- #
# Perturbation mechanics
# ---------------------------------------------------------------------- #
def test_perturb_add(engine):
    grid = make_grid()
    out = engine.perturb(grid, {"GreenCover": ("add", 10.0)})
    assert np.allclose(out["GreenCover"], grid["GreenCover"] + 10.0)


def test_perturb_mul(engine):
    grid = make_grid()
    out = engine.perturb(grid, {"GreenToBuiltRatio": ("mul", 1.2)})
    assert np.allclose(out["GreenToBuiltRatio"], grid["GreenToBuiltRatio"] * 1.2)


def test_perturb_clamps_to_bounds(engine):
    grid = make_grid()
    out = engine.perturb(grid, {"GreenCover": ("add", 500.0)})
    assert out["GreenCover"].max() <= 100.0
    assert out["GreenCover"].min() >= 0.0


def test_perturb_ignores_missing_column(engine):
    grid = make_grid()
    out = engine.perturb(grid, {"DoesNotExist": ("add", 5.0)})
    pd.testing.assert_frame_equal(out, grid)


# ---------------------------------------------------------------------- #
# Interventions
# ---------------------------------------------------------------------- #
def test_tree_planting_increases_tree_count(engine):
    grid = make_grid()
    out = engine.simulate_tree_planting(grid, num_trees=120)
    assert np.allclose(out["TreeCount"], grid["TreeCount"] + 120.0)
    assert (out["MeanNDVI"] > grid["MeanNDVI"]).all()


def test_tree_planting_negative_rejected(engine):
    with pytest.raises(ValueError):
        engine.simulate_tree_planting(make_grid(), num_trees=-5)


def test_cool_roofs_reduces_imperviousness(engine):
    grid = make_grid()
    out = engine.simulate_cool_roofs(grid, coverage_pct=50.0)
    assert (out["ImperviousSurfaceRatio"] < grid["ImperviousSurfaceRatio"]).all()
    assert (out["BuildingCoveragePct"] < grid["BuildingCoveragePct"]).all()


def test_cool_roofs_out_of_range_rejected(engine):
    with pytest.raises(ValueError):
        engine.simulate_cool_roofs(make_grid(), coverage_pct=150.0)


def test_green_corridor_increases_greenspace(engine):
    grid = make_grid()
    out = engine.simulate_green_corridor(grid, corridor_width=100)
    assert (out["GreenSpacePct"] > grid["GreenSpacePct"]).all()
    assert (out["DistToPark"] < grid["DistToPark"]).all()


# ---------------------------------------------------------------------- #
# Scenario runs & comparison
# ---------------------------------------------------------------------- #
def test_run_scenario_unknown_raises(engine):
    with pytest.raises(ValueError):
        engine.run_scenario("does_not_exist", make_grid())


def test_run_scenario_returns_stats(engine):
    result = engine.run_scenario("increase_green_10", make_grid())
    assert result["scenario"] == "increase_green_10"
    for key in ("mean_delta_lst", "baseline_lst", "mean_predicted_lst",
                "min_delta", "max_delta", "pct_cells_cooler"):
        assert key in result


def test_compare_scenarios_ranks_coolest_first(engine):
    grid = make_grid()
    warm = engine.perturb(grid, {"ImperviousSurfaceRatio": ("add", 30.0)})
    cool = engine.perturb(grid, {"GreenCover": ("add", 30.0)})
    table = engine.compare_scenarios(grid, {"warm": warm, "cool": cool})
    assert table.iloc[0]["scenario"] == "cool"
    assert table.iloc[-1]["scenario"] == "warm"
    assert (table["mean_delta_lst"].diff().dropna() >= 0).all()  # ascending


def test_compare_scenarios_linear_math(engine):
    grid = make_grid()
    cool = engine.perturb(grid, {"GreenCover": ("add", 10.0)})
    table = engine.compare_scenarios(grid, {"cool": cool})
    # linear model: -0.05 * +10 green cover
    assert table.iloc[0]["mean_delta_lst"] == pytest.approx(-0.5, abs=1e-9)
