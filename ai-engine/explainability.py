"""
SHAP explainability (STEP 8)
============================
Produces, for the final trained model:

    * Global importance        (mean |SHAP| bar chart + CSV)
    * Local importance         (waterfall plots for representative test rows)
    * Summary plot             (beeswarm)
    * Dependence plots         (top-N features vs SHAP value)
    * Interaction plots        (SHAP interaction values for the top pair)

All figures are saved under outputs/plots/SHAP/. Matplotlib runs headless
(Agg backend) so the pipeline works on servers without a display.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import List, Optional, Tuple

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import shap

log = logging.getLogger("aie.explainability")


class SHAPExplainer:
    """Computes and renders SHAP explanations for the best model."""

    def __init__(self, cfg):
        self.cfg = cfg
        self.explainer = None
        self.shap_values: Optional[np.ndarray] = None
        self.background: Optional[pd.DataFrame] = None

    # ------------------------------------------------------------------ #
    def explain(self, model, X_sample: pd.DataFrame, feature_cols: List[str]) -> np.ndarray:
        """Fit a TreeExplainer and compute SHAP values on the sample."""
        self.background = X_sample
        self.explainer = shap.TreeExplainer(model)
        log.info("Computing SHAP values on %d samples ...", len(X_sample))
        self.shap_values = self.explainer.shap_values(X_sample)
        log.info("SHAP matrix: %s", self.shap_values.shape)
        return self.shap_values

    # ------------------------------------------------------------------ #
    def _save(self, fig, name: str, dpi: int = 150) -> Path:
        out = self.cfg.paths.shap_dir
        out.mkdir(parents=True, exist_ok=True)
        path = out / name
        fig.savefig(path, dpi=dpi, bbox_inches="tight")
        plt.close(fig)
        log.info("Saved plot: %s", path)
        return path

    # ------------------------------------------------------------------ #
    def global_importance(self, feature_cols: List[str]) -> pd.DataFrame:
        """Mean |SHAP| per feature + bar chart."""
        mean_abs = np.abs(self.shap_values).mean(axis=0)
        imp = pd.DataFrame({"feature": feature_cols, "mean_abs_shap": mean_abs})
        imp = imp.sort_values("mean_abs_shap", ascending=False).reset_index(drop=True)
        imp["pct_importance"] = imp["mean_abs_shap"] / imp["mean_abs_shap"].sum() * 100.0
        imp.to_csv(self.cfg.paths.shap_dir / "global_shap_importance.csv", index=False)

        top_n = self.cfg.explainability.n_top_features
        fig, ax = plt.subplots(figsize=(10, 8))
        top = imp.head(top_n)[::-1]
        ax.barh(top["feature"], top["mean_abs_shap"], color="#1f77b4")
        ax.set_xlabel("mean |SHAP value| (impact on predicted LST, °C)")
        ax.set_title("Global feature importance (SHAP)")
        ax.grid(axis="x", alpha=0.3)
        fig.tight_layout()
        self._save(fig, "global_importance.png")
        log.info("Top 10 SHAP features: %s", imp.head(10)["feature"].tolist())
        return imp

    # ------------------------------------------------------------------ #
    def summary_plot(self, feature_cols: List[str]) -> Path:
        """Beeswarm summary plot."""
        fig = plt.figure(figsize=(12, 10))
        shap.summary_plot(self.shap_values, self.background[feature_cols],
                          show=False, max_display=self.cfg.explainability.n_top_features)
        plt.title("SHAP summary (beeswarm)")
        return self._save(fig, "summary_plot.png")

    # ------------------------------------------------------------------ #
    def waterfall_plots(self, y_test: pd.Series, feature_cols: List[str],
                        n_samples: int = 3) -> List[Path]:
        """Local explanations for representative test rows (best/median/worst)."""
        shap_values = self.shap_values
        n = len(shap_values)
        idxs = [int(np.argmin(y_test.values)), n // 2, int(np.argmax(y_test.values))]
        paths = []
        for i in idxs:
            exp = shap.Explanation(
                values=shap_values[i],
                base_values=float(self.explainer.expected_value),
                data=self.background.iloc[i][feature_cols].values,
                feature_names=feature_cols,
            )
            fig = plt.figure(figsize=(12, 7))
            shap.waterfall_plot(exp, max_display=12, show=False)
            plt.title(f"SHAP waterfall - test row {i} (actual LST = {y_test.iloc[i]:.2f}°C)")
            paths.append(self._save(fig, f"waterfall_row_{i}.png"))
        return paths

    # ------------------------------------------------------------------ #
    def dependence_plots(self, feature_cols: List[str],
                         top_features: List[str]) -> List[Path]:
        """Dependence plot for the top-N features."""
        paths = []
        for f in top_features[: self.cfg.explainability.n_dependence]:
            fig = plt.figure(figsize=(9, 6))
            shap.dependence_plot(f, self.shap_values, self.background[feature_cols],
                                 show=False)
            plt.title(f"SHAP dependence - {f}")
            paths.append(self._save(fig, f"dependence_{f}.png"))
        return paths

    # ------------------------------------------------------------------ #
    def interaction_plot(self, feature_cols: List[str],
                         top2: Tuple[str, str], n_samples: int = 300) -> Path:
        """SHAP interaction values heatmap for the top feature pair."""
        X = self.background[feature_cols].iloc[:n_samples]
        inter = self.explainer.shap_interaction_values(X)
        i, j = feature_cols.index(top2[0]), feature_cols.index(top2[1])
        vals = inter[:, i, j]
        fig, ax = plt.subplots(figsize=(8, 6))
        sc = ax.scatter(X.iloc[:, i], X.iloc[:, j], c=vals, cmap="RdBu_r", s=18)
        ax.set_xlabel(top2[0])
        ax.set_ylabel(top2[1])
        ax.set_title(f"SHAP interaction {top2[0]} x {top2[1]}")
        plt.colorbar(sc, ax=ax, label=f"SHAP interaction value")
        fig.tight_layout()
        return self._save(fig, f"interaction_{top2[0]}__x__{top2[1]}.png")

    # ------------------------------------------------------------------ #
    def run_all(self, model, X_sample: pd.DataFrame, y_sample: pd.Series,
                feature_cols: List[str]) -> dict:
        """Convenience runner used by main.py."""
        self.explain(model, X_sample, feature_cols)

        imp = self.global_importance(feature_cols)
        top = imp["feature"].head(6).tolist()
        self.summary_plot(feature_cols)
        self.waterfall_plots(y_sample, feature_cols,
                             self.cfg.explainability.waterfall_samples)
        self.dependence_plots(feature_cols, top)
        if len(top) >= 2:
            self.interaction_plot(feature_cols, (top[0], top[1]),
                                  self.cfg.explainability.local_sample)

        return {
            "n_samples": len(X_sample),
            "expected_value": float(self.explainer.expected_value),
            "top_features": imp.head(15).to_dict("records"),
            "plots_dir": str(self.cfg.paths.shap_dir),
        }
