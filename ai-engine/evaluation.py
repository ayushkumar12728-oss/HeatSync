"""
Evaluation (STEP 11)
====================
Generates:

    * metrics.json            - all regression metrics + CV + leaderboard summary
    * Confusion analysis      - predicted vs actual UHI intensity class
    * Residual plots          - residuals vs predicted, residual histogram
    * Prediction vs Actual    - scatter with y=x line
    * Spatial error map       - residuals mapped on the 100 m grid
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Dict, List, Optional

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

log = logging.getLogger("aie.evaluation")


class Evaluator:
    """Computes metrics and produces all evaluation artifacts."""

    def __init__(self, cfg):
        self.cfg = cfg
        self.metrics: Dict = {}

    # ------------------------------------------------------------------ #
    def confusion_analysis(self, y_true: np.ndarray, y_pred: np.ndarray) -> Dict:
        """Bin LST into UHI intensity classes and build a confusion matrix."""
        # quantile-based bins on the observed distribution
        _, edges = pd.qcut(pd.Series(y_true), q=3, labels=False, retbins=True,
                           duplicates="drop")
        edges = list(np.asarray(edges, dtype=float))
        n_bins = len(edges) - 1
        labels = ["Low", "Medium", "High"][:n_bins]

        actual_class = pd.cut(pd.Series(y_true), bins=edges, labels=labels,
                              include_lowest=True)
        pred_class = pd.cut(pd.Series(y_pred), bins=edges, labels=labels,
                            include_lowest=True)

        cm = pd.crosstab(actual_class, pred_class, rownames=["Actual"], colnames=["Predicted"])
        cm = cm.reindex(index=labels, columns=labels, fill_value=0)
        accuracy = float(np.mean(actual_class == pred_class))
        kappa = self._cohen_kappa(cm)

        out = {
            "bins": edges,
            "labels": labels,
            "confusion_matrix": cm.astype(int).to_dict(),
            "class_accuracy": accuracy,
            "cohen_kappa": kappa,
            "n_misclassified": int(np.sum(actual_class != pred_class)),
        }

        # plot
        fig, ax = plt.subplots(figsize=(7, 6))
        im = ax.imshow(cm.values, cmap="Blues")
        ax.set_xticks(range(len(labels))); ax.set_xticklabels(labels)
        ax.set_yticks(range(len(labels))); ax.set_yticklabels(labels)
        for i in range(len(labels)):
            for j in range(len(labels)):
                ax.text(j, i, int(cm.values[i, j]), ha="center", va="center",
                        color="white" if cm.values[i, j] > cm.values.max() / 2 else "black")
        ax.set_xlabel("Predicted UHI class")
        ax.set_ylabel("Actual UHI class")
        ax.set_title(f"Confusion matrix (class accuracy = {accuracy:.1%})")
        fig.colorbar(im, ax=ax)
        fig.tight_layout()
        path = self.cfg.paths.plots_dir / "confusion_matrix.png"
        fig.savefig(path, dpi=150, bbox_inches="tight")
        plt.close(fig)
        log.info("Confusion analysis: class accuracy=%.3f, kappa=%.3f", accuracy, kappa)
        return out

    @staticmethod
    def _cohen_kappa(cm: pd.DataFrame) -> float:
        cm = cm.values.astype(float)
        n = cm.sum()
        if n == 0:
            return float("nan")
        p0 = np.trace(cm) / n
        pe = np.sum(cm.sum(axis=0) * cm.sum(axis=1)) / (n * n)
        return float((p0 - pe) / (1 - pe)) if pe < 1 else float("nan")

    # ------------------------------------------------------------------ #
    def residual_plots(self, y_true: np.ndarray, y_pred: np.ndarray) -> Dict[str, Path]:
        """Residuals vs predicted + residual histogram."""
        resid = np.asarray(y_pred) - np.asarray(y_true)
        paths = {}

        fig, axes = plt.subplots(1, 2, figsize=(13, 5))
        axes[0].scatter(y_pred, resid, s=6, alpha=0.25)
        axes[0].axhline(0, color="red", lw=1)
        axes[0].set_xlabel("Predicted LST (°C)")
        axes[0].set_ylabel("Residual (pred - actual, °C)")
        axes[0].set_title("Residuals vs predicted")
        axes[1].hist(resid, bins=80, color="#1f77b4", alpha=0.85)
        axes[1].axvline(0, color="red", lw=1)
        axes[1].set_xlabel("Residual (°C)")
        axes[1].set_ylabel("Count")
        axes[1].set_title(f"Residual distribution (std = {resid.std():.3f}°C)")
        fig.tight_layout()
        p1 = self.cfg.paths.plots_dir / "residual_plots.png"
        fig.savefig(p1, dpi=150, bbox_inches="tight")
        plt.close(fig)
        paths["residual_plots"] = p1

        fig, ax = plt.subplots(figsize=(7, 7))
        lims = [min(y_true.min(), y_pred.min()), max(y_true.max(), y_pred.max())]
        ax.scatter(y_true, y_pred, s=6, alpha=0.25)
        ax.plot(lims, lims, "r--", lw=1.2)
        ax.set_xlim(lims); ax.set_ylim(lims)
        ax.set_xlabel("Actual LST (°C)")
        ax.set_ylabel("Predicted LST (°C)")
        ax.set_title("Prediction vs Actual")
        ax.grid(alpha=0.3)
        fig.tight_layout()
        p2 = self.cfg.paths.plots_dir / "prediction_vs_actual.png"
        fig.savefig(p2, dpi=150, bbox_inches="tight")
        plt.close(fig)
        paths["prediction_vs_actual"] = p2
        return paths

    # ------------------------------------------------------------------ #
    def spatial_error_map(self, residuals: pd.Series, grid_ids: pd.Series) -> Optional[Path]:
        """Residuals mapped on the grid (uses grid geometry only, no new GIS)."""
        geojson_path = self.cfg.paths.dataset_geojson
        if not geojson_path.exists():
            return None
        import json
        from shapely.geometry import shape
        with open(geojson_path, "r", encoding="utf-8") as fh:
            geojson = json.load(fh)
        res_map = dict(zip(grid_ids.values, residuals.values))
        xs, ys, vals = [], [], []
        for f in geojson["features"]:
            v = res_map.get(f["properties"].get("Grid_ID"))
            if v is None:
                continue
            b = shape(f["geometry"]).bounds
            xs.append((b[0] + b[2]) / 2)
            ys.append((b[1] + b[3]) / 2)
            vals.append(v)
        if not vals:
            return None

        fig, ax = plt.subplots(figsize=(10, 9))
        vmax = max(abs(min(vals)), abs(max(vals)), 0.5)
        sc = ax.scatter(xs, ys, c=vals, cmap="RdBu_r", vmin=-vmax, vmax=vmax,
                        s=1.5, marker="s")
        ax.set_title("Spatial error map - test-set residuals (pred - actual, °C)")
        ax.set_xlabel("UTM 45N easting (m)")
        ax.set_ylabel("UTM 45N northing (m)")
        fig.colorbar(sc, ax=ax, shrink=0.85, label="Residual (°C)")
        fig.tight_layout()
        path = self.cfg.paths.plots_dir / "spatial_error_map.png"
        fig.savefig(path, dpi=150, bbox_inches="tight")
        plt.close(fig)
        log.info("Spatial error map written: %s", path)
        return path

    # ------------------------------------------------------------------ #
    def build_metrics(self, test_metrics: Dict, cv_summary: Dict,
                      leaderboard: pd.DataFrame, extra: Dict) -> Dict:
        """Aggregate everything into metrics.json."""
        # keep only numeric metrics (drop e.g. the "model" name key)
        test_metrics_num = {k: v for k, v in test_metrics.items()
                            if isinstance(v, (int, float)) and not isinstance(v, bool)}
        self.metrics = {
            "dataset": {
                "samples": int(extra.get("n_samples")),
                "features_used": extra.get("n_features"),
                "features_dropped": extra.get("n_dropped"),
            },
            "test_metrics": {k: round(float(v), 5) for k, v in test_metrics_num.items()},
            "cross_validation_5fold": {k: round(float(v), 5) for k, v in cv_summary.items()},
            "leaderboard": leaderboard.drop(columns=["train_time_s"], errors="ignore")
                                     .fillna("nan").to_dict("records"),
            "best_model": extra.get("best_model"),
            "best_hyperparameters": extra.get("best_hyperparameters"),
            "optuna_best_validation_rmse": extra.get("optuna_best_rmse"),
            "explainability": extra.get("explainability"),
            "sensitivity": extra.get("sensitivity"),
            "confusion": extra.get("confusion"),
        }
        with open(self.cfg.paths.metrics_json, "w", encoding="utf-8") as fh:
            json.dump(self.metrics, fh, indent=2, default=str)
        log.info("metrics.json written: %s", self.cfg.paths.metrics_json)
        return self.metrics
