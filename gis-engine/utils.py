"""
Shared utilities for the Sentinel-2 pipeline
============================================
Logging, boundary loading, UTM handling, resumable downloads, safe math and
raster I/O helpers used by both the download and process stages.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional

import geopandas as gpd
import numpy as np
import rasterio
from rasterio.transform import Affine
from tqdm import tqdm

if sys.version_info >= (3, 9):
    from urllib.error import HTTPError, URLError
    from urllib.request import Request, urlopen
else:  # pragma: no cover
    from urllib2 import HTTPError, URLError, Request, urlopen  # type: ignore


class PipelineError(Exception):
    """Raised when a pipeline stage cannot complete."""


logger = logging.getLogger("sentinel.utils")


def setup_logging(cfg) -> logging.Logger:
    """Configure a single root logger writing to stdout and logs/ dir."""
    cfg.paths.logs.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    if root.handlers:  # already configured (e.g. tests / re-import)
        return root

    log_file = cfg.paths.logs / "sentinel_pipeline.log"
    handlers = [
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(log_file, mode="a", encoding="utf-8"),
    ]
    logging.basicConfig(
        level=getattr(logging, str(cfg.pipeline.log_level).upper(), logging.INFO),
        format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=handlers,
    )
    return root


# ---------------------------------------------------------------------------
# Boundary handling
# ---------------------------------------------------------------------------
def load_boundary(path: Path) -> gpd.GeoDataFrame:
    """
    Read and validate boundary.geojson (STEP 1).

    Returns a GeoDataFrame in EPSG:4326 with a non-empty geometry.
    """
    logger = logging.getLogger("sentinel.utils")
    path = Path(path)
    if not path.exists():
        raise PipelineError(f"Boundary file not found: {path}")

    gdf = gpd.read_file(path)
    if gdf.empty:
        raise PipelineError(f"Boundary file contains no features: {path}")
    if gdf.crs is None:
        logger.warning("Boundary has no CRS - assuming EPSG:4326")
        gdf = gdf.set_crs("EPSG:4326")
    if gdf.crs.to_epsg() != 4326:
        gdf = gdf.to_crs("EPSG:4326")

    logger.info(
        "Boundary loaded: %d feature(s), CRS %s, bbox %s",
        len(gdf), gdf.crs, [round(v, 6) for v in gdf.total_bounds],
    )
    return gdf


def utm_epsg_for(boundary: gpd.GeoDataFrame) -> int:
    """Pick the UTM zone EPSG code from the boundary centroid (lon/lat)."""
    minx, miny, maxx, maxy = boundary.total_bounds
    lon, lat = (minx + maxx) / 2.0, (miny + maxy) / 2.0
    zone = int((lon + 180.0) // 6.0) + 1
    return (32600 + zone) if lat >= 0 else (32700 + zone)


# ---------------------------------------------------------------------------
# Generic STAC helpers (shared by the Sentinel-2 and Landsat pipelines)
# ---------------------------------------------------------------------------
def item_datetime_utc(item) -> datetime:
    """Return the item's acquisition time as a tz-aware datetime (UTC)."""
    dt = getattr(item, "datetime", None)
    if dt is None:
        return datetime.min.replace(tzinfo=timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def covers_boundary(item, boundary_geom, boundary_box: tuple) -> bool:
    """True when the scene footprint covers the entire study boundary."""
    from shapely.geometry import shape

    tol = 1e-7  # ~1 cm, absorbs floating point jitter
    try:
        if shape(item.geometry).covers(boundary_geom):
            return True
    except Exception:
        pass
    try:
        ib = list(item.bbox)
    except Exception:
        try:
            ib = list(shape(item.geometry).bounds)
        except Exception:
            return False
    return (
        ib[0] - tol <= boundary_box[0]
        and ib[1] - tol <= boundary_box[1]
        and ib[2] + tol >= boundary_box[2]
        and ib[3] + tol >= boundary_box[3]
    )


def select_best_scene(items: list, boundary: gpd.GeoDataFrame, max_cloud_cover: float):
    """
    Pick the newest scene that is cloud-clean and fully covers the boundary.
    Items are expected to be cloud-filtered already; this is a final check.
    """
    if not items:
        raise PipelineError("No scenes returned by any provider")
    boundary_geom = boundary.geometry.union_all()
    boundary_box = tuple(boundary.total_bounds)


    for item in sorted(items, key=item_datetime_utc, reverse=True):
        cloud = item.properties.get("eo:cloud_cover")
        if cloud is not None and float(cloud) >= max_cloud_cover:
            continue
        if not covers_boundary(item, boundary_geom, boundary_box):
            logger.debug("Scene %s does not fully cover the boundary", item.id)
            continue
        logger.info(
            "Selected scene: %s | %s | cloud %.1f%%",
            item.id, item_datetime_utc(item).isoformat(),
            float(cloud) if cloud is not None else -1.0,
        )
        return item
    raise PipelineError(
        f"No scene both newer than the lookback window, with cloud cover < "
        f"{max_cloud_cover:.1f}%, fully covering the boundary. Relax the cloud / "
        f"date filters or check network access."
    )


def sign_pc_assets(item) -> None:
    """Sign Planetary Computer asset URLs in place so lazy reads never expire."""
    import planetary_computer

    for key, asset in item.assets.items():
        if asset.href and "sig=" not in asset.href:
            try:
                asset.href = planetary_computer.sign(asset.href)
            except Exception:
                logger.debug("Could not sign asset %s", key, exc_info=True)


def read_stackstac_window(item, assets, epsg: int, resolution: int, bounds: tuple,
                          retries: int = 3) -> "xarray.DataArray":
    """
    Read the given asset bands clipped to ``bounds`` (in the output CRS) at
    ``resolution`` via stackstac, retrying transient network failures.
    Returns the fully-computed uint16 DataArray (raw DN, no rescaling).
    """
    import stackstac
    import time

    last_error: Optional[Exception] = None
    for attempt in range(retries + 1):
        try:
            da = stackstac.stack(
                [item],
                assets=assets,
                epsg=epsg,
                resolution=resolution,
                bounds=list(bounds),
                dtype="uint16",
                rescale=False,
                fill_value=np.uint16(0),  # np.can_cast requires a uint16-typed fill
                chunksize={"x": 2048, "y": 2048},
            )
            return da.compute()
        except Exception as e:
            last_error = e
            logger.warning(
                "stackstac read failed (attempt %d/%d): %s",
                attempt + 1, retries + 1, e,
            )
            time.sleep(min(2 ** attempt, 30))
    raise PipelineError(f"Failed to read scene (after {retries + 1} attempts): {last_error}")


def clip_to_boundary(src_path: Path, out_path: Path, geom, epsg: int,
                     dtype: Optional[str] = None, nodata=None) -> None:
    """
    Generic clip of a raster to a boundary geometry (same CRS), preserving
    source dtype/nodata unless overridden. Writes atomically.
    """
    with rasterio.open(src_path) as src:
        if src.crs is None or src.crs.to_epsg() != epsg:
            raise PipelineError(
                f"{Path(src_path).name} is in unexpected CRS {src.crs} "
                f"(expected EPSG:{epsg})"
            )
        out_img, out_transform = rasterio.mask.mask(
            src, [geom], crop=True, filled=True
        )
        meta = src.meta.copy()
        out_dtype = dtype if dtype is not None else meta["dtype"]
        out_nodata = meta["nodata"] if nodata is None else nodata
        meta.update(
            driver="GTiff", dtype=out_dtype, count=1,
            height=out_img.shape[1], width=out_img.shape[2],
            transform=out_transform, crs=src.crs, nodata=out_nodata,
            compress="deflate", tiled=True, blockxsize=256, blockysize=256,
        )
        data = out_img[0] if dtype is None else out_img[0].astype(out_dtype)
    atomic_write_geotiff(out_path, data, meta)
    logger.info("Clipped %s -> %s (%d x %d px)", Path(src_path).name, out_path,
                meta["width"], meta["height"])


# ---------------------------------------------------------------------------
# Safe arithmetic
# ---------------------------------------------------------------------------
def safe_divide(num: np.ndarray, den: np.ndarray, fill: float = np.nan) -> np.ndarray:
    """Element-wise num/den with division-by-zero protection."""
    with np.errstate(divide="ignore", invalid="ignore"):
        out = np.where(den != 0, num / den, fill)
    return out


# ---------------------------------------------------------------------------
# Resumable HTTP download
# ---------------------------------------------------------------------------
def resumable_download(
    url: str,
    dest: Path,
    headers: Optional[Dict[str, str]] = None,
    chunk_size: int = 1 << 20,
    retries: int = 3,
    timeout: int = 120,
    logger: Optional[logging.Logger] = None,
) -> Path:
    """
    Download ``url`` to ``dest``, resuming interrupted transfers via HTTP Range.

    Writes to ``dest.part`` and atomically renames on success, so a killed run
    can be resumed by simply re-running the pipeline. Retries with backoff.
    """
    log = logger or logging.getLogger("sentinel.utils")
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(str(dest) + ".part")
    base_headers = dict(headers or {})

    for attempt in range(retries + 1):
        try:
            existing = tmp.stat().st_size if tmp.exists() else 0
            req_headers = dict(base_headers)
            if existing > 0:
                req_headers["Range"] = f"bytes={existing}-"

            req = Request(url, headers=req_headers)
            resp = urlopen(req, timeout=timeout)
            try:
                if resp.status == 206 and existing > 0:
                    total = int(resp.headers.get("Content-Range", "/0").split("/")[-1] or 0)
                    mode, initial = "ab", existing
                else:
                    # Server ignored the Range header -> restart from scratch.
                    if existing > 0:
                        log.warning("Server ignored Range request; restarting %s", dest.name)
                    total = int(resp.headers.get("Content-Length") or 0)
                    mode, initial = "wb", 0

                with open(tmp, mode) as fh, tqdm(
                    total=total, initial=initial, unit="B", unit_scale=True,
                    desc=f"downloading {dest.name}", leave=False,
                ) as pbar:
                    while True:
                        chunk = resp.read(chunk_size)
                        if not chunk:
                            break
                        fh.write(chunk)
                        pbar.update(len(chunk))
            finally:
                resp.close()

            os.replace(tmp, dest)
            log.info("Downloaded %s -> %s (%.1f MiB)", dest.name, dest, tmp_size_mib(dest))
            return dest

        except HTTPError as e:
            if e.code == 416 and tmp.exists():
                # Range start beyond file end: file already complete or corrupt.
                log.warning("Server returned 416 for %s; restarting file", dest.name)
                tmp.unlink(missing_ok=True)
                continue
            if attempt < retries:
                log.warning("HTTP error %s on %s (attempt %d/%d)", e.code, dest.name, attempt + 1, retries + 1)
            else:
                raise PipelineError(f"Download failed for {url}: HTTP {e.code}") from e
        except URLError as e:
            if attempt < retries:
                log.warning("Network error on %s (attempt %d/%d): %s", dest.name, attempt + 1, retries + 1, e)
            else:
                raise PipelineError(f"Download failed for {url}: {e}") from e

        time.sleep(min(2 ** attempt, 30))  # exponential backoff

    raise PipelineError(f"Download failed after {retries + 1} attempts: {url}")


def tmp_size_mib(path: Path) -> float:
    try:
        return path.stat().st_size / (1024 * 1024)
    except OSError:
        return 0.0


# ---------------------------------------------------------------------------
# Raster I/O
# ---------------------------------------------------------------------------
def atomic_write_geotiff(path: Path, data: np.ndarray, meta: dict) -> Path:
    """
    Write a single-band GeoTIFF via ``path.part`` + atomic rename so a crash
    never leaves a half-written file that looks complete.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(str(path) + ".part")
    try:
        with rasterio.open(tmp, "w", **meta) as dst:
            dst.write(np.asarray(data), 1)
        os.replace(tmp, path)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise
    return path


def read_band(path: Path) -> tuple:
    """Read a single-band raster; returns (float32 array, metadata dict)."""
    with rasterio.open(path) as src:
        meta = src.meta.copy()
        data = src.read(1).astype(np.float32)
    return data, meta


def geotransform_extent(meta: dict) -> tuple:
    """(left, right, bottom, top) in CRS units from rasterio metadata."""
    t: Affine = meta["transform"]
    w, h = meta["width"], meta["height"]
    left, top = t.c, t.f
    right = left + w * t.a
    bottom = top + h * t.e
    return left, right, bottom, top


def write_json(path: Path, obj: dict) -> Path:
    """Write a JSON file with stable ordering and 2-space indent."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, indent=2, sort_keys=False)
    return path


def read_json(path: Path, default: Optional[dict] = None) -> dict:
    """Read a JSON file, returning ``default`` if missing/invalid."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return dict(default or {})
