"""
STEP 3 - Raster features
========================
Samples / aggregates every raster over each grid cell with a fast,
dependency-light zonal-stats engine:

    1. rasterize the grid-cell polygons into each raster's own pixel grid
       (cells are transformed to the raster CRS first), so every pixel knows
       which Grid_ID it belongs to;
    2. mask nodata;
    3. aggregate with numpy ufunc.at accumulators (sum / max / min / counts
       and a per-cell class histogram for the majority class).

Features produced (one value per grid cell):

    MeanNDVI / MaxNDVI / MinNDVI           from Sentinel-2 NDVI
    GreenCover (%)                         binary green-cover mask
    VegetationDensity / VegDensityClass    mean + majority of 1-5 classes
    LandCoverClass + 4 fraction columns    majority + class shares (%)
    MeanLST / MaxLST / MinLST (degC)       Landsat land surface temperature
    MeanElevation (m), MeanSlope (deg)
    Aspect (deg, circular mean)            dominant exposure direction
    MeanAQI, MeanPM25, MeanPM10, MeanNO2,
    MeanSO2, MeanCO, MeanO3                interpolated air-quality rasters

Rasters are independent -> processed in parallel with a process pool.
"""

from __future__ import annotations

import logging
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from rasterio import features as rio_features
from rasterio.enums import Resampling

from config import Config

logger = logging.getLogger("feature_engineering.raster")


# ---------------------------------------------------------------------------
# Zonal aggregation primitives
# ---------------------------------------------------------------------------
def _mask_array(data: np.ndarray, nodata, zeros_valid: bool = False) -> np.ndarray:
    """Boolean mask of valid (non-nodata) pixels."""
    if zeros_valid:
        # green-cover style rasters: 0 is meaningful data ("not green")
        return ~np.isnan(data) if np.issubdtype(data.dtype, np.floating) \
            else np.ones(data.shape, dtype=bool)
    if nodata is None:
        return np.ones(data.shape, dtype=bool)
    if isinstance(nodata, float) and np.isnan(nodata):
        return ~np.isnan(data)
    if np.issubdtype(data.dtype, np.floating):
        return ~np.isnan(data) & (data != nodata)
    return data != nodata


def _rasterize_cells(cells: gpd.GeoDataFrame, shape, transform) -> np.ndarray:
    """Pixel -> Grid_ID map (0 where no cell covers the pixel)."""
    shapes = [(geom, int(gid)) for gid, geom in zip(cells["Grid_ID"], cells.geometry)]
    return rio_features.rasterize(
        shapes, out_shape=shape, transform=transform, fill=0, dtype="int32"
    )


@dataclass
class RasterSpec:
    """One raster + the aggregations to run on it."""

    name: str
    path: Path
    cells_crs: str                      # "utm" or "wgs84" -> which cell frame to use
    stats: List[str] = field(default_factory=list)   # mean|max|min|sum|circular_mean|majority
    # For majority: map pixel value -> column (class histogram columns)
    class_map: Optional[Dict[int, str]] = None
    # Rename resulting columns (defaults to <NAME>_<STAT>)
    column_map: Optional[Dict[str, str]] = None
    # Treat 0 as valid data (green-cover style) instead of nodata
    zeros_valid: bool = False
    # Rasters coarser than this (metres) are resampled to it on read so that
    # every grid cell receives a value (e.g. 1 km AQI surfaces -> 100 m).
    target_res_m: Optional[float] = None


def _read_raster(spec: RasterSpec):
    """Read band 1; resample to the target grid when the raster is coarser."""
    with rasterio.open(spec.path) as ds:
        data = ds.read(1)
        transform = ds.transform
        nodata = ds.nodata
        if spec.target_res_m and abs(transform.a) > spec.target_res_m:
            scale = abs(transform.a) / spec.target_res_m
            out_shape = (int(round(ds.height * scale)),
                         int(round(ds.width * scale)))
            data = ds.read(1, out_shape=out_shape,
                           resampling=Resampling.nearest)
            transform = ds.transform * ds.transform.scale(
                ds.width / out_shape[1], ds.height / out_shape[0])
            logger.debug("%s: resampled %dx%d -> %dx%d (nearest)",
                         spec.name, ds.width, ds.height, *out_shape)
        return data, transform, nodata


def _aggregate_raster(spec: RasterSpec,
                      cells: gpd.GeoDataFrame) -> Dict[str, float]:
    """Run the aggregations for one raster, keyed by Grid_ID."""
    data, transform, nodata = _read_raster(spec)
    mask = _mask_array(data, nodata, zeros_valid=spec.zeros_valid)
    cell_ids = _rasterize_cells(cells, data.shape, transform)

    valid = mask & (cell_ids > 0)
    ids = cell_ids[valid]
    vals = data[valid].astype(np.float64)
    n_cells = int(cells["Grid_ID"].max()) + 1

    results: Dict[str, np.ndarray] = {}
    for stat in spec.stats:
        if stat == "mean":
            sums = np.zeros(n_cells)
            np.add.at(sums, ids, vals)
            counts = np.bincount(ids, minlength=n_cells)
            results["mean"] = np.divide(sums, counts,
                                        out=np.full(n_cells, np.nan),
                                        where=counts > 0)
        elif stat == "sum":
            sums = np.zeros(n_cells)
            np.add.at(sums, ids, vals)
            results["sum"] = sums
        elif stat == "max":
            mx = np.full(n_cells, -np.inf)
            np.maximum.at(mx, ids, vals)
            results["max"] = np.where(np.isfinite(mx), mx, np.nan)
        elif stat == "min":
            mn = np.full(n_cells, np.inf)
            np.minimum.at(mn, ids, vals)
            results["min"] = np.where(np.isfinite(mn), mn, np.nan)
        elif stat == "circular_mean":
            sin_sum = np.zeros(n_cells)
            cos_sum = np.zeros(n_cells)
            rad = np.deg2rad(vals)
            np.add.at(sin_sum, ids, np.sin(rad))
            np.add.at(cos_sum, ids, np.cos(rad))
            counts = np.bincount(ids, minlength=n_cells)
            with np.errstate(invalid="ignore"):
                ang = np.rad2deg(np.arctan2(sin_sum, cos_sum))
            results["circular_mean"] = np.mod(ang, 360.0)
        elif stat == "majority":
            classes = sorted(spec.class_map or {})
            if classes:
                n_classes = max(classes) + 1
            else:
                # no class map -> derive the code space from the data
                n_classes = int(np.nanmax(vals)) + 1 if len(vals) else 1
            acc = np.zeros((n_cells, n_classes), dtype=np.float64)
            vint = vals.astype(np.int64)
            valid_cls = (vint >= 0) & (vint < n_classes)
            np.add.at(acc, (ids[valid_cls], vint[valid_cls]), 1.0)
            total = acc.sum(axis=1)
            with np.errstate(invalid="ignore", divide="ignore"):
                frac = np.divide(acc, total[:, None],
                                 out=np.zeros_like(acc), where=total[:, None] > 0)
            majority = acc.argmax(axis=1).astype(float)
            majority[total == 0] = np.nan
            results["majority"] = majority
            for cls, label in (spec.class_map or {}).items():
                results[f"frac_{label}"] = frac[:, cls] * 100.0

    return results


def _raster_worker(args):
    """Top-level pool worker: (RasterSpec, cells_wkt) -> DataFrame."""
    spec, cells = args
    try:
        results = _aggregate_raster(spec, cells)
    except Exception as exc:  # noqa: BLE001
        logger.error("Raster %s failed: %s", spec.name, exc)
        return spec.name, pd.DataFrame()

    col_map = spec.column_map or {}
    df = pd.DataFrame(index=cells["Grid_ID"])
    for stat, arr in results.items():
        if stat.startswith("frac_"):
            col = stat[len("frac_"):]
            df[col] = arr[cells["Grid_ID"].to_numpy()]
            continue
        base = col_map.get(stat, f"{spec.name.title()}_{stat}")
        df[base] = arr[cells["Grid_ID"].to_numpy()]
    return spec.name, df


# ---------------------------------------------------------------------------
# Raster registry
# ---------------------------------------------------------------------------
def build_raster_specs(cfg: Config) -> List[RasterSpec]:
    """Declare every raster and its aggregations (single source of truth)."""
    p = cfg.paths
    aqi = p.aqi_dir
    specs = [
        RasterSpec("ndvi", p.ndvi, "utm",
                   stats=["mean", "max", "min"],
                   column_map={"mean": "MeanNDVI", "max": "MaxNDVI", "min": "MinNDVI"}),
        RasterSpec("greencover", p.greencover, "utm",
                   stats=["mean"],
                   column_map={"mean": "GreenCover"},
                   zeros_valid=True),
        RasterSpec("vegetation", p.vegetation, "utm",
                   stats=["mean", "majority"],
                   column_map={"mean": "VegetationDensity",
                               "majority": "VegDensityClass"}),
        RasterSpec("landcover", p.landcover, "utm",
                   stats=["majority"],
                   # explicit names (avoid slug ambiguities like Built-up)
                   class_map={1: "LandCover_WaterPct",
                              2: "LandCover_VegetationPct",
                              3: "LandCover_BuiltupPct",
                              4: "LandCover_BareLandPct"},
                   column_map={"majority": "LandCoverClass"}),
        RasterSpec("lst", p.lst, "utm",
                   stats=["mean", "max", "min"],
                   column_map={"mean": "MeanLST", "max": "MaxLST", "min": "MinLST"}),
        RasterSpec("elevation", p.elevation, "wgs84",
                   stats=["mean"],
                   column_map={"mean": "MeanElevation"}),
        RasterSpec("slope", p.slope, "wgs84",
                   stats=["mean"],
                   column_map={"mean": "MeanSlope"}),
        RasterSpec("aspect", p.aspect, "wgs84",
                   stats=["circular_mean"],
                   column_map={"circular_mean": "Aspect"}),
        RasterSpec("aqi", aqi / "AQI.tif", "utm", stats=["mean"],
                   column_map={"mean": "MeanAQI"}),
        RasterSpec("pm25", aqi / "PM25.tif", "utm", stats=["mean"],
                   column_map={"mean": "MeanPM25"}),
        RasterSpec("pm10", aqi / "PM10.tif", "utm", stats=["mean"],
                   column_map={"mean": "MeanPM10"}),
        RasterSpec("no2", aqi / "NO2.tif", "utm", stats=["mean"],
                   column_map={"mean": "MeanNO2"}),
        RasterSpec("so2", aqi / "SO2.tif", "utm", stats=["mean"],
                   column_map={"mean": "MeanSO2"}),
        RasterSpec("co", aqi / "CO.tif", "utm", stats=["mean"],
                   column_map={"mean": "MeanCO"}),
        RasterSpec("o3", aqi / "O3.tif", "utm", stats=["mean"],
                   column_map={"mean": "MeanO3"}),
    ]
    # drop declarations whose files do not exist (graceful degradation)
    missing = [s.name for s in specs if not s.path.exists()]
    specs = [s for s in specs if s.path.exists()]
    if missing:
        logger.warning("Raster files not found, skipped: %s", missing)
    # coarse rasters (e.g. 1 km AQI) are resampled to the grid resolution
    for s in specs:
        s.target_res_m = cfg.grid.cell_size_m
    return specs


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------
def compute_raster_features(cells_utm: gpd.GeoDataFrame,
                            cells_wgs84: gpd.GeoDataFrame,
                            cfg: Config) -> pd.DataFrame:
    """
    Zonal statistics for every raster over every grid cell.

    Returns a DataFrame indexed by Grid_ID with one column per feature.
    """
    specs = build_raster_specs(cfg)
    if not specs:
        raise FileNotFoundError("No raster inputs found - nothing to aggregate")

    frames: List[gpd.GeoDataFrame] = []
    for s in specs:
        cells = cells_utm if s.cells_crs == "utm" else cells_wgs84
        frames.append(cells[["Grid_ID", "geometry"]])

    tasks = list(zip(specs, frames))
    if cfg.n_jobs > 1 and len(tasks) > 1:
        with ProcessPoolExecutor(max_workers=cfg.n_jobs) as ex:
            results = list(ex.map(_raster_worker, tasks))
    else:
        results = [_raster_worker(t) for t in tasks]

    parts = [df for _, df in results if not df.empty]
    if not parts:
        raise RuntimeError("All raster feature computations failed")

    out = pd.concat(parts, axis=1)
    out = out.loc[:, ~out.columns.duplicated()]

    # GreenCover mean is a 0-1 fraction -> express as percent
    if "GreenCover" in out.columns:
        out["GreenCover"] = out["GreenCover"] * 100.0

    out = out.reindex(index=cells_utm["Grid_ID"])
    logger.info("Raster features computed: %d rows x %d columns",
                len(out), out.shape[1])
    return out
