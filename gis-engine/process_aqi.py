"""
STEPS 4-9 - Air quality processing: clean, interpolate, AQI, stats, plots
=========================================================================
Reads the observations in ``data/raw/aqi/``, cleans them, interpolates each
pollutant onto a regular UTM grid (Ordinary Kriging preferred, IDW fallback),
then derives:

  STEP 5  PM25.tif PM10.tif NO2.tif SO2.tif CO.tif O3.tif   (ug/m3)
  STEP 6  AQI.tif  (Indian CPCB sub-index, 0-500)
  STEP 7  Statistics.json
  STEP 8  PNG previews per pollutant + AQI
  STEP 9  aqi.csv (cleaned station observations + station AQI)

Pollutants with too few observations are skipped with a clear warning.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import matplotlib

matplotlib.use("Agg")  # headless-safe

import matplotlib.pyplot as plt
from matplotlib.colors import ListedColormap
from matplotlib.patches import Patch
import numpy as np
import pandas as pd
import geopandas as gpd
import rasterio
import rasterio.features
from scipy.spatial import cKDTree
from tqdm import tqdm

from config import AQI_BREAKPOINTS, AQI_CATEGORIES, Config
from utils import (
    PipelineError,
    atomic_write_geotiff,
    load_boundary,
    read_json,
    utm_epsg_for,
    write_json,
)

logger = logging.getLogger("sentinel.aqi.process")

POLLUTANT_COLS = ["PM2.5", "PM10", "NO2", "SO2", "CO", "O3"]
RASTER_NAMES = {"PM2.5": "PM25", "PM10": "PM10", "NO2": "NO2",
                "SO2": "SO2", "CO": "CO", "O3": "O3"}
AQI_COLORS = ["#00e400", "#ffff00", "#ff7e00", "#ff0000", "#8f3f97", "#7e0023"]


# ---------------------------------------------------------------------------
# STEP 4 - cleaning
# ---------------------------------------------------------------------------
def load_observations(cfg: Config) -> pd.DataFrame:
    path = cfg.paths.raw_aqi / "aqi_observations.csv"
    if not path.exists():
        raise PipelineError(f"Observations missing: {path} - run the download stage first")
    return pd.read_csv(path)


def clean_observations(df: pd.DataFrame, boundary: gpd.GeoDataFrame, cfg: Config) -> pd.DataFrame:
    """Drop invalid coordinates, non-positive concentrations and all-NaN rows."""
    out = df.copy()

    # Validate coordinates
    minx, miny, maxx, maxy = boundary.total_bounds
    out = out[(out["lat"].between(miny - 0.05, maxy + 0.05))
              & (out["lon"].between(minx - 0.05, maxx + 0.05))]
    out = out[out[["lat", "lon"]].notna().all(axis=1)]

    # Concentrations must be positive (0/negative = invalid record)
    for col in POLLUTANT_COLS:
        if col in out.columns:
            out.loc[out[col] <= 0, col] = np.nan

    before = len(df)
    out = out.dropna(subset=POLLUTANT_COLS, how="all")
    dropped = before - len(out)
    if dropped:
        logger.info("Cleaning: dropped %d invalid record(s) (%d -> %d)",
                    dropped, before, len(out))
    logger.info("Valid observations per pollutant: %s",
                {p: int(out[p].notna().sum()) for p in POLLUTANT_COLS if p in out.columns})
    return out.reset_index(drop=True)


# ---------------------------------------------------------------------------
# STEP 5 - spatial interpolation
# ---------------------------------------------------------------------------
def _grid_utm(boundary: gpd.GeoDataFrame, resolution_m: int, epsg: int):
    """Grid (UTM) covering the boundary bbox; returns (xs, ys, transform, shape)."""
    minx, miny, maxx, maxy = boundary.to_crs(f"EPSG:{epsg}").total_bounds
    xs = np.arange(minx, maxx + resolution_m, resolution_m)
    ys_desc = np.arange(maxy, miny - resolution_m, -resolution_m)  # north -> south
    transform = rasterio.transform.from_origin(minx, maxy, resolution_m, resolution_m)
    return xs, ys_desc, transform, (len(ys_desc), len(xs))


def _interpolate_idw(x, y, z, grid_xy, k: int) -> np.ndarray:
    """Inverse-distance-weighted interpolation (p=2) via scipy cKDTree."""
    tree = cKDTree(np.column_stack([x, y]))
    d, idx = tree.query(grid_xy, k=min(k, len(x)))
    d = np.atleast_2d(d).T
    idx = np.atleast_2d(idx).T
    vals = np.asarray(z)[idx]
    with np.errstate(divide="ignore", invalid="ignore"):
        w = np.where(d > 0, 1.0 / (d ** 2), 0.0)
        w_sum = w.sum(axis=1)
        est = np.sum(w * vals, axis=1) / np.where(w_sum > 0, w_sum, 1.0)
    exact = d[:, 0] == 0
    est[exact] = vals[exact, 0]
    return est


def _interpolate_krige(x, y, z, grid_x, grid_y, cfg: Config) -> np.ndarray:
    """Ordinary Kriging (pykrige) -> values on the grid (y ascending)."""
    try:
        from pykrige.ok import OrdinaryKriging
    except ImportError as e:
        raise PipelineError("pykrige not installed") from e
    ok = OrdinaryKriging(x, y, z, variogram_model=cfg.aqi.variogram_model,
                         verbose=False, enable_plotting=False)
    grid_z, _ = ok.execute("grid", grid_x, grid_y)
    return grid_z


def interpolate_pollutant(
    df: pd.DataFrame, pollutant: str, boundary: gpd.GeoDataFrame,
    cfg: Config, epsg: int,
) -> Tuple[Optional[np.ndarray], Optional[str], Optional[dict]]:
    """Interpolate one pollutant; returns (2D array, method, info) or (None,...)."""
    pts = df[["lat", "lon", pollutant]].dropna()
    if len(pts) < cfg.aqi.min_points_idw:
        logger.warning("Pollutant %s has only %d point(s) - skipping",
                       pollutant, len(pts))
        return None, None, None

    gdf = gpd.GeoDataFrame(pts, geometry=gpd.points_from_xy(pts["lon"], pts["lat"]),
                           crs="EPSG:4326").to_crs(f"EPSG:{epsg}")
    x = gdf.geometry.x.values.astype(np.float64)
    y = gdf.geometry.y.values.astype(np.float64)
    z = gdf[pollutant].values.astype(np.float64)

    xs, ys_desc, transform, (h, w) = _grid_utm(boundary, cfg.aqi.grid_resolution_m, epsg)
    grid_x = np.arange(transform.c, transform.c + w * cfg.aqi.grid_resolution_m,
                       cfg.aqi.grid_resolution_m)
    grid_y = np.arange(transform.f - h * cfg.aqi.grid_resolution_m,
                       transform.f + cfg.aqi.grid_resolution_m,
                       cfg.aqi.grid_resolution_m)[::-1]  # ascending (south->north)

    method = cfg.aqi.interp_method
    array = None
    info = {"points": len(pts)}
    if method in ("auto", "pykrige") and len(pts) >= cfg.aqi.min_points_krige:
        try:
            array = _interpolate_krige(x, y, z, grid_x, grid_y, cfg)
            method = "ordinary-kriging"
        except Exception as e:
            logger.warning("Kriging failed for %s (%s) - falling back to IDW", pollutant, e)
            array = None
    if array is None:
        gx, gy = np.meshgrid(grid_x, grid_y)
        array = _interpolate_idw(x, y, z, np.column_stack([gx.ravel(), gy.ravel()]), k=4)
        array = array.reshape(h, w)
        method = "idw"
    else:  # kriging rows are south->north; flip for north->south raster rows
        array = np.flipud(array)

    array = np.clip(array, 0.0, None)  # concentrations cannot be negative
    info.update({"method": method, "grid": {"x": w, "y": h},
                 "resolution_m": cfg.aqi.grid_resolution_m})
    return array, method, info


def mask_outside_boundary(array: np.ndarray, boundary: gpd.GeoDataFrame,
                          transform, epsg: int) -> np.ndarray:
    """NaN everywhere outside the boundary polygon (UTM grid)."""
    geom = boundary.to_crs(f"EPSG:{epsg}").geometry.union_all()
    mask = rasterio.features.geometry_mask(
        [geom], out_shape=array.shape, transform=transform, invert=True
    )
    return np.where(mask, array, np.nan)


# ---------------------------------------------------------------------------
# STEP 6 - AQI
# ---------------------------------------------------------------------------
def aqi_subindex(conc: np.ndarray, bands: list) -> np.ndarray:
    """Indian CPCB sub-index (0-500) for a concentration raster."""
    out = np.full(conc.shape, np.nan)
    for lo, hi, alo, ahi in bands:
        hi = hi if hi is not None else lo * 2.0  # top band: assumed width
        m = (conc >= lo) & (conc <= hi)
        if m.any():
            out[m] = alo + (ahi - alo) * ((conc[m] - lo) / (hi - lo))
    return out


def compute_aqi(raster_stack: Dict[str, np.ndarray], cfg: Config) -> np.ndarray:
    """AQI = max over available pollutant sub-indices (CO in mg/m3)."""
    sub = []
    for pollutant, arr in raster_stack.items():
        conc = arr
        if pollutant == "CO":
            conc = arr / 1000.0  # ug/m3 -> mg/m3 for CPCB breakpoints
        sub.append(aqi_subindex(conc, AQI_BREAKPOINTS[pollutant]))
    stack = np.stack(sub)
    aqi = np.full(stack.shape[1:], np.nan)
    valid = np.any(~np.isnan(stack), axis=0)
    if valid.any():
        aqi[valid] = np.nanmax(stack[:, valid], axis=0)
    return aqi


def aqi_category(aqi: np.ndarray) -> Tuple[np.ndarray, List[str]]:
    """Category code (1..6) per pixel + ordered labels."""
    code = np.full(aqi.shape, 0, dtype=np.uint8)
    for i, (_, start) in enumerate(AQI_CATEGORIES, start=1):
        code[(aqi >= start)] = i
    code[np.isnan(aqi)] = 0
    return code, [c for c, _ in AQI_CATEGORIES]


# ---------------------------------------------------------------------------
# STEP 7 - statistics
# ---------------------------------------------------------------------------
def raster_summary(arr: np.ndarray, pixel_area: float) -> dict:
    valid = arr[~np.isnan(arr)]
    if valid.size == 0:
        return {"mean": None, "max": None, "min": None, "std": None,
                "area_km2": 0.0}
    return {
        "mean": round(float(valid.mean()), 2),
        "max": round(float(valid.max()), 2),
        "min": round(float(valid.min()), 2),
        "std": round(float(valid.std()), 2),
        "area_km2": round(valid.size * pixel_area / 1e6, 3),
    }


# ---------------------------------------------------------------------------
# STEP 8 - plots
# ---------------------------------------------------------------------------
def plot_pollutant(arr: np.ndarray, transform, title: str, cmap: str,
                   out: Path, dpi: int, vmax=None) -> None:
    fig, ax = plt.subplots(figsize=(11, 9))
    im = ax.imshow(arr, cmap=cmap, extent=raster_extent(arr, transform), vmin=0, vmax=vmax)
    ax.set_title(title, fontweight="bold")
    plt.colorbar(im, ax=ax, shrink=0.8, label="µg/m³")
    ax.set_xticks([]); ax.set_yticks([])
    fig.tight_layout()
    fig.savefig(out, dpi=dpi, bbox_inches="tight")
    plt.close(fig)


def plot_aqi(aqi: np.ndarray, transform, out: Path, dpi: int) -> None:
    code, labels = aqi_category(aqi)
    cmap = ListedColormap(["#666666"] + AQI_COLORS)
    fig, ax = plt.subplots(figsize=(11, 9))
    im = ax.imshow(code, cmap=cmap, extent=raster_extent(aqi, transform), vmin=0, vmax=6)
    ax.set_title("Air Quality Index (Indian CPCB)", fontweight="bold")
    ax.legend(handles=[Patch(facecolor=AQI_COLORS[i - 1], label=f"{i}. {lbl}")
                       for i, (lbl, _) in enumerate(AQI_CATEGORIES, start=1)],
              loc="lower right", fontsize=9)
    ax.set_xticks([]); ax.set_yticks([])
    fig.tight_layout()
    fig.savefig(out, dpi=dpi, bbox_inches="tight")
    plt.close(fig)


def raster_extent(arr: np.ndarray, transform) -> tuple:
    return (transform.c, transform.c + arr.shape[1] * transform.a,
            transform.f + arr.shape[0] * transform.e, transform.f)


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------
def process_aqi(cfg: Config, boundary: Optional[gpd.GeoDataFrame] = None) -> Tuple[Dict[str, Path], dict]:
    """STEPS 4-9: clean, interpolate, AQI, stats, plots, exports."""
    boundary = boundary if boundary is not None else load_boundary(cfg.paths.boundary)
    epsg = utm_epsg_for(boundary)
    skip = cfg.pipeline.skip_existing and not cfg.pipeline.force

    # ---- STEP 4: clean ----
    raw = load_observations(cfg)
    obs = clean_observations(raw, boundary, cfg)
    if obs.empty:
        raise PipelineError("No valid observations after cleaning")

    # ---- STEP 5: interpolate each pollutant ----
    cfg.paths.aqi_rasters.mkdir(parents=True, exist_ok=True)
    outputs: Dict[str, Path] = {}
    rasters: Dict[str, np.ndarray] = {}
    methods: Dict[str, str] = {}
    transform = None

    for pollutant in tqdm(POLLUTANT_COLS, desc="Interpolating pollutants", leave=False):
        arr, method, info = interpolate_pollutant(obs, pollutant, boundary, cfg, epsg)
        if arr is None:
            continue
        if transform is None:
            _, _, transform, _ = _grid_utm(boundary, cfg.aqi.grid_resolution_m, epsg)
        arr = mask_outside_boundary(arr, boundary, transform, epsg)

        name = RASTER_NAMES[pollutant]
        out = cfg.paths.aqi_rasters / f"{name}.tif"
        if not (out.exists() and skip):
            meta = {
                "driver": "GTiff", "dtype": "float32", "count": 1,
                "height": arr.shape[0], "width": arr.shape[1],
                "crs": f"EPSG:{epsg}", "transform": transform, "nodata": np.nan,
                "compress": "deflate", "tiled": True,
                "blockxsize": 256, "blockysize": 256,
            }
            atomic_write_geotiff(out, arr, meta)
        outputs[name] = out
        rasters[pollutant] = arr
        methods[pollutant] = method or "skipped"
        logger.info("Interpolated %s -> %s (%s, %d points)",
                    pollutant, out.name, method, info.get("points", 0) if info else 0)

    if not rasters:
        raise PipelineError("No pollutant could be interpolated - check observations")

    # ---- STEP 6: AQI ----
    aqi = compute_aqi(rasters, cfg)
    aqi_out = cfg.paths.aqi_rasters / "AQI.tif"
    if not (aqi_out.exists() and skip):
        meta = {
            "driver": "GTiff", "dtype": "float32", "count": 1,
            "height": aqi.shape[0], "width": aqi.shape[1],
            "crs": f"EPSG:{epsg}", "transform": transform, "nodata": np.nan,
            "compress": "deflate", "tiled": True,
            "blockxsize": 256, "blockysize": 256,
        }
        atomic_write_geotiff(aqi_out, aqi, meta)
    outputs["AQI.tif"] = aqi_out

    # ---- STEP 9a: station AQI -> aqi.csv ----
    station_rows = []
    for _, row in obs.iterrows():
        sub = []
        for p in POLLUTANT_COLS:
            v = row.get(p)
            if pd.isna(v):
                continue
            c = v / 1000.0 if p == "CO" else v
            sub.append(aqi_subindex(np.array([c]), AQI_BREAKPOINTS[p])[0])
        row_out = row.to_dict()
        row_out["AQI"] = float(np.nanmax(sub)) if sub else np.nan
        station_rows.append(row_out)
    aqi_csv = obs.copy()
    aqi_csv["AQI"] = [r["AQI"] for r in station_rows]
    aqi_csv_path = cfg.paths.aqi / "aqi.csv"
    aqi_csv_path.write_text(aqi_csv.to_csv(index=False))
    outputs["aqi.csv"] = aqi_csv_path

    # ---- STEP 7: statistics ----
    pixel_area = cfg.aqi.grid_resolution_m ** 2
    category_code, category_labels = aqi_category(aqi)
    valid_total = int((~np.isnan(aqi)).sum()) or 1
    source = read_json(cfg.paths.raw_aqi / "aqi_metadata.json")
    stats = {
        "source": source,
        "crs": f"EPSG:{epsg}",
        "grid": {"resolution_m": cfg.aqi.grid_resolution_m,
                 "interpolation_methods": methods},
        "pollutants_ug_m3": {p: raster_summary(arr, pixel_area)
                             for p, arr in rasters.items()},
        "aqi": raster_summary(aqi, pixel_area),
        "aqi_category_area_percent": {
            lbl: round(float((category_code == i).sum()) / valid_total * 100.0, 2)
            for i, (lbl, _) in enumerate(AQI_CATEGORIES, start=1)
        },
        "stations": {"count": len(obs),
                     "mean_aqi": round(float(aqi_csv["AQI"].mean()), 2),
                     "max_aqi": round(float(aqi_csv["AQI"].max()), 2)},
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    stats_path = write_json(cfg.paths.aqi_statistics / "Statistics.json", stats)
    outputs["Statistics.json"] = stats_path

    # ---- STEP 8: plots ----
    cfg.paths.aqi_plots.mkdir(parents=True, exist_ok=True)
    cmap_map = {"PM2.5": "YlOrRd", "PM10": "YlOrRd", "NO2": "RdPu",
                "SO2": "PuRd", "CO": "OrRd", "O3": "YlGnBu"}
    for pollutant, arr in tqdm(rasters.items(), desc="AQI plots", leave=False):
        out = cfg.paths.aqi_plots / f"{RASTER_NAMES[pollutant]}.png"
        plot_pollutant(arr, transform, f"{pollutant} concentration (µg/m³)",
                       cmap_map[pollutant], out, cfg.pipeline.preview_dpi)
        outputs[out.name] = out
    aqi_png = cfg.paths.aqi_plots / "AQI.png"
    plot_aqi(aqi, transform, aqi_png, cfg.pipeline.preview_dpi)
    outputs["AQI.png"] = aqi_png

    logger.info("AQI processing complete: %d output files", len(outputs))
    return outputs, stats


if __name__ == "__main__":  # pragma: no cover
    from utils import setup_logging

    cfg = Config.from_env()
    cfg.paths.ensure()
    setup_logging(cfg)
    outputs, stats = process_aqi(cfg)
    print(f"\nAQI: mean {stats['aqi']['mean']} | max {stats['aqi']['max']}")
    print("Categories:", stats["aqi_category_area_percent"])
    for name, path in outputs.items():
        print(f"  {name}: {path}")
