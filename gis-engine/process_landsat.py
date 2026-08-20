"""
STEPS 4-10 - Landsat LST processing: clip, scaling, LST, heat classes, previews, stats
======================================================================================
Reads the raw Landsat bands in ``data/raw/landsat/``, clips them to
boundary.geojson, then derives:

  STEP 5-6  LST from the USGS Collection-2 Level-2 ST_B10 scaling factors
  STEP 7    Heat classification (6 classes: Very Cool .. Very Hot)
  STEP 8    matplotlib preview PNGs
  STEP 9-10 statistics (mean/max/min/std, histogram, distribution, scene info)

All products are written atomically and skipped when they already exist
(unless ``--force`` is given).
"""

from __future__ import annotations

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
from rasterio.transform import Affine
from tqdm import tqdm

from config import Config
from utils import (
    PipelineError,
    atomic_write_geotiff,
    clip_to_boundary,
    geotransform_extent,
    load_boundary,
    read_band,
    read_json,
    utm_epsg_for,
    write_json,
)

logger = logging.getLogger("sentinel.landsat.process")

HEAT_CLASS_COLORS = ["#2166ac", "#67a9cf", "#fdae61", "#f46d43", "#d73027", "#67001f"]
QA_CLOUD_MASK_BITS = 0b11111  # fill(1) | dilated cloud(2) | cirrus(4) | cloud(8) | shadow(16)


# ---------------------------------------------------------------------------
# STEP 4 - Clip
# ---------------------------------------------------------------------------
def ensure_clipped_bands(cfg: Config, boundary: gpd.GeoDataFrame) -> Dict[str, Path]:
    """Clip ST_B10 + QA_PIXEL to boundary.geojson (preserving uint16 DNs)."""
    epsg = cfg.landsat.utm_epsg or utm_epsg_for(boundary)
    boundary_utm = boundary.to_crs(f"EPSG:{epsg}")
    geom = boundary_utm.geometry.union_all()

    clipped: Dict[str, Path] = {}
    for band in cfg.landsat.bands:
        raw = cfg.paths.raw_landsat / f"{band}.tif"
        out = cfg.paths.clipped / f"{band}_clipped.tif"
        if out.exists() and cfg.pipeline.skip_existing and not cfg.pipeline.force:
            clipped[band] = out
            continue
        if not raw.exists():
            raise PipelineError(f"Raw band missing: {raw}. Run the download stage first.")
        clip_to_boundary(raw, out, geom, epsg)
        clipped[band] = out
    return clipped


# ---------------------------------------------------------------------------
# STEP 5 - USGS scaling factors (from MTL when available)
# ---------------------------------------------------------------------------
def _walk_scale_keys(d: dict, found: dict) -> None:
    for key, value in d.items():
        if "TEMPERATURE_MULT_BAND_ST_B10" in str(key).upper():
            found["mul"] = float(value)
        elif "TEMPERATURE_ADD_BAND_ST_B10" in str(key).upper():
            found["add"] = float(value)
        elif isinstance(value, dict):
            _walk_scale_keys(value, found)


def read_scale_factors(cfg: Config) -> Tuple[float, float]:
    """Return (mult, add) from the MTL file, falling back to config defaults."""
    mul, add = cfg.landsat.scale_mul, cfg.landsat.scale_add
    found: dict = {}

    mtl_json = cfg.paths.raw_landsat / "mtl.json"
    mtl_txt = cfg.paths.raw_landsat / "mtl.txt"
    if mtl_json.exists():
        _walk_scale_keys(read_json(mtl_json), found)
    elif mtl_txt.exists():
        try:
            for line in mtl_txt.read_text(encoding="utf-8").splitlines():
                if "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip().upper()
                if "TEMPERATURE_MULT_BAND_ST_B10" in key:
                    found["mul"] = float(value.strip())
                elif "TEMPERATURE_ADD_BAND_ST_B10" in key:
                    found["add"] = float(value.strip())
        except Exception:
            logger.warning("Could not parse %s; using default scaling", mtl_txt)

    if found:
        logger.info("LST scaling from MTL: ST_K = DN * %s + %s", found["mul"], found["add"])
        return found.get("mul", mul), found.get("add", add)
    logger.info("Using default USGS scaling: ST_K = DN * %s + %s", mul, add)
    return mul, add


# ---------------------------------------------------------------------------
# STEP 6 - Land Surface Temperature
# ---------------------------------------------------------------------------
def compute_lst(
    st: np.ndarray, qa: Optional[np.ndarray], cfg: Config, mul: float, add: float
) -> np.ndarray:
    """
    Surface temperature in degrees Celsius from USGS C2 L2 ST_B10 DNs.

      ST_K  = DN * mul + add          (Kelvin, per USGS product guide)
      LST_C = ST_K - 273.15

    Optional QA_PIXEL masking removes fill / dilated cloud / cirrus / cloud /
    cloud-shadow pixels (bits 0-4).
    """
    st = st.astype(np.float32)
    lst_k = st * mul + add
    lst_c = lst_k + cfg.landsat.kelvin_to_celsius

    lst_c[st == 0] = np.nan  # nodata / outside-boundary fill (DN 0)

    if cfg.landsat.mask_clouds and qa is not None:
        qa_mask = (qa.astype(np.uint16) & QA_CLOUD_MASK_BITS) != 0
        n_masked = int(qa_mask.sum())
        lst_c[qa_mask] = np.nan
        if n_masked:
            logger.info("QA_PIXEL masked %d pixel(s) (fill/cloud/cirrus/shadow)", n_masked)

    valid = lst_c[~np.isnan(lst_c)]
    if valid.size == 0:
        raise PipelineError("No valid LST pixels after masking - check scene and QA band")
    logger.info(
        "LST (Celsius): mean %.2f | min %.2f | max %.2f",
        float(np.mean(valid)), float(np.min(valid)), float(np.max(valid)),
    )
    return lst_c


# ---------------------------------------------------------------------------
# STEP 7 - Heat classification
# ---------------------------------------------------------------------------
def classify_heat(lst_c: np.ndarray, cfg: Config) -> np.ndarray:
    """
    Six classes (Very Cool, Cool, Moderate, Warm, Hot, Very Hot) -> uint8 1..6.

    method "quantile": breaks at scene percentiles (scene-adaptive).
    method "fixed"   : absolute breaks in degrees Celsius.
    """
    n = len(cfg.heat.labels)
    valid = lst_c[~np.isnan(lst_c)]
    if cfg.heat.method == "fixed":
        breaks = np.asarray(cfg.heat.fixed_breaks_c, dtype=np.float64)
    else:  # quantile
        q = np.asarray(cfg.heat.quantile_breaks, dtype=np.float64) / 100.0
        breaks = np.quantile(valid, q)

    cls = np.searchsorted(breaks, lst_c, side="right").astype(np.uint8) + 1
    cls = np.clip(cls, 1, n)
    cls[np.isnan(lst_c)] = 0  # nodata
    return cls


# ---------------------------------------------------------------------------
# STEP 8 - Previews
# ---------------------------------------------------------------------------
def _extent(meta: dict) -> tuple:
    left, right, bottom, top = geotransform_extent(meta)
    return (left, right, bottom, top)


def _finish(fig, out: Path, dpi: int) -> None:
    fig.savefig(out, dpi=dpi, bbox_inches="tight")
    plt.close(fig)
    logger.info("Preview saved -> %s", out)


def preview_lst(lst_c: np.ndarray, meta: dict, cfg: Config, out: Path) -> None:
    valid = lst_c[~np.isnan(lst_c)]
    vmin = float(np.percentile(valid, 2)) if valid.size else float(lst_c.min())
    vmax = float(np.percentile(valid, 98)) if valid.size else float(lst_c.max())

    fig, ax = plt.subplots(figsize=(12, 10))
    im = ax.imshow(lst_c, cmap="RdYlBu_r", extent=_extent(meta), vmin=vmin, vmax=vmax)
    ax.set_title("Land Surface Temperature (°C)", fontweight="bold")
    ax.set_xlabel("Easting (m)"); ax.set_ylabel("Northing (m)")
    plt.colorbar(im, ax=ax, label="°C", shrink=0.8)
    _finish(fig, out, cfg.pipeline.preview_dpi)


def preview_heat_classes(classes: np.ndarray, meta: dict, cfg: Config, out: Path) -> None:
    n = len(cfg.heat.labels)
    cmap = ListedColormap(HEAT_CLASS_COLORS[:n])
    fig, ax = plt.subplots(figsize=(12, 10))
    im = ax.imshow(classes, cmap=cmap, extent=_extent(meta), vmin=1, vmax=n)
    ax.set_title("Heat Classification", fontweight="bold")
    ax.set_xlabel("Easting (m)"); ax.set_ylabel("Northing (m)")
    ax.legend(
        handles=[Patch(facecolor=c, label=lbl)
                 for c, lbl in zip(HEAT_CLASS_COLORS[:n], cfg.heat.labels)],
        loc="lower right",
    )
    _finish(fig, out, cfg.pipeline.preview_dpi)


def preview_histogram(lst_c: np.ndarray, stats: dict, cfg: Config, out: Path) -> None:
    valid = lst_c[~np.isnan(lst_c)]
    fig, ax = plt.subplots(figsize=(11, 7))
    ax.hist(valid, bins=stats["histogram"]["bins"], color="#d73027", edgecolor="white")
    ax.axvline(stats["lst"]["mean"], color="black", linestyle="--", linewidth=1.5,
               label=f"Mean = {stats['lst']['mean']:.2f}°C")
    ax.set_title("LST Distribution (degrees Celsius)", fontweight="bold")
    ax.set_xlabel("Temperature (°C)"); ax.set_ylabel("Pixel count")
    ax.legend()
    _finish(fig, out, cfg.pipeline.preview_dpi)


def preview_overview(lst_c: np.ndarray, classes: np.ndarray, meta: dict, cfg: Config, out: Path) -> None:
    n = len(cfg.heat.labels)
    valid = lst_c[~np.isnan(lst_c)]
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(17, 9))
    im1 = ax1.imshow(lst_c, cmap="RdYlBu_r", extent=_extent(meta),
                     vmin=float(np.percentile(valid, 2)), vmax=float(np.percentile(valid, 98)))
    ax1.set_title("LST (°C)"); plt.colorbar(im1, ax=ax1, shrink=0.8)
    im2 = ax2.imshow(classes, cmap=ListedColormap(HEAT_CLASS_COLORS[:n]),
                     extent=_extent(meta), vmin=1, vmax=n)
    ax2.set_title("Heat Classification")
    for a in (ax1, ax2):
        a.set_xticks([]); a.set_yticks([])
    fig.suptitle("Landsat Land Surface Temperature - Bhubaneswar", fontweight="bold", fontsize=15)
    fig.tight_layout()
    _finish(fig, out, cfg.pipeline.preview_dpi)


# ---------------------------------------------------------------------------
# STEP 9 - Statistics
# ---------------------------------------------------------------------------
def _pixel_area(meta: dict) -> float:
    t: Affine = meta["transform"]
    return abs(t.a * t.e)  # m^2 per pixel (UTM)


def compute_stats(
    lst_c: np.ndarray, classes: np.ndarray, meta: dict, scene: dict,
    scale_mul: float, scale_add: float, cfg: Config,
) -> dict:
    valid = lst_c[~np.isnan(lst_c)]
    pixel_area = _pixel_area(meta)
    total = int(valid.size)

    hist_counts, hist_edges = np.histogram(valid, bins=20)

    # 5-degree Celsius distribution
    lo = float(np.floor(valid.min() / 5.0) * 5.0)
    hi = float(np.ceil(valid.max() / 5.0) * 5.0)
    bin5_counts, bin5_edges = np.histogram(valid, bins=np.arange(lo, hi + 5.0, 5.0))
    dist_5c = [
        {"range": f"{bin5_edges[i]:.0f}-{bin5_edges[i + 1]:.0f}",
         "percent": round(float(bin5_counts[i] / total * 100.0), 2)}
        for i in range(len(bin5_counts))
    ]

    heat = {}
    for i, label in enumerate(cfg.heat.labels):
        mask = classes == (i + 1)
        px = int(mask.sum())
        temp = lst_c[mask]
        heat[label] = {
            "pixels": px,
            "percent": round(px / total * 100.0, 2),
            "area_ha": round(px * pixel_area / 1e4, 2),
            "area_km2": round(px * pixel_area / 1e6, 4),
            "temp_min_c": round(float(temp.min()), 2) if px else None,
            "temp_max_c": round(float(temp.max()), 2) if px else None,
        }

    return {
        "scene": scene,
        "units": "celsius",
        "scaling": {"mult": scale_mul, "add": scale_add, "kelvin_to_celsius": cfg.landsat.kelvin_to_celsius},
        "crs": str(meta["crs"]),
        "resolution_m": {
            "x": round(abs(meta["transform"].a), 4),
            "y": round(abs(meta["transform"].e), 4),
        },
        "pixel_area_m2": round(pixel_area, 2),
        "lst": {
            "mean": round(float(np.mean(valid)), 2),
            "median": round(float(np.median(valid)), 2),
            "max": round(float(np.max(valid)), 2),
            "min": round(float(np.min(valid)), 2),
            "std": round(float(np.std(valid)), 2),
            "p5": round(float(np.percentile(valid, 5)), 2),
            "p95": round(float(np.percentile(valid, 95)), 2),
        },
        "histogram": {"bins": [round(float(e), 2) for e in hist_edges],
                      "counts": [int(c) for c in hist_counts]},
        "distribution_5c": dist_5c,
        "heat_classes": heat,
        "cloud_mask_bits": QA_CLOUD_MASK_BITS,
        "valid_pixels": total,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------
def process_landsat(
    cfg: Config, boundary: Optional[gpd.GeoDataFrame] = None
) -> Tuple[Dict[str, Path], dict]:
    """
    STEPS 4-10: clip, LST (USGS scaling), heat classes, previews, statistics.
    Returns (outputs, stats).
    """
    boundary = boundary if boundary is not None else load_boundary(cfg.paths.boundary)

    # ---- STEP 4: clip ----
    logger.info("=" * 62)
    logger.info("STEP 4 - Clipping Landsat bands to boundary.geojson")
    clipped = ensure_clipped_bands(cfg, boundary)

    st_path = clipped[cfg.landsat.thermal_band]
    qa_path = clipped.get(cfg.landsat.qa_band)
    st, meta = read_band(st_path)
    qa = read_band(qa_path)[0] if qa_path else None

    # ---- STEP 5-6: LST ----
    mul, add = read_scale_factors(cfg)
    lst_c = compute_lst(st, qa, cfg, mul, add)

    # ---- STEP 7: heat classes ----
    classes = classify_heat(lst_c, cfg)

    # ---- write products ----
    outputs: Dict[str, Path] = {}

    def _save(name: str, arr: np.ndarray, dtype: str, out: Path) -> None:
        if out.exists() and cfg.pipeline.skip_existing and not cfg.pipeline.force:
            outputs[name] = out
            return
        m = meta.copy()
        m.update(dtype=dtype, count=1, compress="deflate",
                 tiled=True, blockxsize=256, blockysize=256)
        m["nodata"] = np.nan if dtype == "float32" else 0
        atomic_write_geotiff(out, arr, m)
        outputs[name] = out
        logger.info("Product written -> %s", out)

    cfg.paths.lst.mkdir(parents=True, exist_ok=True)
    cfg.paths.heatmap.mkdir(parents=True, exist_ok=True)
    _save("LST.tif", lst_c, "float32", cfg.paths.lst / "LST.tif")
    _save("heat_classes.tif", classes, "uint8", cfg.paths.heatmap / "heat_classes.tif")

    # ---- STEP 8: previews ----
    logger.info("Generating Landsat preview maps")
    previews: Dict[str, Path] = {
        "lst": cfg.paths.lst / "LST.png",
        "heat_classes": cfg.paths.heatmap / "heat_classes.png",
        "lst_preview": cfg.paths.previews / "lst_preview.png",
        "heat_classes_preview": cfg.paths.previews / "heat_classes.png",
        "lst_histogram": cfg.paths.previews / "lst_histogram.png",
        "overview": cfg.paths.previews / "landsat_overview.png",
    }
    jobs = [
        (preview_lst, (lst_c, meta, cfg, previews["lst"])),
        (preview_heat_classes, (classes, meta, cfg, previews["heat_classes"])),
    ]
    for fn, args in tqdm(jobs, desc="LST previews", leave=False):
        fn(*args)
    shutil.copyfile(previews["lst"], previews["lst_preview"])
    shutil.copyfile(previews["heat_classes"], previews["heat_classes_preview"])

    # ---- STEP 9-10: statistics ----
    scene_meta = read_json(cfg.paths.raw_landsat / "metadata.json")
    scene = {
        "scene_id": scene_meta.get("scene_id"),
        "provider": scene_meta.get("provider"),
        "acquisition_date": scene_meta.get("datetime"),
        "cloud_cover": scene_meta.get("cloud_cover"),
    }
    stats = compute_stats(lst_c, classes, meta, scene, mul, add, cfg)

    # histogram + previews need the stats; generate them after compute_stats
    preview_histogram(lst_c, stats, cfg, previews["lst_histogram"])
    preview_overview(lst_c, classes, meta, cfg, previews["overview"])

    lst_stats = {
        "mean_lst_c": stats["lst"]["mean"],
        "max_lst_c": stats["lst"]["max"],
        "min_lst_c": stats["lst"]["min"],
        "std_lst_c": stats["lst"]["std"],
        "units": "celsius",
        "acquisition_date": scene.get("acquisition_date"),
        "cloud_cover": scene.get("cloud_cover"),
        "resolution_m": stats["resolution_m"],
        "crs": stats["crs"],
        "scene_id": scene.get("scene_id"),
        "provider": scene.get("provider"),
    }
    write_json(cfg.paths.lst / "LST_statistics.json", lst_stats)
    stats_path = write_json(cfg.paths.stats / "landsat_stats.json", stats)
    outputs["landsat_stats.json"] = stats_path
    logger.info("Statistics written -> %s / LST_statistics.json", stats_path)

    logger.info("Landsat processing complete: %d output files", len(outputs))
    return outputs, stats


if __name__ == "__main__":  # pragma: no cover
    from utils import setup_logging

    cfg = Config.from_env()
    cfg.paths.ensure()
    setup_logging(cfg)
    outputs, stats = process_landsat(cfg)
    print(f"\nMean LST: {stats['lst']['mean']} °C")
    print(f"Max / Min LST: {stats['lst']['max']} / {stats['lst']['min']} °C")
    for name, path in outputs.items():
        print(f"  {name}: {path}")
