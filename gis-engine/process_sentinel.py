"""
STEPS 4-10 - Sentinel-2 processing: clip, NDVI, products, previews, statistics
==============================================================================
Reads the raw bands in ``data/raw/sentinel2/``, clips them to boundary.geojson,
then derives:

  STEP 5  NDVI raster + PNG + ndvi_statistics.json
  STEP 6  Green Cover raster (binary, configurable NDVI threshold)
  STEP 7  Vegetation Density raster (5 classes: Very Low..Very High)
  STEP 8  Land Cover raster (Water / Vegetation / Built-up / Bare Land)
  STEP 9  matplotlib preview PNGs
  STEP 10 aggregate stats.json

Every product is written atomically and skipped when it already exists
(unless ``--force`` is given).
"""

from __future__ import annotations

import json
import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import matplotlib

matplotlib.use("Agg")  # headless-safe

import matplotlib.pyplot as plt
from matplotlib.colors import ListedColormap
from matplotlib.patches import Patch
import numpy as np
import geopandas as gpd
import rasterio
import rasterio.mask
from rasterio.transform import Affine
from tqdm import tqdm

from config import Config
from utils import (
    PipelineError,
    atomic_write_geotiff,
    geotransform_extent,
    load_boundary,
    read_band,
    read_json,
    utm_epsg_for,
    write_json,
)

logger = logging.getLogger("sentinel.process")


# ---------------------------------------------------------------------------
# STEP 4 - Clip raw bands to the boundary polygon
# ---------------------------------------------------------------------------
def _read_scale_offset(cfg: Config) -> Tuple[float, float]:
    meta = read_json(cfg.paths.raw_sentinel / "metadata.json")
    return float(meta.get("scale", cfg.sentinel.scale)), float(
        meta.get("offset", cfg.sentinel.offset)
    )


def clip_band(
    raw_path: Path, out_path: Path, geom, epsg: int,
    scale: float, offset: float, cfg: Config,
) -> None:
    """Clip one raw uint16 band to the boundary and save float32 reflectance."""
    with rasterio.open(raw_path) as src:
        if src.crs is None or src.crs.to_epsg() != epsg:
            raise PipelineError(
                f"{raw_path.name} is in unexpected CRS {src.crs} (expected EPSG:{epsg})"
            )
        out_img, out_transform = rasterio.mask.mask(
            src, [geom], crop=True, filled=True, nodata=0
        )
        meta = src.meta.copy()
        meta.update(
            driver="GTiff", dtype="float32", count=1,
            height=out_img.shape[1], width=out_img.shape[2],
            transform=out_transform, crs=src.crs,
            nodata=np.nan, compress="deflate",
            tiled=True, blockxsize=256, blockysize=256,
        )

    data = out_img[0].astype(np.float32) * scale + offset
    data[data == (0.0 * scale + offset)] = np.nan  # S2 nodata is 0 (uint16)

    atomic_write_geotiff(out_path, data, meta)
    logger.info("Clipped %s -> %s (%d x %d px)", raw_path.name, out_path,
                meta["width"], meta["height"])


def ensure_clipped_bands(cfg: Config, boundary: gpd.GeoDataFrame) -> Dict[str, Path]:
    """Clip every raw band to boundary.geojson (STEP 4)."""
    epsg = cfg.sentinel.utm_epsg or utm_epsg_for(boundary)
    boundary_utm = boundary.to_crs(f"EPSG:{epsg}")
    geom = boundary_utm.geometry.union_all()
    scale, offset = _read_scale_offset(cfg)

    clipped: Dict[str, Path] = {}
    for band in cfg.sentinel.bands:
        raw = cfg.paths.raw_sentinel / f"{band}.tif"
        out = cfg.paths.clipped / f"{band}_clipped.tif"
        if out.exists() and cfg.pipeline.skip_existing and not cfg.pipeline.force:
            clipped[band] = out
            continue
        if not raw.exists():
            raise PipelineError(
                f"Raw band missing: {raw}. Run the download stage first."
            )
        clip_band(raw, out, geom, epsg, scale, offset, cfg)
        clipped[band] = out
    return clipped


def read_clipped_bands(cfg: Config, clipped: Dict[str, Path]) -> Tuple[Dict[str, np.ndarray], dict]:
    """Read clipped bands as float32 arrays; return (bands, metadata of first)."""
    bands: Dict[str, np.ndarray] = {}
    meta: Optional[dict] = None
    for name, path in clipped.items():
        data, m = read_band(path)
        bands[name] = data
        if meta is None:
            meta = m
    if meta is None:
        raise PipelineError("No clipped bands available to process")
    return bands, meta


# ---------------------------------------------------------------------------
# STEP 5 - NDVI
# ---------------------------------------------------------------------------
def compute_ndvi(nir: np.ndarray, red: np.ndarray) -> np.ndarray:
    """NDVI = (NIR - Red) / (NIR + Red), clipped to [-1, 1], NaN preserved."""
    nir = nir.astype(np.float32)
    red = red.astype(np.float32)
    denom = nir + red
    with np.errstate(divide="ignore", invalid="ignore"):
        ndvi = (nir - red) / denom
    ndvi = np.where(denom > 0, ndvi, np.nan)  # NaN denominator stays NaN
    return np.clip(ndvi, -1.0, 1.0)


# ---------------------------------------------------------------------------
# STEP 6 - Green Cover
# ---------------------------------------------------------------------------
def compute_green_cover(ndvi: np.ndarray, threshold: float) -> np.ndarray:
    """Binary vegetation mask: 1 where NDVI > threshold, else 0 (uint8)."""
    return (ndvi > threshold).astype(np.uint8)


# ---------------------------------------------------------------------------
# STEP 7 - Vegetation Density (5 classes)
# ---------------------------------------------------------------------------
def compute_vegetation_density(
    ndvi: np.ndarray, breaks: List[float], n_classes: int
) -> np.ndarray:
    """
    Classify NDVI into n_classes density levels (uint8, 1..n_classes).

    Classes are defined by the breakpoints, e.g. breaks=[0.1, 0.2, 0.4, 0.6]
    yields Very Low < 0.1 <= Low < 0.2 <= Moderate < 0.4 <= High < 0.6 <= Very High.
    """
    idx = np.searchsorted(np.asarray(breaks, dtype=np.float32), ndvi, side="right")
    cls = (idx + 1).astype(np.uint8)
    cls = np.clip(cls, 1, n_classes)
    cls[np.isnan(ndvi)] = 0  # nodata
    return cls


# ---------------------------------------------------------------------------
# STEP 8 - Land Cover
# ---------------------------------------------------------------------------
def compute_landcover(ndvi: np.ndarray, cfg: Config) -> np.ndarray:
    """
    Rule-based land cover (uint8): 1 Water, 2 Vegetation, 3 Built-up, 4 Bare Land.

    Only 4 bands are available (no SWIR), so classification is NDVI-driven:
      Water      : NDVI <  water_ndvi
      Built-up   : water_ndvi <= NDVI < builtup_ndvi
      Bare Land  : builtup_ndvi <= NDVI < bare_ndvi
      Vegetation : NDVI >= bare_ndvi
    """
    t = cfg.thresholds
    lc = np.full(ndvi.shape, 4, dtype=np.uint8)                      # Bare Land
    lc = np.where(ndvi < t.landcover_water_ndvi, 1, lc)              # Water
    lc = np.where(
        (ndvi >= t.landcover_water_ndvi) & (ndvi < t.landcover_builtup_ndvi),
        3, lc,
    )                                                                 # Built-up
    lc = np.where(ndvi >= t.landcover_bare_ndvi, 2, lc)              # Vegetation
    lc[np.isnan(ndvi)] = 0                                           # nodata
    return lc


# ---------------------------------------------------------------------------
# STEP 9 - Previews
# ---------------------------------------------------------------------------
def _extent(meta: dict) -> tuple:
    left, right, bottom, top = geotransform_extent(meta)
    return (left, right, bottom, top)


def _finish(fig, out: Path, dpi: int) -> None:
    fig.savefig(out, dpi=dpi, bbox_inches="tight")
    plt.close(fig)
    logger.info("Preview saved -> %s", out)


def preview_rgb(bands: Dict[str, np.ndarray], meta: dict, cfg: Config, out: Path) -> None:
    rgb = np.stack([bands["B04"], bands["B03"], bands["B02"]])  # R, G, B
    rgb = np.nan_to_num(rgb, nan=0.0)
    stretched = []
    for channel in rgb:
        valid = channel[channel > 0]
        lo, hi = (np.percentile(valid, (2, 98)) if valid.size else (0.0, 1.0))
        s = (channel - lo) / (hi - lo) if hi > lo else channel
        stretched.append(np.clip(s, 0, 1))
    rgb = np.stack(stretched)

    fig, ax = plt.subplots(figsize=(12, 10))
    ax.imshow(np.transpose(rgb, (1, 2, 0)), extent=_extent(meta))
    ax.set_title("True Colour Composite (B04 B03 B02)", fontweight="bold")
    ax.set_xlabel("Easting (m)"); ax.set_ylabel("Northing (m)")
    _finish(fig, out, cfg.pipeline.preview_dpi)


def preview_ndvi(ndvi: np.ndarray, meta: dict, cfg: Config, out: Path) -> None:
    fig, ax = plt.subplots(figsize=(12, 10))
    im = ax.imshow(
        ndvi, cmap="RdYlGn", extent=_extent(meta),
        vmin=cfg.pipeline.ndvi_vmin, vmax=cfg.pipeline.ndvi_vmax,
    )
    ax.set_title("NDVI (Normalized Difference Vegetation Index)", fontweight="bold")
    ax.set_xlabel("Easting (m)"); ax.set_ylabel("Northing (m)")
    plt.colorbar(im, ax=ax, label="NDVI", shrink=0.8)
    _finish(fig, out, cfg.pipeline.preview_dpi)


def preview_green_cover(gc: np.ndarray, meta: dict, cfg: Config, out: Path) -> None:
    cmap = ListedColormap(["#d9d9d9", "#1a9850"])
    fig, ax = plt.subplots(figsize=(12, 10))
    im = ax.imshow(gc, cmap=cmap, extent=_extent(meta), vmin=0, vmax=1)
    ax.set_title(f"Green Cover (NDVI > {cfg.thresholds.green_cover_ndvi})", fontweight="bold")
    ax.set_xlabel("Easting (m)"); ax.set_ylabel("Northing (m)")
    ax.legend(handles=[
        Patch(facecolor="#1a9850", label="Vegetation"),
        Patch(facecolor="#d9d9d9", label="Non-vegetation"),
    ], loc="lower right")
    _finish(fig, out, cfg.pipeline.preview_dpi)


def preview_density(vd: np.ndarray, meta: dict, cfg: Config, out: Path) -> None:
    n = len(cfg.thresholds.veg_density_labels)
    colors = ["#d9f0a3", "#a6d96a", "#66bd63", "#1a9850", "#006837"][:n]
    cmap = ListedColormap(colors)
    fig, ax = plt.subplots(figsize=(12, 10))
    im = ax.imshow(vd, cmap=cmap, extent=_extent(meta), vmin=1, vmax=n)
    ax.set_title("Vegetation Density", fontweight="bold")
    ax.set_xlabel("Easting (m)"); ax.set_ylabel("Northing (m)")
    ax.legend(
        handles=[Patch(facecolor=c, label=lbl)
                 for c, lbl in zip(colors, cfg.thresholds.veg_density_labels)],
        loc="lower right",
    )
    _finish(fig, out, cfg.pipeline.preview_dpi)


def preview_landcover(lc: np.ndarray, meta: dict, cfg: Config, out: Path) -> None:
    colors = ["#2c7bb6", "#1a9850", "#d7191c", "#fdae61"]  # Water, Veg, Built, Bare
    cmap = ListedColormap(colors)
    fig, ax = plt.subplots(figsize=(12, 10))
    im = ax.imshow(lc, cmap=cmap, extent=_extent(meta), vmin=1, vmax=4)
    ax.set_title("Land Cover Classification", fontweight="bold")
    ax.set_xlabel("Easting (m)"); ax.set_ylabel("Northing (m)")
    ax.legend(
        handles=[Patch(facecolor=c, label=lbl)
                 for c, lbl in zip(colors, cfg.thresholds.landcover_labels)],
        loc="lower right",
    )
    _finish(fig, out, cfg.pipeline.preview_dpi)


def preview_overview(arrays: Dict[str, np.ndarray], meta: dict, cfg: Config, out: Path) -> None:
    fig, axes = plt.subplots(2, 2, figsize=(16, 13))
    (ax1, ax2), (ax3, ax4) = axes
    im1 = ax1.imshow(arrays["ndvi"], cmap="RdYlGn", vmin=-0.5, vmax=1.0)
    ax1.set_title("NDVI"); plt.colorbar(im1, ax=ax1, shrink=0.8)
    im2 = ax2.imshow(arrays["gc"], cmap=ListedColormap(["#d9d9d9", "#1a9850"]), vmin=0, vmax=1)
    ax2.set_title("Green Cover")
    im3 = ax3.imshow(arrays["vd"], cmap=ListedColormap(["#d9f0a3", "#a6d96a", "#66bd63", "#1a9850", "#006837"]), vmin=1, vmax=5)
    ax3.set_title("Vegetation Density")
    im4 = ax4.imshow(arrays["lc"], cmap=ListedColormap(["#2c7bb6", "#1a9850", "#d7191c", "#fdae61"]), vmin=1, vmax=4)
    ax4.set_title("Land Cover")
    for a in (ax1, ax2, ax3, ax4):
        a.set_xticks([]); a.set_yticks([])
    fig.suptitle("Sentinel-2 Derived Products - Bhubaneswar", fontweight="bold", fontsize=15)
    fig.tight_layout()
    _finish(fig, out, cfg.pipeline.preview_dpi)


# ---------------------------------------------------------------------------
# STEP 10 - Statistics
# ---------------------------------------------------------------------------
def _pixel_area(meta: dict) -> float:
    t: Affine = meta["transform"]
    return abs(t.a * t.e)  # m^2 per pixel (UTM)


def _class_summary(mask: np.ndarray, pixel_area: float) -> dict:
    pixels = int(mask.sum())
    return {
        "pixels": pixels,
        "area_ha": round(pixels * pixel_area / 1e4, 2),
        "area_km2": round(pixels * pixel_area / 1e6, 4),
    }


def compute_stats(
    ndvi: np.ndarray, gc: np.ndarray, vd: np.ndarray, lc: np.ndarray,
    meta: dict, scene: dict, cfg: Config,
) -> dict:
    valid = ~np.isnan(ndvi)
    total = int(valid.sum())
    pixel_area = _pixel_area(meta)
    t = cfg.thresholds

    if total == 0:
        raise PipelineError("No valid pixels inside the boundary - nothing to summarise")

    stats = {
        "scene": scene,
        "crs": str(meta["crs"]),
        "resolution_m": {
            "x": round(abs(meta["transform"].a), 4),
            "y": round(abs(meta["transform"].e), 4),
        },
        "pixel_area_m2": round(pixel_area, 2),
        "ndvi": {
            "mean": round(float(np.nanmean(ndvi)), 4),
            "median": round(float(np.nanmedian(ndvi)), 4),
            "max": round(float(np.nanmax(ndvi)), 4),
            "min": round(float(np.nanmin(ndvi)), 4),
            "std": round(float(np.nanstd(ndvi)), 4),
        },
        "green_cover": {
            "threshold": t.green_cover_ndvi,
            "pixels": int(gc.sum()),
            "percent": round(float(gc.sum() / total * 100.0), 2),
            **_class_summary(gc.astype(bool), pixel_area),
        },
        "vegetation_density": {
            label: _class_summary(vd == (i + 1), pixel_area)
            for i, label in enumerate(t.veg_density_labels)
        },
        "landcover": {
            label: _class_summary(lc == (i + 1), pixel_area)
            for i, label in enumerate(t.landcover_labels)
        },
        "valid_pixels": total,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    # percentage shares for the density / land cover tables
    for table in (stats["vegetation_density"], stats["landcover"]):
        for key in table:
            table[key]["percent"] = round(table[key]["pixels"] / total * 100.0, 2)
    return stats


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------
def process_sentinel(
    cfg: Config, boundary: Optional[gpd.GeoDataFrame] = None
) -> Tuple[Dict[str, Path], dict]:
    """
    STEPS 4-10: clip, NDVI, green cover, vegetation density, land cover,
    previews and statistics. Returns (outputs, stats).
    """
    boundary = boundary if boundary is not None else load_boundary(cfg.paths.boundary)

    # ---- STEP 4: clip ----
    logger.info("=" * 62)
    logger.info("STEP 4 - Clipping raw bands to boundary.geojson")
    clipped = ensure_clipped_bands(cfg, boundary)
    bands, meta = read_clipped_bands(cfg, clipped)

    # ---- Derived products (STEP 5-8) ----
    logger.info("Computing NDVI = (B08 - B04) / (B08 + B04)")
    ndvi = compute_ndvi(bands["B08"], bands["B04"])
    gc = compute_green_cover(ndvi, cfg.thresholds.green_cover_ndvi)
    vd = compute_vegetation_density(
        ndvi, cfg.thresholds.veg_density_breaks, len(cfg.thresholds.veg_density_labels)
    )
    lc = compute_landcover(ndvi, cfg)

    products: List[Tuple[str, np.ndarray, str, Path]] = [
        ("ndvi.tif", ndvi, "float32", cfg.paths.ndvi / "ndvi.tif"),
        ("green_cover.tif", gc, "uint8", cfg.paths.greencover / "green_cover.tif"),
        ("vegetation_density.tif", vd, "uint8", cfg.paths.vegetation / "vegetation_density.tif"),
        ("landcover.tif", lc, "uint8", cfg.paths.landcover / "landcover.tif"),
    ]

    outputs: Dict[str, Path] = {}
    for name, arr, dtype, out in tqdm(products, desc="Writing products", leave=False):
        if out.exists() and cfg.pipeline.skip_existing and not cfg.pipeline.force:
            outputs[name] = out
            continue
        m = meta.copy()
        m.update(dtype=dtype, count=1, compress="deflate",
                 tiled=True, blockxsize=256, blockysize=256)
        if dtype == "uint8":
            m["nodata"] = 0
        atomic_write_geotiff(out, arr, m)
        outputs[name] = out
        logger.info("Product written -> %s", out)

    # ---- STEP 9: previews ----
    logger.info("Generating preview maps")
    cfg.paths.previews.mkdir(parents=True, exist_ok=True)
    previews: Dict[str, Path] = {
        "rgb_composite.png": cfg.paths.previews / "rgb_composite.png",
        "ndvi.png": cfg.paths.previews / "ndvi.png",
        "green_cover.png": cfg.paths.previews / "green_cover.png",
        "vegetation_density.png": cfg.paths.previews / "vegetation_density.png",
        "landcover.png": cfg.paths.previews / "landcover.png",
        "overview.png": cfg.paths.previews / "overview.png",
    }
    jobs = [
        (preview_rgb, (bands, meta, cfg, previews["rgb_composite.png"])),
        (preview_ndvi, (ndvi, meta, cfg, previews["ndvi.png"])),
        (preview_green_cover, (gc, meta, cfg, previews["green_cover.png"])),
        (preview_density, (vd, meta, cfg, previews["vegetation_density.png"])),
        (preview_landcover, (lc, meta, cfg, previews["landcover.png"])),
        (preview_overview, ({
            "ndvi": ndvi, "gc": gc, "vd": vd, "lc": lc,
        }, meta, cfg, previews["overview.png"])),
    ]
    for fn, args in tqdm(jobs, desc="Creating previews", leave=False):
        fn(*args)

    # STEP 5 also asks for ndvi.png next to the raster + ndvi_statistics.json
    shutil.copyfile(previews["ndvi.png"], cfg.paths.ndvi / "ndvi.png")

    # ---- STEP 10: statistics ----
    scene_meta = read_json(cfg.paths.raw_sentinel / "metadata.json")
    scene = {
        "scene_id": scene_meta.get("scene_id"),
        "provider": scene_meta.get("provider"),
        "acquisition_date": scene_meta.get("datetime"),
        "cloud_cover": scene_meta.get("cloud_cover"),
    }
    stats = compute_stats(ndvi, gc, vd, lc, meta, scene, cfg)

    ndvi_stats = {
        "mean_ndvi": stats["ndvi"]["mean"],
        "max_ndvi": stats["ndvi"]["max"],
        "min_ndvi": stats["ndvi"]["min"],
        "green_cover_percent": stats["green_cover"]["percent"],
        "vegetation_area_km2": stats["green_cover"]["area_km2"],
        "resolution_m": stats["resolution_m"],
        "crs": stats["crs"],
        "acquisition_date": scene.get("acquisition_date"),
        "scene_id": scene.get("scene_id"),
        "provider": scene.get("provider"),
    }
    write_json(cfg.paths.ndvi / "ndvi_statistics.json", ndvi_stats)
    stats_path = write_json(cfg.paths.stats / "stats.json", stats)
    outputs["stats.json"] = stats_path
    logger.info("Statistics written -> %s / ndvi_statistics.json", stats_path)

    logger.info("Processing complete: %d output files", len(outputs))
    return outputs, stats


if __name__ == "__main__":  # pragma: no cover
    from utils import setup_logging

    cfg = Config.from_env()
    cfg.paths.ensure()
    setup_logging(cfg)
    outputs, stats = process_sentinel(cfg)
    print(f"\nMean NDVI: {stats['ndvi']['mean']}")
    print(f"Green cover: {stats['green_cover']['percent']}%")
    for name, path in outputs.items():
        print(f"  {name}: {path}")
