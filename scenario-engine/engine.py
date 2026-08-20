#!/usr/bin/env python3
"""
Simulation Engine
=================
Simulates the impact of urban interventions on the Urban Heat Island using
the *trained* XGBoost model and the *unchanged* ai-engine scenario mechanics.

Interventions:
    - Tree planting       (shade + evapotranspiration -> cooler surfaces)
    - Cool roofs          (reflective surfaces -> less heat absorbed)
    - Green corridors     (connected green spaces -> ventilation channels)
    - Plus the 7 canonical ai-engine sensitivity scenarios
      (increase_green_10/20, decrease_buildings_10/20, increase_trees,
       increase_parks, increase_water)

Every perturbation is applied with the same clamping rules as the training
pipeline (``ai-engine/scenario_simulator.ScenarioSimulator._perturb``), so
simulation results are consistent with the offline sensitivity analysis.

Standalone usage::

    python scenario-engine/engine.py              # run all scenarios, print table

Library usage::

    from scenario_engine.engine import SimulationEngine
    engine = SimulationEngine()                   # auto-loads best_model.pkl
    modified = engine.simulate_tree_planting(grid_df, num_trees=200)
    table = engine.compare_scenarios(base_df, {"trees": modified})
"""

from __future__ import annotations

import importlib.util
import logging
import sys
from collections.abc import Callable
from pathlib import Path

import numpy as np
import pandas as pd

# scenario-engine/engine.py -> scenario-engine -> project root
PROJECT_ROOT = Path(__file__).resolve().parent.parent
AI_ENGINE_DIR = PROJECT_ROOT / "ai-engine"
SIM_ENGINE_DIR = Path(__file__).resolve().parent

log = logging.getLogger("scenario_engine")


def _load_module(name: str, directory: Path, relative_path: str):
    """Load a module by file path (dir names contain hyphens)."""
    path = directory / relative_path
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _load_ai_module(name: str, relative_path: str):
    return _load_module(name, AI_ENGINE_DIR, relative_path)


def _default_cfg():
    return _load_ai_module("sim_aie_config", "config.py").Config()


def _default_simulator(cfg):
    return _load_ai_module("sim_aie_scenario", "scenario_simulator.py").ScenarioSimulator(cfg)


def _default_predict_fn(model):
    return lambda df: model.predict(df)


def _load_model() -> object:
    """Load the trained model (joblib) from models/."""
    import joblib

    path = PROJECT_ROOT / "models" / "best_model.pkl"
    if not path.exists():
        raise FileNotFoundError(
            f"Trained model not found: {path}. Run `python ai-engine/main.py` "
            "or pass an explicit model/predict_fn to SimulationEngine."
        )
    return joblib.load(path)


def _load_intervention(name: str, folder: str):
    """Load scenario-engine/<folder>/scenario.py under a unique alias."""
    return _load_module(name, SIM_ENGINE_DIR / folder, "scenario.py")


def _load_default_grid(features: list[str], max_rows: int | None = None) -> pd.DataFrame:
    """Rebuild the transformed feature matrix from the training dataset.

    Reuses the unchanged ai-engine column-role / leakage / preprocessing steps
    so the matrix matches training exactly. ~7 s for the full 53 k-cell grid.
    """
    cfg = _default_cfg()
    loader = _load_ai_module("sim_aie_loader", "data_loader.py").DataLoader(cfg)
    df = loader.load()
    schema = loader.report()
    selector = _load_ai_module("sim_aie_selector", "feature_selection.py")
    df_clean, kept = selector.FeatureSelector(cfg, schema).run(df)
    pre = _load_ai_module("sim_aie_pre", "preprocessing.py").Preprocessor(cfg)
    X = pre.fit_transform(df_clean[kept], schema["categorical_columns"])
    if max_rows and max_rows < len(X):
        X = X.sample(n=max_rows, random_state=42)
    return X


class SimulationEngine:
    """Runs urban-intervention scenarios against the trained model.
    
    Supports area-based interventions:
    - Polygon: user draws an arbitrary polygon
    - Neighborhood: select from predefined neighborhoods
    - Radius: circular area around a point
    - Cells: direct cell selection
    
    Before/After validation:
    - Cells outside intervention area remain unchanged
    - Area statistics reported (affected cells, unaffected cells, area km²)
    """

    def __init__(self, predict_fn: Callable[[pd.DataFrame], np.ndarray] | None = None,
                 model: object | None = None,
                 cfg: object | None = None):
        """
        Args:
            predict_fn: callable DataFrame(rows x features) -> predictions.
                        Defaults to the trained XGBoost model when not given.
            model:      a fitted sklearn/xgboost regressor (used to build the
                        default predict_fn when ``predict_fn`` is None).
            cfg:        ai-engine Config bundle (scenario definitions + bounds).
        """
        self.cfg = cfg if cfg is not None else _default_cfg()
        self._simulator = _default_simulator(self.cfg)
        if predict_fn is not None:
            self.predict_fn = predict_fn
        elif model is not None:
            self.predict_fn = _default_predict_fn(model)
            self.model = model
        else:
            self.model = _load_model()
            self.predict_fn = _default_predict_fn(self.model)
        
        # Area selector is lazy-loaded on first area-based scenario call
        self._area_selector = None

    # ------------------------------------------------------------------ #
    # Scenario definitions
    # ------------------------------------------------------------------ #
    @property
    def scenarios(self) -> list[dict]:
        """The 7 canonical sensitivity scenarios from the ai-engine config."""
        return [
            {"name": sc.name, "description": sc.description,
             "perturbations": dict(sc.perturbations)}
            for sc in self.cfg.scenarios.scenarios
        ]

    def get_scenario(self, name: str) -> dict | None:
        for sc in self.scenarios:
            if sc["name"] == name:
                return sc
        return None

    # ------------------------------------------------------------------ #
    # Core perturbation / prediction primitives
    # ------------------------------------------------------------------ #
    def perturb(self, grid: pd.DataFrame,
                perturbations: dict[str, tuple]) -> pd.DataFrame:
        """Apply perturbations with the ai-engine clamping rules."""
        return self._simulator._perturb(grid, perturbations)

    def predict(self, grid: pd.DataFrame) -> np.ndarray:
        return np.asarray(self.predict_fn(grid)).ravel()

    def _stats(self, baseline: np.ndarray, perturbed: np.ndarray) -> dict:
        delta = perturbed - baseline
        return {
            "baseline_lst": float(np.mean(baseline)),
            "mean_predicted_lst": float(np.mean(perturbed)),
            "mean_delta_lst": float(np.mean(delta)),
            "min_delta": float(np.min(delta)),
            "max_delta": float(np.max(delta)),
            "pct_cells_cooler": float(np.mean(delta < 0) * 100.0),
            "n_cells": len(baseline),
        }

    # ------------------------------------------------------------------ #
    # Interventions (public API kept from the original stub)
    # ------------------------------------------------------------------ #
    def simulate_tree_planting(self, grid: pd.DataFrame,
                               num_trees: int = 100) -> pd.DataFrame:
        """Return the grid after planting ``num_trees`` trees per cell."""
        mod = _load_intervention("sim_tree_scenario", "tree")
        return self.perturb(grid, mod.build_perturbations(num_trees=num_trees))

    def simulate_cool_roofs(self, grid: pd.DataFrame,
                            coverage_pct: float = 30.0) -> pd.DataFrame:
        """Return the grid after converting ``coverage_pct`` % of roofs to cool roofs."""
        mod = _load_intervention("sim_coolroof_scenario", "cool_roof")
        return self.perturb(grid, mod.build_perturbations(coverage_pct=coverage_pct))

    def simulate_green_corridor(self, grid: pd.DataFrame,
                                corridor_width: int = 50) -> pd.DataFrame:
        """Return the grid after introducing a ``corridor_width`` m green corridor."""
        mod = _load_intervention("sim_green_scenario", "green_corridor")
        return self.perturb(grid, mod.build_perturbations(corridor_width=corridor_width))

    # ------------------------------------------------------------------ #
    # Scenario runs
    # ------------------------------------------------------------------ #
    def run_scenario(self, name: str, grid: pd.DataFrame) -> dict:
        """Run one canonical scenario; returns summary statistics."""
        sc = self.get_scenario(name)
        if sc is None:
            raise ValueError(f"Unknown scenario '{name}'. Available: "
                             f"{[s['name'] for s in self.scenarios]}")
        baseline = self.predict(grid)
        perturbed = self.predict(self.perturb(grid, sc["perturbations"]))
        stats = self._stats(baseline, perturbed)
        return {"scenario": name, "description": sc["description"], **stats,
                "n_perturbed_features": len(sc["perturbations"])}

    def run_scenario_area(
        self,
        name: str,
        grid: pd.DataFrame,
        area_mode: str = "city",
        area_params: dict | None = None,
    ) -> dict:
        """Run a scenario with area-based cell selection.

        Args:
            name: Scenario name.
            grid: Full feature grid DataFrame.
            area_mode: One of 'city', 'polygon', 'neighborhood', 'radius', 'cells'.
            area_params: Parameters for the area selection mode.
                - polygon: {'coords': [[lon, lat], ...]}
                - neighborhood: {'name': 'area_name'}
                - radius: {'center_lon': float, 'center_lat': float, 'radius_m': float}
                - cells: {'cell_ids': ['gid1', 'gid2', ...]}

        Returns:
            Dict with scenario results, area stats, and before/after validation.
        """
        try:
            from scenario_engine.area_selector import (
                apply_area_intervention,
                create_area_mask,
                validate_before_after,
            )
        except ImportError:
            import importlib.util
            spec = importlib.util.spec_from_file_location(
                "area_selector",
                Path(__file__).resolve().parent / "area_selector.py"
            )
            area_selector_mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(area_selector_mod)
            apply_area_intervention = area_selector_mod.apply_area_intervention
            create_area_mask = area_selector_mod.create_area_mask
            validate_before_after = area_selector_mod.validate_before_after

        sc = self.get_scenario(name)
        if sc is None:
            raise ValueError(f"Unknown scenario '{name}'. Available: "
                             f"{[s['name'] for s in self.scenarios]}")

        # Lazy-load area selector
        if self._area_selector is None:
            try:
                from scenario_engine.area_selector import AreaSelector
            except ImportError:
                import importlib.util
                spec = importlib.util.spec_from_file_location(
                    "area_selector",
                    Path(__file__).resolve().parent / "area_selector.py"
                )
                area_selector_mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(area_selector_mod)
                AreaSelector = area_selector_mod.AreaSelector
            self._area_selector = AreaSelector()

        selector = self._area_selector
        total_cells = len(grid)
        area_params = area_params or {}

        if area_mode == "city":
            # Apply to entire city (backwards-compatible)
            selection = selector.select_by_cells([], total_cells=total_cells)
            selection.cell_indices = list(range(total_cells))
            selection.cell_count = total_cells
            selection.total_cells = total_cells
            selection.area_km2 = total_cells * 0.01  # 100m grid
            selection.description = "Full city"
            selection.affected_pct = 100.0
            mask = np.ones(total_cells, dtype=bool)
        elif area_mode == "polygon":
            coords = area_params.get("coords", [])
            selection = selector.select_by_polygon(coords, total_cells=total_cells)
            mask = create_area_mask(selection, total_cells)
        elif area_mode == "neighborhood":
            nh_name = area_params.get("name", "")
            selection = selector.select_by_neighborhood(nh_name, total_cells=total_cells)
            mask = create_area_mask(selection, total_cells)
        elif area_mode == "radius":
            selection = selector.select_by_radius(
                center_lon=area_params.get("center_lon", 85.788),
                center_lat=area_params.get("center_lat", 20.252),
                radius_m=area_params.get("radius_m", 500),
                total_cells=total_cells,
            )
            mask = create_area_mask(selection, total_cells)
        elif area_mode == "cells":
            cell_ids = area_params.get("cell_ids", [])
            selection = selector.select_by_cells(cell_ids, total_cells=total_cells)
            mask = create_area_mask(selection, total_cells)
        else:
            raise ValueError(f"Unknown area_mode: {area_mode}")

        # Run baseline
        baseline = self.predict(grid)

        # Apply perturbations only to masked cells
        X_pert = apply_area_intervention(grid, mask, sc["perturbations"], self._simulator)
        perturbed = self.predict(X_pert)

        # Before/after validation
        validation = validate_before_after(baseline, perturbed, mask)

        # Statistics
        delta = perturbed - baseline
        stats = self._stats(baseline, perturbed)

        return {
            "scenario": name,
            "description": sc["description"],
            **stats,
            "n_perturbed_features": len(sc["perturbations"]),
            "area": selection.to_dict(),
            "validation": validation,
        }

    def run_all(self, grid: pd.DataFrame | None = None,
                max_rows: int | None = 5000) -> pd.DataFrame:
        """Run the 7 canonical + 3 intervention scenarios, ranked by cooling.

        ``grid`` defaults to a sample of the training dataset (requires the
        ai-engine dataset CSV).
        """
        if grid is None:
            grid = _load_default_grid(self._feature_names(), max_rows=max_rows)
        rows = []
        for name in [s["name"] for s in self.scenarios]:
            rows.append(self.run_scenario(name, grid))
        for label, fn in (
            ("tree_planting", self.simulate_tree_planting),
            ("cool_roofs_30pct", self.simulate_cool_roofs),
            ("green_corridor", self.simulate_green_corridor),
        ):
            baseline = self.predict(grid)
            perturbed = self.predict(fn(grid))
            rows.append({"scenario": label, "description": "", **self._stats(baseline, perturbed)})
        return (pd.DataFrame(rows)
                .sort_values("mean_delta_lst")
                .reset_index(drop=True))

    def _feature_names(self) -> list[str]:
        report = self.cfg.paths.reports_dir / "leakage_report.json"
        if report.exists():
            import json
            return list(json.loads(report.read_text(encoding="utf-8"))["kept"])
        return []

    # ------------------------------------------------------------------ #
    # Comparison
    # ------------------------------------------------------------------ #
    def compare_scenarios(self, base: pd.DataFrame,
                          scenarios: dict[str, pd.DataFrame]) -> pd.DataFrame:
        """Compare scenario results against a baseline grid.

        Args:
            base:       baseline feature DataFrame.
            scenarios:  mapping of scenario name -> perturbed feature DataFrame.

        Returns:
            Sorted comparison table (coolest first).
        """
        baseline = self.predict(base)
        rows = []
        for name, grid in scenarios.items():
            perturbed = self.predict(grid)
            rows.append({"scenario": name, **self._stats(baseline, perturbed)})
        return (pd.DataFrame(rows)
                .sort_values("mean_delta_lst")
                .reset_index(drop=True))


def main() -> int:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s | %(levelname)-7s | %(message)s")
    print("Urban Digital Twin - Simulation Engine")
    print("=" * 66)
    engine = SimulationEngine()
    print(f"Model           : {type(engine.model).__name__}")
    print(f"Canonical       : {len(engine.scenarios)} scenarios + 3 interventions")
    table = engine.run_all()
    print("=" * 66)
    print(table[["scenario", "mean_delta_lst", "pct_cells_cooler"]]
          .to_string(index=False, float_format=lambda v: f"{v:+.3f}"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
