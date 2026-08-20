"""
Sensitivity / scenario analysis (STEP 9)
========================================
Apply urban-intervention scenarios to the full training grid (all 53,802
cells) and predict the resulting LST change with the final model:

    * Increase green cover       (+10%, +20%)
    * Decrease buildings         (-10%, -20%)
    * Increase trees
    * Increase parks
    * Increase water

Each scenario perturbs the coherent set of driving features (green cover,
NDVI, land-cover percentages, imperviousness, cooling indices), clamps the
values to physically sensible bounds, re-predicts and reports mean LST
change. Outputs: reports/sensitivity_analysis.csv + plots/sensitivity.png.

The full grid is used (rather than a held-out test set) so these aggregate
results agree with the live simulation API and the cell-level scenario
outputs, which all operate on the same 53,802-cell grid.
"""

from __future__ import annotations

import logging
from typing import Dict, List

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from tqdm import tqdm

log = logging.getLogger("aie.scenario_simulator")


class ScenarioSimulator:
    """Runs the configured intervention scenarios against the final model."""

    def __init__(self, cfg):
        self.cfg = cfg
        # feature -> (lower bound, upper bound) for clamping perturbed values.
        self.bounds: Dict[str, tuple] = {
            "GreenCover": (0.0, 100.0),
            "LandCover_VegetationPct": (0.0, 100.0),
            "LandCover_BuiltupPct": (0.0, 100.0),
            "LandCover_WaterPct": (0.0, 100.0),
            "LandCover_BareLandPct": (0.0, 100.0),
            "GreenSpacePct": (0.0, 100.0),
            "VegetationDensity": (0.0, 100.0),
            "TreeDensity": (0.0, 100.0),
            "BuildingCoveragePct": (0.0, 100.0),
            "ImperviousSurfaceRatio": (0.0, 100.0),
            "MeanNDVI": (-1.0, 1.0),
            "MaxNDVI": (-1.0, 1.0),
            "MinNDVI": (-1.0, 1.0),
            "HeatVulnerabilityIndex": (0.0, 1.0),
            "TreeCount": (0.0, np.inf),
            "BuildingCount": (0.0, np.inf),
            "DistToPark": (1.0, np.inf),
            "DistToWater": (1.0, np.inf),
            "GreenToBuiltRatio": (0.0, np.inf),
            "VegetationCoolingIndex": (0.0, np.inf),
            "CoolingDistanceIndex": (0.0, np.inf),
        }

    # ------------------------------------------------------------------ #
    def _perturb(self, df: pd.DataFrame, perturbations: Dict[str, tuple]) -> pd.DataFrame:
        """Apply additive / multiplicative perturbations with clamping."""
        out = df.copy()
        for col, (kind, val) in perturbations.items():
            if col not in out.columns:
                log.warning("Scenario feature '%s' not in dataset - skipped.", col)
                continue
            if kind == "add":
                out[col] = out[col] + val
            elif kind == "mul":
                out[col] = out[col] * val
            elif kind == "min":
                out[col] = out[col].clip(upper=val)
            elif kind == "max":
                out[col] = out[col].clip(lower=val)
            else:
                raise ValueError(f"Unknown perturbation kind: {kind}")
            if col in self.bounds:
                lo, hi = self.bounds[col]
                out[col] = out[col].clip(lower=lo, upper=hi)
        return out

    # ------------------------------------------------------------------ #
    def run(self, model, X_test: pd.DataFrame, y_test: pd.Series) -> pd.DataFrame:
        """Predict baseline + scenario LSTs and compute deltas."""
        scenarios = self.cfg.scenarios.scenarios
        log.info("=" * 72)
        log.info("STEP 9 - Sensitivity analysis (%d scenarios)", len(scenarios))
        log.info("=" * 72)

        baseline = model.predict(X_test)
        rows = []
        with tqdm(total=len(scenarios), desc="Scenarios", ncols=100) as pbar:
            for sc in scenarios:
                X_pert = self._perturb(X_test, sc.perturbations)
                pred = model.predict(X_pert)
                delta = float(np.mean(pred - baseline))
                rows.append({
                    "scenario": sc.name,
                    "description": sc.description,
                    "mean_predicted_lst": float(np.mean(pred)),
                    "baseline_lst": float(np.mean(baseline)),
                    "mean_delta_lst": delta,
                    "min_delta": float(np.min(pred - baseline)),
                    "max_delta": float(np.max(pred - baseline)),
                    "pct_cells_cooler": float(np.mean(pred < baseline) * 100.0),
                })
                log.info("  %-22s delta LST = %+.3f °C", sc.name, delta)
                pbar.update(1)

        df = pd.DataFrame(rows)
        df = df.sort_values("mean_delta_lst").reset_index(drop=True)
        df.to_csv(self.cfg.paths.reports_dir / "sensitivity_analysis.csv", index=False)
        self._plot(df)
        return df

    # ------------------------------------------------------------------ #
    def _plot(self, df: pd.DataFrame) -> None:
        fig, ax = plt.subplots(figsize=(11, 6))
        colors = ["#2ca02c" if d < 0 else "#d62728" for d in df["mean_delta_lst"]]
        bars = ax.bar(df["scenario"], df["mean_delta_lst"], color=colors)
        ax.axhline(0, color="black", lw=0.8)
        ax.set_ylabel("mean predicted LST change (°C)")
        ax.set_title("Sensitivity analysis - effect of urban interventions on LST")
        ax.set_xticklabels(df["scenario"], rotation=30, ha="right")
        for b, v in zip(bars, df["mean_delta_lst"]):
            ax.text(b.get_x() + b.get_width() / 2, v + (0.02 if v >= 0 else -0.07),
                    f"{v:+.2f}", ha="center", fontsize=8)
        ax.grid(axis="y", alpha=0.3)
        fig.tight_layout()
        out = self.cfg.paths.plots_dir / "sensitivity_analysis.png"
        fig.savefig(out, dpi=150, bbox_inches="tight")
        plt.close(fig)
        log.info("Saved plot: %s", out)
