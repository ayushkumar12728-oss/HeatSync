"""
STEPS 3-10 - DEM processing: merge, clip, terrain derivatives, contours, stats
==============================================================================
Reads the tiles in ``data/raw/dem/``, merges them, clips to boundary.geojson,
then derives:

  STEP 5  Elevation.tif
  STEP 6  Slope.tif        (degrees, Horn 1981 / RichDEM)
  STEP 7  Aspect.tif       (0-360 from north, clockwise; flat = -1)
  STEP 8  Hillshade.tif    (0-255, configurable sun azimuth/altitude)
  STEP 9  Contour lines every N metres (GeoJSON)
  STEP 10 dem_stats.json

Terrain math uses Horn's (1981) 3x3 finite differences implemented in numpy;
RichDEM is used instead when ``engine = "richdem"`` and the package imports.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import matplotlib

matplotlib.use("Agg")  # headless-safe

import matplotlib.pyplot as plt
import numpy as np
import geopandas as gpd
import rasterio
import rioxarray
import xarray as xr
from rasterio.merge import merge as merge_tiles
from shapely.geometry import LineString

from config import Config
from utils import (
    PipelineError,
    atomic_write_geotiff,
    load_boundary,
    read_json,
    write_json,
)

logger = logging.getLogger("sentinel.dem.process")

ASPECT_DIRECTIONS = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]


# ---------------------------------------------------------------------------
# STEP 3 - Merge tiles
# ---------------------------------------------------------------------------
def merge_dem_tiles(cfg: Config, tile_paths: Dict[str, Path], out_path: Path) -> Path:
    """Merge all downloaded DEM tiles into a single GeoTIFF (EPSG:4326)."""
    if out_path.exists() and cfg.pipeline.skip_existing and not cfg.pipeline.force:
        logger.info("Merged DEM already exists - skipping")
        return out_path
    paths = list(tile_paths.values())
    if not paths:
        raise PipelineError("No DEM tiles available to merge")

    with rasterio.open(paths[0]) as src:
        nodata = src.nodata
        crs = src.crs
    merged, transform = merge_tiles(paths, nodata=nodata, method="first")
    meta = {
        "driver": "GTiff", "dtype": merged.dtype, "count": 1,
        "height": merged.shape[1], "width": merged.shape[2],
        "crs": crs, "transform": transform, "nodata": nodata,
        "compress": "deflate", "tiled": True, "blockxsize": 256, "blockysize": 256,
    }
    atomic_write_geotiff(out_path, merged[0], meta)
    logger.info("Merged %d tile(s) -> %s", len(paths), out_path)
    return out_path


# ---------------------------------------------------------------------------
# STEP 4 - Clip to boundary
# ---------------------------------------------------------------------------
def clip_dem(cfg: Config, merged_path: Path, out_path: Path,
             boundary: gpd.GeoDataFrame) -> Path:
    """Clip the merged DEM to boundary.geojson (rioxarray)."""
    if out_path.exists() and cfg.pipeline.skip_existing and not cfg.pipeline.force:
        logger.info("Clipped DEM already exists - skipping")
        return out_path
    if not merged_path.exists():
        raise PipelineError(f"Merged DEM missing: {merged_path}")

    da: xr.DataArray = rioxarray.open_rasterio(merged_path, masked=True)
    if da.rio.crs is None:
        da = da.rio.write_crs("EPSG:4326")
    clipped = da.rio.clip(boundary.geometry, boundary.crs, drop=True)
    clipped.rio.to_raster(out_path, compress="deflate", dtype="float32")
    logger.info("Clipped DEM -> %s (%d x %d px)", out_path,
                clipped.sizes["x"], clipped.sizes["y"])
    return out_path


# ---------------------------------------------------------------------------
# Terrain derivatives (Horn 1981, numpy)
# ---------------------------------------------------------------------------
def _fill_nodata_nearest(elev: np.ndarray) -> np.ndarray:
    """Fill NaN with nearest neighbours (4 directional passes + median tail)."""
    z = elev.astype(np.float32)
    if not np.isnan(z).any():
        return z
    for _ in range(2):
        np.copyto(z, np.where(np.isnan(z), np.roll(z, 1, axis=1), z))
        np.copyto(z, np.where(np.isnan(z), np.roll(z, -1, axis=1), z))
        np.copyto(z, np.where(np.isnan(z), np.roll(z, 1, axis=0), z))
        np.copyto(z, np.where(np.isnan(z), np.roll(z, -1, axis=0), z))
    np.copyto(z, np.where(np.isnan(z), np.nanmedian(z), z))
    return z


def _gradients(z: np.ndarray, cell_x: float, cell_y: float) -> Tuple[np.ndarray, np.ndarray]:
    """Horn's (1981) 3x3 weighted finite differences (interior cells only)."""
    dzdx = ((z[:-2, 2:] + 2 * z[1:-1, 2:] + z[2:, 2:])
            - (z[:-2, :-2] + 2 * z[1:-1, :-2] + z[2:, :-2])) / (8 * cell_x)
    dzdy = ((z[2:, :-2] + 2 * z[2:, 1:-1] + z[2:, 2:])
            - (z[:-2, :-2] + 2 * z[:-2, 1:-1] + z[:-2, 2:])) / (8 * cell_y)
    return dzdx, dzdy


def compute_slope_aspect(elev: np.ndarray, cell_x: float, cell_y: float) -> Tuple[np.ndarray, np.ndarray]:
    """Slope (degrees) and aspect (0-360 clockwise from N, flat = -1)."""
    z = _fill_nodata_nearest(elev)
    dzdx, dzdy = _gradients(z, cell_x, cell_y)
    slope = np.degrees(np.arctan(np.hypot(dzdx, dzdy)))
    aspect = (90.0 - np.degrees(np.arctan2(dzdy, -dzdx))) % 360.0
    aspect[slope <= 1e-6] = -1.0  # flat cells

    slope = np.pad(slope, 1, mode="edge")
    aspect = np.pad(aspect, 1, mode="edge")
    slope[np.isnan(elev)] = np.nan
    aspect[np.isnan(elev)] = np.nan
    return slope.astype(np.float32), aspect.astype(np.float32)


def compute_hillshade(elev: np.ndarray, cell_x: float, cell_y: float,
                      azimuth: float = 315.0, altitude: float = 45.0) -> np.ndarray:
    """Hillshade 0-255 (standard ArcGIS/USGS formula)."""
    z = _fill_nodata_nearest(elev)
    dzdx, dzdy = _gradients(z, cell_x, cell_y)
    slope_rad = np.arctan(np.hypot(dzdx, dzdy))
    aspect_rad = np.radians((90.0 - np.degrees(np.arctan2(dzdy, -dzdx))) % 360.0)

    zenith = np.radians(90.0 - altitude)
    az_math = np.radians(360.0 - azimuth + 90.0)
    hs = (np.cos(zenith) * np.cos(slope_rad)
          + np.sin(zenith) * np.sin(slope_rad) * np.cos(az_math - aspect_rad))
    hs = np.clip(hs, 0.0, 1.0) * 255.0

    hs = np.pad(hs, 1, mode="edge")
    hs[np.isnan(elev)] = np.nan
    return hs.astype(np.float32)


def cell_sizes_m(meta: dict) -> Tuple[float, float]:
    """Approximate cell size in metres from a geographic (EPSG:4326) DEM."""
    t = meta["transform"]
    res_x, res_y = abs(t.a), abs(t.e)
    lat = t.f + meta["height"] * t.e / 2.0  # centre latitude
    m_per_deg_y = 111132.0 - 559.0 * np.cos(2 * np.radians(lat))
    m_per_deg_x = 111320.0 * np.cos(np.radians(lat))
    return res_x * m_per_deg_x, res_y * m_per_deg_y


# ---------------------------------------------------------------------------
# RichDEM engine (optional)
# ---------------------------------------------------------------------------
def _try_richdem(elev: np.ndarray, cell_x: float, cell_y: float) -> Optional[Tuple[np.ndarray, np.ndarray]]:
    try:
        import richdem as rd
    except ImportError:
        return None
    logger.info("Using RichDEM engine for slope/aspect/hillshade")
    z = _fill_nodata_nearest(elev)
    rda = rd.rdarray(z, no_data=np.nan)
    rda = rda / rda  # ensure float + nodata propagation
    slope = rd.TerrainAttribute(rda, attrib="slope_degrees")
    aspect = rd.TerrainAttribute(rda, attrib="aspect")
    return np.asarray(slope), np.asarray(aspect)


# ---------------------------------------------------------------------------
# STEP 9 - Contours
# ---------------------------------------------------------------------------
def generate_contours(elev: np.ndarray, meta: dict, interval: float,
                      out_path: Path, skip_existing: bool) -> int:
    """Extract contour lines every ``interval`` metres as a GeoJSON."""
    if out_path.exists() and skip_existing:
        logger.info("Contours already exist - skipping")
        try:
            return len(gpd.read_file(out_path))
        except Exception:
            return int(out_path.stat().st_size > 0)
    valid = elev[~np.isnan(elev)]
    if valid.size == 0:
        raise PipelineError("No valid elevation pixels for contouring")
    lo = float(np.floor(valid.min() / interval) * interval)
    hi = float(np.ceil(valid.max() / interval) * interval)
    levels = np.arange(lo, hi + interval, interval)
    levels = levels[(levels > valid.min()) & (levels < valid.max())]
    if levels.size == 0:
        raise PipelineError("Contour interval larger than elevation range")

    fig, ax = plt.subplots()
    cs = ax.contour(elev, levels=levels)
    segs_by_level = cs.allsegs
    plt.close(fig)

    t = meta["transform"]
    lines: List[LineString] = []
    values: List[float] = []
    for lvl, segs in zip(levels, segs_by_level):
        for seg in segs:
            if len(seg) < 2:
                continue
            pts = [(t.c + col * t.a, t.f + row * t.e) for col, row in seg]
            lines.append(LineString(pts))
            values.append(float(lvl))

    gdf = gpd.GeoDataFrame({"elevation": values}, geometry=lines,
                           crs=meta["crs"])
    out_path.parent.mkdir(parents=True, exist_ok=True)
    gdf.to_file(out_path, driver="GeoJSON")
    logger.info("Contours (every %.0f m) -> %s (%d lines)",
                interval, out_path, len(gdf))
    return len(gdf)


# ---------------------------------------------------------------------------
# STEP 10 - Statistics
# ---------------------------------------------------------------------------
def aspect_distribution(aspect: np.ndarray) -> Dict[str, float]:
    valid = aspect[~np.isnan(aspect)]
    total = valid.size
    if total == 0:
        return {d: 0.0 for d in ASPECT_DIRECTIONS} | {"Flat": 0.0}
    nonflat = valid[valid != -1.0]
    idx = ((nonflat + 22.5) % 360.0 // 45.0).astype(int)
    counts = np.bincount(idx, minlength=8)
    dist = {d: round(float(counts[i] / total * 100.0), 2)
            for i, d in enumerate(ASPECT_DIRECTIONS)}
    dist["Flat"] = round(float((valid == -1.0).sum() / total * 100.0), 2)
    return dist


def compute_stats(elev: np.ndarray, slope: np.ndarray, aspect: np.ndarray,
                  meta: dict, source: dict, contour_count: int, cfg: Config) -> dict:
    valid = ~np.isnan(elev)
    if not valid.any():
        raise PipelineError("No valid elevation pixels inside the boundary")
    elev_v, slope_v = elev[valid], slope[valid]
    cell_x, cell_y = cell_sizes_m(meta)

    return {
        "source": source,
        "crs": str(meta["crs"]),
        "resolution_deg": {
            "x": round(abs(meta["transform"].a), 8),
            "y": round(abs(meta["transform"].e), 8),
        },
        "resolution_m": {
            "x": float(round(cell_x, 2)), "y": float(round(cell_y, 2)),
            "note": "approximate (geographic CRS scaled at scene centre latitude)",
        },
        "elevation": {
            "min": round(float(np.nanmin(elev)), 2),
            "max": round(float(np.nanmax(elev)), 2),
            "mean": round(float(np.nanmean(elev)), 2),
            "median": round(float(np.nanmedian(elev)), 2),
            "std": round(float(np.nanstd(elev)), 2),
            "unit": "metres (EGM2008 geoid heights for Copernicus GLO-30)",
        },
        "slope": {
            "min": round(float(np.nanmin(slope)), 3),
            "max": round(float(np.nanmax(slope)), 3),
            "mean": round(float(np.nanmean(slope)), 3),
            "std": round(float(np.nanstd(slope)), 3),
            "unit": "degrees",
        },
        "aspect_distribution_percent": aspect_distribution(aspect),
        "contours": {"interval_m": cfg.dem.contour_interval_m, "count": contour_count},
        "terrain_engine": cfg.dem.engine,
        "valid_pixels": int(valid.sum()),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# Previews
# ---------------------------------------------------------------------------
def _extent(meta: dict) -> tuple:
    t = meta["transform"]
    return (t.c, t.c + meta["width"] * t.a, t.f + meta["height"] * t.e, t.f)


def preview_relief(elev: np.ndarray, hillshade: np.ndarray, meta: dict,
                   cfg: Config, out: Path) -> None:
    fig, ax = plt.subplots(figsize=(12, 10))
    hs = np.nan_to_num(hillshade, nan=0.0)
    ax.imshow(hs, cmap="gray", extent=_extent(meta))
    ax.set_title("Hillshade Relief", fontweight="bold")
    ax.set_xlabel("Longitude"); ax.set_ylabel("Latitude")
    fig.savefig(out, dpi=cfg.pipeline.preview_dpi, bbox_inches="tight")
    plt.close(fig)
    logger.info("Preview saved -> %s", out)


def preview_contours(elev: np.ndarray, hillshade: np.ndarray, meta: dict,
                     contours_path: Path, cfg: Config, out: Path) -> None:
    gdf = gpd.read_file(contours_path)
    fig, ax = plt.subplots(figsize=(12, 10))
    hs = np.nan_to_num(hillshade, nan=0.0)
    ax.imshow(hs, cmap="gray", extent=_extent(meta))
    if not gdf.empty:
        gdf.plot(ax=ax, color="k", linewidth=0.4)
    ax.set_title("Contours (every %.0f m) over hillshade"
                 % cfg.dem.contour_interval_m, fontweight="bold")
    ax.set_xlabel("Longitude"); ax.set_ylabel("Latitude")
    fig.savefig(out, dpi=cfg.pipeline.preview_dpi, bbox_inches="tight")
    plt.close(fig)
    logger.info("Preview saved -> %s", out)


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------
def process_dem(cfg: Config, boundary: Optional[gpd.GeoDataFrame] = None) -> Tuple[Dict[str, Path], dict]:
    """
    STEPS 3-10: merge tiles, clip, elevation, slope, aspect, hillshade,
    contours and statistics. Returns (outputs, stats).
    """
    boundary = boundary if boundary is not None else load_boundary(cfg.paths.boundary)
    skip_existing = cfg.pipeline.skip_existing and not cfg.pipeline.force
    source = read_json(cfg.paths.raw_dem / "dem_metadata.json")
    tile_paths = {
        name: cfg.paths.raw_dem / f"{name}.tif"
        for name in source.get("tiles", {}).keys()
    }
    if not tile_paths and source.get("single"):
        tile_paths = {"srtm_30m": Path(source["single"])}
    if not tile_paths:
        raise PipelineError("No DEM tiles found - run the download stage first")

    # ---- STEP 3: merge ----
    merged_path = merge_dem_tiles(cfg, tile_paths, cfg.paths.dem / "merged.tif")

    # ---- STEP 4: clip ----
    clipped_path = clip_dem(cfg, merged_path, cfg.paths.dem / "dem_clipped.tif", boundary)

    # ---- read elevation ----
    with rasterio.open(clipped_path) as src:
        elev = src.read(1).astype(np.float32)
        meta = src.meta.copy()
    nodata = meta.get("nodata")
    if nodata is not None:
        elev[elev == nodata] = np.nan
    elev[~np.isfinite(elev)] = np.nan  # NaN / inf -> invalid everywhere
    meta.update(dtype="float32", nodata=np.nan, compress="deflate",
                tiled=True, blockxsize=256, blockysize=256)

    cell_x, cell_y = cell_sizes_m(meta)

    # ---- STEP 5: Elevation.tif ----
    elev_out = cfg.paths.elevation / "Elevation.tif"
    if not (elev_out.exists() and skip_existing):
        atomic_write_geotiff(elev_out, elev, meta)
    outputs: Dict[str, Path] = {"Elevation.tif": elev_out}

    # ---- STEP 6-8: slope, aspect, hillshade ----
    rich = _try_richdem(elev, cell_x, cell_y) if cfg.dem.engine == "richdem" else None
    if rich is not None:
        slope, aspect = rich
        slope = np.asarray(slope, dtype=np.float32)
        aspect = np.asarray(aspect, dtype=np.float32)
        aspect[np.isnan(elev)] = np.nan
        slope[np.isnan(elev)] = np.nan
    else:
        slope, aspect = compute_slope_aspect(elev, cell_x, cell_y)
    hillshade = compute_hillshade(elev, cell_x, cell_y,
                                  cfg.dem.hillshade_azimuth,
                                  cfg.dem.hillshade_altitude)

    slope_out = cfg.paths.slope / "Slope.tif"
    aspect_out = cfg.paths.aspect / "Aspect.tif"
    hs_out = cfg.paths.hillshade / "Hillshade.tif"
    for arr, out in [(slope, slope_out), (aspect, aspect_out), (hillshade, hs_out)]:
        if not (out.exists() and skip_existing):
            atomic_write_geotiff(out, arr, meta)
        outputs[out.name] = out

    # ---- STEP 9: contours ----
    contour_out = cfg.paths.contours / f"contours_{cfg.dem.contour_interval_m:.0f}m.geojson"
    n_contours = generate_contours(
        elev, meta, cfg.dem.contour_interval_m, contour_out,
        skip_existing=skip_existing,
    )
    outputs[contour_out.name] = contour_out

    # ---- previews ----
    preview_relief(elev, hillshade, meta, cfg, cfg.paths.dem / "hillshade_relief.png")
    preview_contours(elev, hillshade, meta, contour_out, cfg,
                     cfg.paths.dem / "contours_preview.png")

    # ---- STEP 10: statistics ----
    stats = compute_stats(elev, slope, aspect, meta, source, n_contours, cfg)
    stats_path = write_json(cfg.paths.stats / "dem_stats.json", stats)
    outputs["dem_stats.json"] = stats_path
    logger.info("Statistics written -> %s", stats_path)

    logger.info("DEM processing complete: %d output files", len(outputs))
    return outputs, stats


if __name__ == "__main__":  # pragma: no cover
    from utils import setup_logging

    cfg = Config.from_env()
    cfg.paths.ensure()
    setup_logging(cfg)
    outputs, stats = process_dem(cfg)
    print(f"\nElevation: min {stats['elevation']['min']} | max "
          f"{stats['elevation']['max']} | mean {stats['elevation']['mean']} m")
    print(f"Mean slope: {stats['slope']['mean']} deg")
    print(f"Contours: {stats['contours']['count']}")
    for name, path in outputs.items():
        print(f"  {name}: {path}")
