"""
Data loading & column-role identification
==========================================
STEP 1 - Load the training dataset and automatically classify every column:

    * Target column        (Target_LST)
    * ID columns           (Grid_ID, ..._ID)
    * Geometry columns     (geometry / wkt / geom, if present)
    * Categorical columns  (object dtype or low-cardinality int codes)
    * Numeric columns      (everything else)
    * Leakage candidates   (explicit LST duplicates + high |corr| with target)
"""

from __future__ import annotations

import json
import logging
import re
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

log = logging.getLogger("aie.data_loader")


def _looks_like_id(name: str) -> bool:
    """Heuristic: Grid_ID, FID, OBJECTID, ..._id (case-insensitive)."""
    if re.fullmatch(r"(?i)(fid|objectid|index|grid_id)", name):
        return True
    return bool(re.fullmatch(r"(?i).*(_id|\.id)$", name))


def _looks_like_geometry(name: str) -> bool:
    return name.lower() in {"geometry", "geom", "wkt", "shape", "the_geom"}


class DataLoader:
    """Loads the training table, classifies columns and exposes the schema."""

    def __init__(self, cfg):
        self.cfg = cfg
        self.df: Optional[pd.DataFrame] = None
        self.geojson: Optional[dict] = None
        self.schema: Dict[str, List[str]] = {}

    # ------------------------------------------------------------------ #
    def load(self) -> pd.DataFrame:
        """Load the CSV (and GeoJSON for spatial outputs)."""
        csv_path = self.cfg.paths.dataset_csv
        if not csv_path.exists():
            raise FileNotFoundError(
                f"Training dataset not found: {csv_path}. "
                "Run gis-engine/feature_engineering/main.py first."
            )
        log.info("Loading dataset: %s", csv_path)
        self.df = pd.read_csv(csv_path)
        log.info("Loaded %d rows x %d columns", *self.df.shape)

        if self.cfg.paths.dataset_geojson.exists():
            log.info("Loading GeoJSON (spatial grid): %s", self.cfg.paths.dataset_geojson)
            with open(self.cfg.paths.dataset_geojson, "r", encoding="utf-8") as fh:
                self.geojson = json.load(fh)
            log.info("GeoJSON features: %d", len(self.geojson.get("features", [])))
        else:
            log.warning("GeoJSON grid not found - spatial outputs will be skipped.")

        self._classify_columns()
        return self.df

    # ------------------------------------------------------------------ #
    def _classify_columns(self) -> None:
        """Automatically identify target / id / geometry / cat / num columns."""
        df = self.df
        target = self.cfg.data.target
        if target not in df.columns:
            raise ValueError(
                f"Target column '{target}' not found. Available: {list(df.columns[:10])}..."
            )

        id_cols = [c for c in df.columns if _looks_like_id(c) and c != target]
        # A unique, integer-valued column is almost certainly an ID (e.g. Grid_ID).
        # Continuous float columns (distances, densities, indices) are features
        # even when every value happens to be unique.
        for c in df.columns:
            if c in id_cols or c == target:
                continue
            if pd.api.types.is_integer_dtype(df[c]) and df[c].nunique(dropna=True) == len(df):
                id_cols.append(c)

        geometry_cols = [c for c in df.columns if _looks_like_geometry(c)]

        # Categorical: object dtype, booleans, or low-cardinality int codes.
        cat_cols: List[str] = []
        numeric_cols: List[str] = []
        for c in df.columns:
            if c in (target, *id_cols, *geometry_cols):
                continue
            if df[c].dtype == object or df[c].dtype == bool:
                cat_cols.append(c)
            elif pd.api.types.is_numeric_dtype(df[c]):
                nunique = df[c].nunique(dropna=True)
                # Only integer-coded, low-cardinality columns are categorical;
                # continuous floats stay numeric even at low cardinality.
                is_cat = (pd.api.types.is_integer_dtype(df[c]) and
                          nunique <= self.cfg.data.max_categorical_nunique)
                if is_cat:
                    cat_cols.append(c)
                else:
                    numeric_cols.append(c)
            else:
                cat_cols.append(c)

        # Configured categoricals always win (even if high-cardinality).
        for c in self.cfg.data.categorical_columns:
            if c in numeric_cols:
                numeric_cols.remove(c)
                if c not in cat_cols:
                    cat_cols.append(c)

        # Leakage candidates: explicit list + columns whose name mentions the target.
        leakage_candidates = list(self.cfg.data.known_leakage)
        for c in df.columns:
            if c == target:
                continue
            if re.search(r"lst", c, re.IGNORECASE) and c not in leakage_candidates:
                leakage_candidates.append(c)

        self.schema = {
            "target": [target],
            "id": sorted(id_cols),
            "geometry": sorted(geometry_cols),
            "categorical": sorted(set(cat_cols) - set(id_cols) - set(geometry_cols)),
            "numeric": sorted(set(numeric_cols) - set(id_cols) - set(geometry_cols)),
            "leakage_candidates": sorted(set(leakage_candidates) & set(df.columns)),
        }

        log.info("Column classification:")
        for role, cols in self.schema.items():
            log.info("  %-20s (%d): %s", role, len(cols), cols[:20])

    # ------------------------------------------------------------------ #
    def report(self) -> Dict:
        """Machine-readable schema summary (used by main.py)."""
        out = {
            "shape": list(self.df.shape),
            "target": self.schema["target"],
            "id_columns": self.schema["id"],
            "geometry_columns": self.schema["geometry"],
            "categorical_columns": self.schema["categorical"],
            "numeric_columns": self.schema["numeric"],
            "leakage_candidates": self.schema["leakage_candidates"],
        }
        return out
