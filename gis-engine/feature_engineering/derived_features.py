"""
STEP 5 - Derived features
=========================
Builds the seven composite UHI-relevant indices from the merged raw
features.  All indices are scaled to the [0, 1] range where a HIGHER value
means a STRONGER contribution to urban heat (except GreenToBuiltRatio and
CoolingDistanceIndex / VegetationCoolingIndex, which are cooling scores -
higher = cooler).

    ImperviousSurfaceRatio    built-up + bare land share of the cell
    GreenToBuiltRatio         vegetation area / built-up area (epsilon-safe)
    CoolingDistanceIndex      proximity to park/water + green-area share
    RoadExposureIndex         road density + proximity to major roads
    VegetationCoolingIndex    scaled NDVI weighted by green-cover share
    TerrainExposureIndex      normalised mean slope
    HeatVulnerabilityIndex    weighted composite of the above + building
                              density + low NDVI (config weights)
    Target_LST                regression target = cell mean LST (degC)
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from config import Config

logger = logging.getLogger("feature_engineering.derived")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _minmax(s: pd.Series) -> pd.Series:
    """0-1 min-max normalisation (NaN-safe)."""
    lo, hi = s.min(), s.max()
    if pd.isna(lo) or pd.isna(hi) or hi - lo <= 1e-12:
        return pd.Series(0.5, index=s.index)
    return (s - lo) / (hi - lo)


def _proximity_score(dist_m: pd.Series, ref_m: float) -> pd.Series:
    """1 / (1 + d/ref) -> 1 when the feature is at the cell, -> 0 far away."""
    d = dist_m.fillna(np.inf)
    return 1.0 / (1.0 + d / ref_m)


def _clip01(s: pd.Series) -> pd.Series:
    return s.clip(lower=0.0, upper=1.0)


def _safe_min(s1: pd.Series, s2: pd.Series) -> pd.Series:
    both = pd.concat([s1, s2], axis=1)
    return both.min(axis=1).where(both.notna().any(axis=1), np.nan)


# ---------------------------------------------------------------------------
# Feature builders
# ---------------------------------------------------------------------------
def _impervious_surface_ratio(df: pd.DataFrame) -> pd.Series:
    built = df.get("LandCover_BuiltupPct", pd.Series(0.0, index=df.index))
    bare = df.get("LandCover_BareLandPct", pd.Series(0.0, index=df.index))
    return _clip01((built.fillna(0.0) + bare.fillna(0.0)) / 100.0)


def _green_to_built_ratio(df: pd.DataFrame) -> pd.Series:
    veg = df.get("LandCover_VegetationPct", pd.Series(0.0, index=df.index))
    built = df.get("LandCover_BuiltupPct", pd.Series(0.0, index=df.index))
    eps = 1e-6
    return (veg.fillna(0.0) + eps) / (built.fillna(0.0) + eps)


def _cooling_distance_index(df: pd.DataFrame, cfg: Config) -> pd.Series:
    w = cfg.derived.cooling_distance_weights
    prox = _proximity_score(
        _safe_min(df["DistToPark"], df["DistToWater"]),
        cfg.derived.proximity_ref_m,
    )
    green = df.get("GreenSpacePct", pd.Series(0.0, index=df.index)).fillna(0.0) / 100.0
    return _clip01(w["proximity"] * prox + w["green_area"] * green)


def _road_exposure_index(df: pd.DataFrame, cfg: Config) -> pd.Series:
    w = cfg.derived.road_exposure_weights
    density = _minmax(df["RoadDensity"].fillna(0.0))
    prox = _proximity_score(df["DistToMajorRoad"], cfg.derived.proximity_ref_m)
    # proximity is a cooling score -> invert it for *exposure*
    return _clip01(w["density"] * density + w["proximity"] * (1.0 - prox))


def _vegetation_cooling_index(df: pd.DataFrame, cfg: Config) -> pd.Series:
    ndvi = df["MeanNDVI"]
    lo = np.nanpercentile(ndvi, cfg.derived.ndvi_pct_lo)
    hi = np.nanpercentile(ndvi, cfg.derived.ndvi_pct_hi)
    scaled = (ndvi - lo) / (hi - lo) if hi - lo > 1e-9 else ndvi * 0.0
    green = df.get("GreenCover", pd.Series(0.0, index=df.index)).fillna(0.0) / 100.0
    return _clip01(scaled.clip(0, 1) * green)


def _terrain_exposure_index(df: pd.DataFrame) -> pd.Series:
    return _clip01(_minmax(df["MeanSlope"].fillna(0.0)))


def _heat_vulnerability_index(df: pd.DataFrame, cfg: Config,
                              impervious: pd.Series,
                              road_exposure: pd.Series) -> pd.Series:
    w = cfg.derived.hvi_weights
    low_green = 1.0 - df["GreenSpacePct"].fillna(0.0) / 100.0
    building = _minmax(df["BuildingDensity"].fillna(0.0))
    ndvi = df["MeanNDVI"]
    lo = np.nanpercentile(ndvi, cfg.derived.ndvi_pct_lo)
    hi = np.nanpercentile(ndvi, cfg.derived.ndvi_pct_hi)
    low_ndvi = 1.0 - (ndvi - lo) / (hi - lo) if hi - lo > 1e-9 else 0.5
    low_ndvi = low_ndvi.clip(0, 1)
    hvi = (w["impervious"] * impervious
           + w["low_green"] * low_green
           + w["building_density"] * building
           + w["road_exposure"] * road_exposure
           + w["low_ndvi"] * low_ndvi)
    return _clip01(hvi)


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------
def compute_derived_features(df: pd.DataFrame, cfg: Config) -> pd.DataFrame:
    """
    Add the STEP-5 derived indices (and the Target_LST column) to ``df``.

    ``df`` must already contain the merged vector + raster + weather features
    (indexed by Grid_ID).
    """
    out = df.copy()

    impervious = _impervious_surface_ratio(out)
    out["ImperviousSurfaceRatio"] = impervious
    out["GreenToBuiltRatio"] = _green_to_built_ratio(out)
    out["CoolingDistanceIndex"] = _cooling_distance_index(out, cfg)
    out["RoadExposureIndex"] = _road_exposure_index(out, cfg)
    out["VegetationCoolingIndex"] = _vegetation_cooling_index(out, cfg)
    out["TerrainExposureIndex"] = _terrain_exposure_index(out)
    out["HeatVulnerabilityIndex"] = _heat_vulnerability_index(
        out, cfg, impervious, out["RoadExposureIndex"],
    )

    # Regression target: cell mean land-surface temperature (degC).
    out["Target_LST"] = out["MeanLST"]

    logger.info("Derived features computed: %d new columns",
                len(set(out.columns) - set(df.columns)))
    return out
