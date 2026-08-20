"""
STEP 6 - Merge & cleaning
=========================
Orchestrates the full pipeline:

    1. load boundary + build the 100 m grid          (grid_generator)
    2. vector features per cell                       (vector_features)
    3. raster zonal statistics per cell               (raster_features)
    4. weather features joined by acquisition date    (weather_features)
    5. derived UHI indices + Target_LST               (derived_features)
    6. cleaning: duplicate removal, missing-value
       handling, CRS validation, geometry repair      (this module)

Outputs the final feature table indexed by Grid_ID.  The raw (un-normalised)
table is what gets written to ``training_dataset.csv``; a z-score normalised
copy is written to ``training_dataset_normalized.csv`` (see quality_checks).
"""

from __future__ import annotations

import logging
from typing import Dict, Optional, Tuple

import geopandas as gpd
import numpy as np
import pandas as pd

from config import Config
from derived_features import compute_derived_features
from grid_generator import generate_grid, load_boundary
from raster_features import compute_raster_features
from vector_features import compute_vector_features
from weather_features import load_weather_features

logger = logging.getLogger("feature_engineering.merge")

# Columns that are identifiers / coordinates, never feature statistics.
ID_COLUMNS = ["Grid_ID", "Latitude", "Longitude", "Area_m2"]
# Categorical columns excluded from numeric cleaning / normalisation.
CATEGORICAL_COLUMNS = ["Season", "LandCoverClass", "VegDensityClass", "Month"]


def build_merged_features(cfg: Config,
                          acquisition_date: Optional[str] = None,
                          grid_size_m: Optional[float] = None,
                          ) -> Tuple[gpd.GeoDataFrame, Dict]:
    """
    Run steps 1-6 and return (cleaned GeoDataFrame, cleaning metadata).

    The returned GeoDataFrame is in EPSG:32645 and carries every feature
    column plus ``Target_LST`` (regression target).
    """
    cfg.paths.ensure()

    # --- STEP 1: grid -----------------------------------------------------
    boundary = load_boundary(cfg)
    cells_utm = generate_grid(boundary, cfg, grid_size_m)
    cells_wgs84 = cells_utm.to_crs(epsg=cfg.grid.wgs84_epsg)

    # --- STEP 2: vector features ------------------------------------------
    vector_df = compute_vector_features(cells_utm, cfg)

    # --- STEP 3: raster features ------------------------------------------
    raster_df = compute_raster_features(cells_utm, cells_wgs84, cfg)

    # --- STEP 4: weather features (broadcast, joined by acquisition date) -
    weather_df = load_weather_features(cfg, acquisition_date)

    # --- STEP 5: derived features -----------------------------------------
    merged = vector_df.join(raster_df, how="outer")
    # overlapping OSM green polygons can double-count area -> clip to [0,100]
    if "GreenSpacePct" in merged.columns:
        merged["GreenSpacePct"] = merged["GreenSpacePct"].clip(0.0, 100.0)
    # broadcast the (single) weather row to every cell
    for col in weather_df.columns:
        merged[col] = weather_df.iloc[0][col]
    merged = compute_derived_features(merged, cfg)

    # --- attach identifiers + geometry ------------------------------------
    cells = cells_utm[["Grid_ID", "geometry"]].copy()
    cells["Area_m2"] = cells_utm["Area"].values
    final = cells.join(merged, on="Grid_ID", how="left")

    # --- STEP 6: cleaning ---------------------------------------------------
    cleaning = clean_dataset(final, cfg)
    return cleaning["data"], cleaning


# ---------------------------------------------------------------------------
# STEP 6 - cleaning
# ---------------------------------------------------------------------------
def clean_dataset(gdf: gpd.GeoDataFrame, cfg: Config) -> Dict:
    """
    - drop exact duplicate rows
    - handle missing values (report + median fill; drop hopeless columns)
    - validate CRS
    - check / repair geometry

    Returns a dict with the cleaned data + cleaning metadata.
    """
    df = gdf.copy()
    report: Dict = {}

    # 1) geometry / CRS -----------------------------------------------------
    report["crs"] = str(df.crs) if df.crs is not None else None
    report["expected_crs"] = f"EPSG:{cfg.grid.target_epsg}"
    crs_ok = df.crs is not None and df.crs.to_epsg() == cfg.grid.target_epsg
    report["crs_valid"] = bool(crs_ok)
    if not crs_ok:
        logger.warning("CRS mismatch - reprojecting to EPSG:%d",
                       cfg.grid.target_epsg)
        df = df.to_crs(epsg=cfg.grid.target_epsg)

    n_before = len(df)
    report["rows_before_cleaning"] = int(n_before)

    # 2) geometry validity ---------------------------------------------------
    df["geometry"] = df.geometry.buffer(0)
    invalid = ~df.geometry.is_valid
    report["invalid_geometries_fixed"] = int(invalid.sum())
    df = df[df.geometry.notna() & ~df.geometry.is_empty].copy()
    report["rows_dropped_empty_geometry"] = int(n_before - len(df))
    n_after_geom = len(df)

    # 3) duplicate rows ------------------------------------------------------
    feature_cols = [c for c in df.columns
                    if c not in ID_COLUMNS and c != "geometry"]
    dup_mask = df[feature_cols].duplicated(keep="first")
    n_dup = int(dup_mask.sum())
    df = df[~dup_mask].copy()
    report["duplicate_rows_removed"] = n_dup
    report["rows_after_dedup"] = int(len(df))

    # 4) missing values ------------------------------------------------------
    missing = df[feature_cols].isna().sum()
    missing_pct = missing / max(len(df), 1) * 100.0
    missing_table = pd.DataFrame({
        "column": missing.index,
        "missing_count": missing.values,
        "missing_pct": np.round(missing_pct.values, 2),
    })
    report["missing_before_fill"] = {
        str(row.column): {"count": int(row.missing_count),
                          "pct": float(row.missing_pct)}
        for row in missing_table.itertuples()
        if row.missing_count > 0
    }
    # drop columns that are essentially empty
    drop_cols = missing_table.loc[
        missing_table["missing_pct"] > cfg.quality.max_missing_pct, "column"
    ].tolist()
    if drop_cols:
        logger.warning("Dropping %d columns missing >%.0f%%: %s",
                       len(drop_cols), cfg.quality.max_missing_pct, drop_cols)
        df = df.drop(columns=drop_cols)
    report["columns_dropped_excessive_missing"] = drop_cols

    # fill the rest
    numeric_cols = [c for c in df.columns
                    if c not in ID_COLUMNS + CATEGORICAL_COLUMNS
                    and c != "geometry"
                    and pd.api.types.is_numeric_dtype(df[c])]
    for col in numeric_cols:
        if df[col].isna().any():
            fill_val = (df[col].median() if cfg.quality.fill_method == "median"
                        else df[col].mean())
            df[col] = df[col].fillna(fill_val)
    for col in CATEGORICAL_COLUMNS:
        if col in df.columns and df[col].isna().any():
            df[col] = df[col].fillna(df[col].mode().iloc[0]
                                     if not df[col].mode().empty else "NA")

    report["missing_value_fill_method"] = cfg.quality.fill_method
    report["rows_final"] = int(len(df))
    report["columns_final"] = int(len(df.columns))

    df = df.reset_index(drop=True)
    logger.info("Cleaning complete: %d rows, %d columns "
                "(duplicates removed: %d, columns dropped: %d)",
                len(df), len(df.columns), n_dup, len(drop_cols))
    return {"data": df, "report": report}


# ---------------------------------------------------------------------------
# Normalisation (used by quality_checks for the normalised CSV)
# ---------------------------------------------------------------------------
def normalize_numeric(df: pd.DataFrame) -> pd.DataFrame:
    """Z-score every continuous numeric column (identifiers / categoricals kept)."""
    out = df.copy()
    numeric_cols = [c for c in out.columns
                    if c not in ID_COLUMNS + CATEGORICAL_COLUMNS
                    and pd.api.types.is_numeric_dtype(out[c])]
    for col in numeric_cols:
        s = out[col]
        std = s.std(ddof=0)
        out[col] = (s - s.mean()) / std if std > 0 else s * 0.0
    return out
