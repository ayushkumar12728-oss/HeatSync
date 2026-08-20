"""
Leakage detection & feature selection
======================================
STEP 2 - Automatically detect and remove leakage features:

    * Explicitly known leakage columns (MeanLST, MaxLST, MinLST, ...).
    * Any column with |Pearson correlation| to the target above a threshold
      (default 0.99) -> duplicated target information.
    * Constant (zero-variance) columns carry no information -> dropped.
    * Perfectly duplicated feature columns -> dropped.

A leakage_report.json is written describing every removal decision.
"""

from __future__ import annotations

import json
import logging
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd

log = logging.getLogger("aie.feature_selection")


class FeatureSelector:
    """Detects leakage / constant / duplicate columns and selects features."""

    def __init__(self, cfg, schema: Dict[str, List[str]]):
        self.cfg = cfg
        self.schema = schema
        # data_loader exposes both internal ('id') and report ('id_columns') keys
        self._id_cols = schema.get("id", schema.get("id_columns", []))
        self._geom_cols = schema.get("geometry", schema.get("geometry_columns", []))
        self._leakage_candidates = schema.get("leakage_candidates", [])
        self.leakage_report: Dict = {}
        self.selected_features: List[str] = []

    # ------------------------------------------------------------------ #
    def run(self, df: pd.DataFrame) -> Tuple[pd.DataFrame, List[str]]:
        """Drop leakage/constant/duplicate columns and return (df, features)."""
        target = self.cfg.data.target
        report: Dict = {"target": target, "removed": [], "kept": []}

        # 0) ID and geometry columns are never features (e.g. Grid_ID is a
        #    spatial-order proxy that would leak location into the model).
        id_columns = [c for c in self._id_cols if c in df.columns]
        geom_columns = [c for c in self._geom_cols if c in df.columns]
        report["removed"].extend(
            {"column": c, "reason": "id_column (never a feature)"} for c in id_columns
        )
        report["removed"].extend(
            {"column": c, "reason": "geometry_column (never a feature)"} for c in geom_columns
        )

        # 1) Columns with no variance at all (single value).
        constant_cols = [c for c in df.columns if c != target
                         and c not in {*id_columns, *geom_columns}
                         and df[c].nunique(dropna=True) <= 1]
        report["removed"].extend(
            {"column": c, "reason": "constant_column (zero variance)"} for c in constant_cols
        )

        # 2) Explicit / name-based leakage candidates.
        explicit_leakage = [c for c in self._leakage_candidates if c in df.columns
                            and c not in {*id_columns, *geom_columns}]
        report["removed"].extend(
            {"column": c, "reason": "known_leakage (duplicate target information)"}
            for c in explicit_leakage
        )

        # 3) Automatic: |corr(feature, target)| > threshold -> leakage.
        candidates = [c for c in df.columns
                      if c not in {target, *constant_cols, *explicit_leakage,
                                   *id_columns, *geom_columns}]
        corr = df[candidates].corrwith(df[target], method="pearson").abs()
        auto_leakage = corr[corr > self.cfg.data.leakage_corr_threshold].index.tolist()
        report["removed"].extend(
            {
                "column": c,
                "reason": f"auto_leakage |corr|={corr[c]:.4f} > {self.cfg.data.leakage_corr_threshold}",
                "corr_with_target": round(float(corr[c]), 4),
            }
            for c in auto_leakage
        )

        # 4) Perfectly duplicated feature columns (keep the first occurrence).
        remaining = [c for c in df.columns
                     if c not in {*constant_cols, *explicit_leakage, *auto_leakage,
                                  *id_columns, *geom_columns}]
        dupes: List[str] = []
        if remaining:
            frame = pd.DataFrame(df[remaining].values.T)  # rows = columns
            dup_mask = frame.duplicated(keep="first")
            for c, is_dup in zip(remaining, dup_mask):
                if is_dup:
                    dupes.append(c)
                    report["removed"].append(
                        {"column": c, "reason": "duplicate_of another column"}
                    )

        drop_cols = {*constant_cols, *explicit_leakage, *auto_leakage, *dupes,
                     *id_columns, *geom_columns, target}
        selected = [c for c in df.columns if c not in drop_cols]

        report["kept"] = selected
        report["n_removed"] = len(report["removed"])
        report["n_kept"] = len(selected)
        report["leakage_corr_threshold"] = self.cfg.data.leakage_corr_threshold

        self.leakage_report = report
        self.selected_features = selected

        log.info("Leakage / constant / duplicate detection:")
        log.info("  removed %d columns (%d explicit leakage, %d auto-leakage, "
                 "%d constant, %d duplicates)",
                 len(report["removed"]), len(explicit_leakage), len(auto_leakage),
                 len(constant_cols), len(dupes))
        log.info("  kept %d feature columns", len(selected))

        out = df.drop(columns=list(drop_cols)).copy()
        return out, selected

    # ------------------------------------------------------------------ #
    def save_report(self, path) -> None:
        """Persist leakage_report.json."""
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(self.leakage_report, fh, indent=2, default=str)
        log.info("Leakage report written: %s", path)
