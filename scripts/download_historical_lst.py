#!/usr/bin/env python3
"""
Download Historical Landsat LST Scenes
=======================================
Searches Microsoft Planetary Computer for Landsat 8/9 Collection 2 Level-2
scenes covering the Bhubaneswar boundary, spanning multiple years and seasons.

Outputs:
    data/historical_lst/scenes/{scene_id}/
        ST_B10.tif          - Surface temperature band (raw DN)
        QA_PIXEL.tif        - Quality/pixel mask
        metadata.json       - Scene metadata (acquisition date, cloud cover, etc.)

    data/historical_lst/catalogue.json   - Full catalogue of downloaded scenes
    data/historical_lst/manifest.json    - Pipeline provenance

Usage:
    python scripts/download_historical_lst.py
    python scripts/download_historical_lst.py --start-year 2022 --end-year 2025
    python scripts/download_historical_lst.py --max-cloud 20 --max-scenes 50
    python scripts/download_historical_lst.py --force  # re-download everything

Scientific integrity:
    - Only uses real Landsat Collection 2 Level-2 Surface Temperature (ST_B10)
    - Applies QA_PIXEL cloud masking (bits 0-4: fill, dilated cloud, cirrus, cloud, shadow)
    - Records valid pixel fraction for each scene
    - Never fabricates or interpolates missing data
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np

# Project root
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "gis-engine"))

from utils import (
    PipelineError,
    atomic_write_geotiff,
    covers_boundary,
    item_datetime_utc,
    load_boundary,
    sign_pc_assets,
    utm_epsg_for,
    write_json,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("download_historical_lst")

# --- USGS Collection 2 Level-2 Surface Temperature scale factors ---
# Source: USGS Landsat Collection 2 Level-2 Product Guide
DEFAULT_SCALE_MUL = 0.00341802
DEFAULT_SCALE_ADD = 149.0
KELVIN_TO_CELSIUS = -273.15

# QA_PIXEL bit masks (bits 0-4)
QA_FILL_BIT = 0
QA_DILATED_CLOUD_BIT = 1
QA_CIRRUS_BIT = 2
QA_CLOUD_BIT = 3
QA_CLOUD_SHADOW_BIT = 4
QA_CLOUD_MASK = (
    (1 << QA_FILL_BIT)
    | (1 << QA_DILATED_CLOUD_BIT)
    | (1 << QA_CIRRUS_BIT)
    | (1 << QA_CLOUD_BIT)
    | (1 << QA_CLOUD_SHADOW_BIT)
)

# Output paths
HISTORICAL_DIR = PROJECT_ROOT / "data" / "historical_lst"
SCENES_DIR = HISTORICAL_DIR / "scenes"
CATALOGUE_PATH = HISTORICAL_DIR / "catalogue.json"
MANIFEST_PATH = HISTORICAL_DIR / "manifest.json"
BOUNDARY_PATH = PROJECT_ROOT / "boundary.geojson"

# Planetary Computer STAC
PC_STAC_URL = "https://planetarycomputer.microsoft.com/api/stac/v1"
LANDSAT_COLLECTION = "landsat-c2-l2"

# Asset keys for Planetary Computer
ASSET_KEYS = {"ST_B10": "lwir11", "QA_PIXEL": "qa_pixel"}


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Download historical Landsat LST scenes for Bhubaneswar"
    )
    p.add_argument("--start-year", type=int, default=2022,
                   help="Start year for search (default: 2022)")
    p.add_argument("--end-year", type=int, default=2026,
                   help="End year for search (default: 2026)")
    p.add_argument("--max-cloud", type=float, default=30.0,
                   help="Maximum cloud cover percentage (default: 30)")
    p.add_argument("--max-scenes", type=int, default=60,
                   help="Maximum number of scenes to download (default: 60)")
    p.add_argument("--force", action="store_true",
                   help="Re-download all scenes even if they exist")
    p.add_argument("--dry-run", action="store_true",
                   help="Search only, do not download")
    return p.parse_args()


def search_landsat_scenes(
    boundary_geom,
    boundary_box: tuple,
    start_date: datetime,
    end_date: datetime,
    max_cloud: float,
    max_items: int,
) -> List[dict]:
    """Search Planetary Computer for Landsat C2 L2 scenes."""
    try:
        import planetary_computer
        import pystac_client
    except ImportError as e:
        raise PipelineError(
            "Missing packages: pip install pystac-client planetary-computer"
        ) from e

    catalog = pystac_client.Client.open(
        PC_STAC_URL, modifier=planetary_computer.sign_inplace
    )

    bbox = [float(v) for v in boundary_box]
    search = catalog.search(
        collections=[LANDSAT_COLLECTION],
        bbox=bbox,
        datetime=f"{start_date.isoformat()}/{end_date.isoformat()}",
        query={"eo:cloud_cover": {"lt": max_cloud}},
        max_items=max_items,
    )

    items = list(search.items())
    log.info("Planetary Computer: %d Landsat candidate scenes (cloud < %.0f%%)",
             len(items), max_cloud)
    return items


def filter_scenes(
    items: list,
    boundary_geom,
    boundary_box: tuple,
    max_cloud: float,
) -> list:
    """Filter scenes that fully cover the boundary with acceptable cloud cover."""
    valid = []
    for item in items:
        cloud = item.properties.get("eo:cloud_cover")
        if cloud is not None and float(cloud) >= max_cloud:
            continue
        if not covers_boundary(item, boundary_geom, boundary_box):
            log.debug("Scene %s does not cover boundary", item.id)
            continue
        valid.append(item)

    # Sort by acquisition date (oldest first for temporal analysis)
    valid.sort(key=lambda x: item_datetime_utc(x))
    log.info("Filtered to %d scenes that cover the boundary", len(valid))
    return valid


def download_scene_bands(
    item,
    scene_dir: Path,
    epsg: int,
    boundary_geom,
    force: bool,
) -> Dict[str, Path]:
    """Download ST_B10 and QA_PIXEL bands for a single scene."""
    import stackstac
    import rioxarray  # noqa: F401  (registers .rio accessor on xarray objects)

    scene_id = item.id
    scene_dir.mkdir(parents=True, exist_ok=True)

    paths = {}
    bands_to_download = ["ST_B10", "QA_PIXEL"]

    # Check if already downloaded
    all_exist = all((scene_dir / f"{b}.tif").exists() for b in bands_to_download)
    if all_exist and not force:
        log.info("Scene %s already downloaded - skipping", scene_id)
        return {b: scene_dir / f"{b}.tif" for b in bands_to_download}

    # Sign assets
    sign_pc_assets(item)

    # Get boundary bounds in UTM
    import geopandas as gpd
    boundary_utm = boundary_geom.to_crs(f"EPSG:{epsg}")
    bounds_utm = [float(v) for v in boundary_utm.total_bounds]

    asset_names = [ASSET_KEYS.get(b, b) for b in bands_to_download]

    try:
        da = stackstac.stack(
            [item],
            assets=asset_names,
            epsg=epsg,
            resolution=30,
            bounds=list(bounds_utm),
            dtype="uint16",
            rescale=False,
            fill_value=np.uint16(0),
            chunksize={"x": 2048, "y": 2048},
        )
        da = da.compute()
    except Exception as exc:
        log.error("Failed to read scene %s: %s", scene_id, exc)
        return {}

    for band_name in bands_to_download:
        asset_key = ASSET_KEYS.get(band_name, band_name)
        out_path = scene_dir / f"{band_name}.tif"

        if out_path.exists() and not force:
            paths[band_name] = out_path
            continue

        band_da = da.sel(band=asset_key).squeeze()
        data = band_da.values.astype(np.uint16)
        transform = band_da.rio.transform()

        meta = {
            "driver": "GTiff",
            "dtype": "uint16",
            "count": 1,
            "height": data.shape[0],
            "width": data.shape[1],
            "crs": f"EPSG:{epsg}",
            "transform": transform,
            "nodata": 0,
            "compress": "deflate",
            "tiled": True,
            "blockxsize": 256,
            "blockysize": 256,
        }
        atomic_write_geotiff(out_path, data, meta)
        paths[band_name] = out_path
        log.info("Saved %s for scene %s", band_name, scene_id)

    return paths


def compute_cloud_stats(qa_path: Path) -> dict:
    """Compute cloud statistics from QA_PIXEL band."""
    import rasterio

    with rasterio.open(qa_path) as src:
        qa = src.read(1)

    total_pixels = qa.size
    cloud_mask = (qa.astype(np.uint16) & QA_CLOUD_MASK) != 0
    cloud_pixels = int(cloud_mask.sum())
    valid_pixels = total_pixels - cloud_pixels

    return {
        "total_pixels": total_pixels,
        "cloud_masked_pixels": cloud_pixels,
        "valid_pixels": valid_pixels,
        "valid_pixel_fraction": round(valid_pixels / total_pixels, 4) if total_pixels > 0 else 0.0,
        "cloud_fraction": round(cloud_pixels / total_pixels, 4) if total_pixels > 0 else 0.0,
    }


def compute_lst_stats(st_path: Path, qa_path: Optional[Path]) -> dict:
    """Compute LST statistics from ST_B10 band with optional cloud masking."""
    import rasterio

    with rasterio.open(st_path) as src:
        st = src.read(1).astype(np.float32)

    # Apply USGS scaling: ST_K = DN * scale_mul + scale_add
    lst_k = st * DEFAULT_SCALE_MUL + DEFAULT_SCALE_ADD
    lst_c = lst_k + KELVIN_TO_CELSIUS

    # Mask nodata (DN = 0)
    lst_c[st == 0] = np.nan

    # Apply cloud mask if QA_PIXEL available
    if qa_path and qa_path.exists():
        with rasterio.open(qa_path) as src:
            qa = src.read(1)
        cloud_mask = (qa.astype(np.uint16) & QA_CLOUD_MASK) != 0
        lst_c[cloud_mask] = np.nan

    valid = lst_c[~np.isnan(lst_c)]
    if len(valid) == 0:
        return {"error": "No valid LST pixels after masking"}

    return {
        "mean_lst_c": round(float(np.mean(valid)), 2),
        "median_lst_c": round(float(np.median(valid)), 2),
        "min_lst_c": round(float(np.min(valid)), 2),
        "max_lst_c": round(float(np.max(valid)), 2),
        "std_lst_c": round(float(np.std(valid)), 2),
        "p5_lst_c": round(float(np.percentile(valid, 5)), 2),
        "p95_lst_c": round(float(np.percentile(valid, 95)), 2),
        "valid_pixel_count": int(len(valid)),
    }


def get_season(date_str: str) -> str:
    """Classify a date into Bhubaneswar season."""
    try:
        month = int(date_str.split("-")[1])
    except (ValueError, IndexError):
        return "unknown"

    if month in (12, 1, 2):
        return "winter"
    elif month in (3, 4, 5):
        return "pre_monsoon"
    elif month in (6, 7, 8, 9):
        return "monsoon"
    elif month in (10, 11):
        return "post_monsoon"
    return "unknown"


def build_catalogue(
    scenes: List[dict],
    start_year: int,
    end_year: int,
    max_cloud: float,
) -> dict:
    """Build the full catalogue metadata."""
    dates = [s["date"] for s in scenes]
    seasons = {}
    for s in scenes:
        season = s.get("season", "unknown")
        seasons.setdefault(season, []).append(s["date"])

    return {
        "source": "Landsat Collection 2 Level-2 Surface Temperature",
        "product": "USGS Landsat 8/9 Collection 2 Level-2 Surface Temperature (ST_B10)",
        "location": "Bhubaneswar",
        "crs": "EPSG:32645",
        "resolution_m": 30,
        "scale_factor": DEFAULT_SCALE_MUL,
        "scale_offset": DEFAULT_SCALE_ADD,
        "kelvin_to_celsius": KELVIN_TO_CELSIUS,
        "quality_filter": "QA_PIXEL bits 0-4 (fill, dilated cloud, cirrus, cloud, cloud shadow)",
        "search_parameters": {
            "start_year": start_year,
            "end_year": end_year,
            "max_cloud_cover_pct": max_cloud,
            "provider": "Microsoft Planetary Computer",
            "collection": LANDSAT_COLLECTION,
        },
        "scene_count": len(scenes),
        "first_date": dates[0] if dates else None,
        "latest_date": dates[-1] if dates else None,
        "date_range_years": round(
            (datetime.fromisoformat(dates[-1]) - datetime.fromisoformat(dates[0])).days / 365.25, 1
        ) if len(dates) >= 2 else 0,
        "seasons": {k: {"count": len(v), "dates": sorted(v)} for k, v in seasons.items()},
        "observations": scenes,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def main() -> int:
    args = parse_args()
    t_start = time.time()

    log.info("=" * 72)
    log.info("HISTORICAL LANDSAT LST DOWNLOAD")
    log.info("Start year: %d | End year: %d | Max cloud: %.0f%% | Max scenes: %d",
             args.start_year, args.end_year, args.max_cloud, args.max_scenes)
    log.info("=" * 72)

    # Ensure directories exist
    SCENES_DIR.mkdir(parents=True, exist_ok=True)

    # Load boundary
    boundary = load_boundary(BOUNDARY_PATH)
    boundary_geom = boundary.geometry.union_all()
    boundary_box = tuple(boundary.total_bounds)
    epsg = utm_epsg_for(boundary)
    log.info("Boundary: EPSG:%d, bbox %s", epsg,
             [round(v, 4) for v in boundary_box])

    # Search date range
    start_date = datetime(args.start_year, 1, 1, tzinfo=timezone.utc)
    end_date = datetime(args.end_year, 12, 31, tzinfo=timezone.utc)

    # Search Planetary Computer
    log.info("Searching Planetary Computer for Landsat scenes...")
    try:
        items = search_landsat_scenes(
            boundary_geom, boundary_box, start_date, end_date,
            args.max_cloud, args.max_scenes * 2,
        )
    except PipelineError as exc:
        log.error("Search failed: %s", exc)
        return 1

    if not items:
        log.error("No scenes found")
        return 1

    # Filter to scenes covering the boundary
    valid_items = filter_scenes(items, boundary_geom, boundary_box, args.max_cloud)
    if not valid_items:
        log.error("No scenes pass the filter")
        return 1

    # Limit to max_scenes
    if len(valid_items) > args.max_scenes:
        log.info("Limiting to %d scenes (from %d candidates)", args.max_scenes, len(valid_items))
        valid_items = valid_items[:args.max_scenes]

    if args.dry_run:
        log.info("DRY RUN - would download %d scenes:", len(valid_items))
        for item in valid_items:
            dt = item_datetime_utc(item)
            cloud = item.properties.get("eo:cloud_cover", -1)
            log.info("  %s | %s | cloud %.1f%%", item.id, dt.strftime("%Y-%m-%d"), cloud)
        return 0

    # Download each scene
    scenes_metadata = []
    success_count = 0
    fail_count = 0

    for i, item in enumerate(valid_items):
        scene_id = item.id
        dt = item_datetime_utc(item)
        date_str = dt.strftime("%Y-%m-%d")
        cloud_cover = float(item.properties.get("eo:cloud_cover", -1))
        season = get_season(date_str)

        log.info("[%d/%d] Processing scene %s (%s, cloud %.1f%%, season=%s)",
                 i + 1, len(valid_items), scene_id, date_str, cloud_cover, season)

        scene_dir = SCENES_DIR / scene_id

        try:
            # Download bands
            paths = download_scene_bands(item, scene_dir, epsg, boundary, args.force)
            if not paths:
                log.warning("No bands downloaded for %s", scene_id)
                fail_count += 1
                continue

            # Compute cloud stats
            qa_path = paths.get("QA_PIXEL")
            cloud_stats = compute_cloud_stats(qa_path) if qa_path else {}

            # Compute LST stats
            st_path = paths.get("ST_B10")
            lst_stats = compute_lst_stats(st_path, qa_path) if st_path else {}

            # Scene metadata
            scene_meta = {
                "scene_id": scene_id,
                "date": date_str,
                "acquisition_datetime": dt.isoformat(),
                "season": season,
                "cloud_cover_pct": cloud_cover,
                "provider": "planetary-computer",
                "collection": LANDSAT_COLLECTION,
                "resolution_m": 30,
                "crs": f"EPSG:{epsg}",
                "scale_mul": DEFAULT_SCALE_MUL,
                "scale_add": DEFAULT_SCALE_ADD,
                "cloud_mask_bits": QA_CLOUD_MASK,
                "bands": {b: str(p) for b, p in paths.items()},
                "cloud_stats": cloud_stats,
                "lst_stats": lst_stats,
                "valid_pixel_fraction": cloud_stats.get("valid_pixel_fraction", 0),
                "has_valid_data": lst_stats.get("valid_pixel_count", 0) > 0,
            }

            # Reject scenes with too few valid pixels
            valid_frac = cloud_stats.get("valid_pixel_fraction", 0)
            if valid_frac < 0.5:
                log.warning("Scene %s has only %.1f%% valid pixels - marking as low quality",
                           scene_id, valid_frac * 100)
                scene_meta["quality_flag"] = "low_quality"

            # Write scene metadata
            meta_path = scene_dir / "metadata.json"
            write_json(meta_path, scene_meta)

            scenes_metadata.append(scene_meta)
            success_count += 1

            log.info("  LST: mean=%.1f°C, range=[%.1f, %.1f]°C, valid=%.1f%%",
                     lst_stats.get("mean_lst_c", 0),
                     lst_stats.get("min_lst_c", 0),
                     lst_stats.get("max_lst_c", 0),
                     valid_frac * 100)

        except Exception as exc:
            log.error("Failed to process scene %s: %s", scene_id, exc)
            fail_count += 1
            continue

        # Rate limiting: be kind to Planetary Computer
        time.sleep(0.5)

    # Sort scenes by date
    scenes_metadata.sort(key=lambda s: s["date"])

    # Build catalogue
    catalogue = build_catalogue(
        scenes_metadata, args.start_year, args.end_year, args.max_cloud
    )
    write_json(CATALOGUE_PATH, catalogue)

    # Build manifest
    manifest = {
        "pipeline": "download_historical_lst",
        "version": "1.0.0",
        "start_year": args.start_year,
        "end_year": args.end_year,
        "max_cloud_cover": args.max_cloud,
        "max_scenes": args.max_scenes,
        "scenes_found": len(valid_items),
        "scenes_downloaded": success_count,
        "scenes_failed": fail_count,
        "low_quality_scenes": sum(
            1 for s in scenes_metadata if s.get("quality_flag") == "low_quality"
        ),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "elapsed_seconds": round(time.time() - t_start, 1),
    }
    write_json(MANIFEST_PATH, manifest)

    # Summary
    elapsed = time.time() - t_start
    log.info("=" * 72)
    log.info("DOWNLOAD COMPLETE (%.1f seconds)", elapsed)
    log.info("Scenes downloaded: %d / %d (failed: %d)", success_count, len(valid_items), fail_count)
    log.info("Low quality: %d", manifest["low_quality_scenes"])
    log.info("Date range: %s to %s (%.1f years)",
             catalogue["first_date"], catalogue["latest_date"],
             catalogue["date_range_years"])
    log.info("Seasons: %s", {k: v["count"] for k, v in catalogue["seasons"].items()})
    log.info("Output: %s", HISTORICAL_DIR)
    log.info("=" * 72)

    return 0 if fail_count == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
