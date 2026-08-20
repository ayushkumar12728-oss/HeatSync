"""
Urban Digital Twin - remote sensing pipeline entry point
========================================================
Runs the Sentinel-2 (NDVI / green cover / land cover), Landsat 8/9
(LST / heat classes), DEM (elevation / slope / aspect / hillshade /
contours), NASA POWER weather and air-quality (AQI) workflows from
``boundary.geojson``:

    python main.py                 # download + process (skips existing work)
    python main.py --force         # re-download and reprocess everything
    python main.py --skip-download # Sentinel: only process existing raw data
    python main.py --skip-process  # Sentinel: only download imagery
    python main.py --skip-landsat  # skip the Landsat LST stage entirely
    python main.py --skip-dem      # skip the DEM terrain stage entirely
    python main.py --skip-weather  # skip the NASA POWER weather stage entirely
    python main.py --skip-aqi      # skip the air quality stage entirely

Exit codes: 0 success, 1 pipeline error, 2 unexpected error, 130 Ctrl-C.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from config import Config
from utils import PipelineError, load_boundary, setup_logging

logger = logging.getLogger("sentinel.main")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="main.py",
        description="Sentinel-2 download + processing pipeline (Bhubaneswar UDT)",
    )
    p.add_argument("--boundary", type=Path, default=None,
                   help="path to boundary.geojson (default: project boundary.geojson)")
    p.add_argument("--force", action="store_true",
                   help="re-download and reprocess everything, ignoring existing files")
    p.add_argument("--no-skip", dest="skip_existing", action="store_false",
                   help="recompute outputs even if they already exist")
    p.add_argument("--cloud-max", type=float, default=None,
                   help="maximum cloud cover in %% (default from config: 10)")
    p.add_argument("--days", type=int, default=None,
                   help="search lookback window in days (default from config: 365)")
    p.add_argument("--skip-download", action="store_true",
                   help="skip the download stage, process existing raw data")
    p.add_argument("--skip-process", action="store_true",
                   help="skip the Sentinel processing stage, only download imagery")
    p.add_argument("--skip-landsat", action="store_true",
                   help="skip the Landsat 8/9 LST stage entirely")
    p.add_argument("--skip-dem", action="store_true",
                   help="skip the DEM terrain stage entirely")
    p.add_argument("--skip-weather", action="store_true",
                   help="skip the NASA POWER weather stage entirely")
    p.add_argument("--skip-aqi", action="store_true",
                   help="skip the air quality stage entirely")
    p.add_argument("--log-level", default=None,
                   choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    return p.parse_args()


def main() -> int:
    args = parse_args()

    cfg = Config.from_env()
    if args.boundary is not None:
        cfg.paths.boundary = args.boundary
    if args.force:
        cfg.pipeline.force = True
        cfg.pipeline.skip_existing = False
    if not args.skip_existing:
        cfg.pipeline.skip_existing = False
    if args.cloud_max is not None:
        cfg.sentinel.max_cloud_cover = args.cloud_max
    if args.days is not None:
        cfg.sentinel.lookback_days = args.days
    if args.log_level is not None:
        cfg.pipeline.log_level = args.log_level

    cfg.paths.ensure()
    setup_logging(cfg)

    logger.info("Urban Digital Twin - Sentinel-2 pipeline (Bhubaneswar)")
    logger.info("Boundary: %s | cloud max: %.1f%% | lookback: %d days | force: %s",
                cfg.paths.boundary, cfg.sentinel.max_cloud_cover,
                cfg.sentinel.lookback_days, cfg.pipeline.force)

    try:
        boundary = load_boundary(cfg.paths.boundary)

        if not args.skip_download:
            from download_sentinel import download_sentinel
            logger.info("-" * 62)
            logger.info("STAGE 1/2 - Search & download Sentinel-2 Level-2A")
            result = download_sentinel(cfg, boundary)
            logger.info("Scene %s (%s) acquired %s, cloud %.1f%%",
                        result.scene_id, result.provider, result.datetime,
                        result.cloud_cover if result.cloud_cover is not None else -1.0)

        if not args.skip_process:
            from process_sentinel import process_sentinel
            logger.info("-" * 62)
            logger.info("STAGE 2/6 - Sentinel: clip, NDVI, products, previews, stats")
            outputs, stats = process_sentinel(cfg, boundary)

            logger.info("-" * 62)
            logger.info("SENTINEL SUMMARY")
            logger.info("Mean NDVI      : %.4f", stats["ndvi"]["mean"])
            logger.info("Max / Min NDVI : %.4f / %.4f", stats["ndvi"]["max"], stats["ndvi"]["min"])
            logger.info("Green cover    : %.2f%% (%.2f km2)",
                        stats["green_cover"]["percent"], stats["green_cover"]["area_km2"])
            logger.info("Resolution     : %s m", stats["resolution_m"])
            logger.info("CRS            : %s", stats["crs"])
            logger.info("Acquisition    : %s", stats["scene"].get("acquisition_date"))
            for name in ("vegetation_density", "landcover"):
                shares = {k: v["percent"] for k, v in stats[name].items()}
                logger.info("%-17s: %s", name.title(), shares)
            logger.info("Outputs (%d):", len(outputs))
            for name, path in sorted(outputs.items()):
                logger.info("  %s", path)

        if not args.skip_landsat:
            from download_landsat import download_landsat
            from process_landsat import process_landsat
            logger.info("-" * 62)
            logger.info("STAGE 3/6 - Landsat 8/9: search, download, LST, heat classes")
            land_result = download_landsat(cfg, boundary)
            logger.info("Landsat scene %s (%s) acquired %s, cloud %.1f%%",
                        land_result.scene_id, land_result.provider, land_result.datetime,
                        land_result.cloud_cover if land_result.cloud_cover is not None else -1.0)
            land_outputs, land_stats = process_landsat(cfg, boundary)

            logger.info("-" * 62)
            logger.info("LANDSAT SUMMARY")
            logger.info("Mean / Max / Min LST : %.2f / %.2f / %.2f C",
                        land_stats["lst"]["mean"], land_stats["lst"]["max"],
                        land_stats["lst"]["min"])
            logger.info("Std LST             : %.2f C", land_stats["lst"]["std"])
            logger.info("Resolution          : %s m", land_stats["resolution_m"])
            logger.info("CRS                 : %s", land_stats["crs"])
            logger.info("Acquisition         : %s", land_stats["scene"].get("acquisition_date"))
            hot_share = land_stats["heat_classes"].get("Very Hot", {}).get("percent", 0.0)
            logger.info("Very Hot area       : %.2f%% of valid pixels", hot_share)
            logger.info("Outputs (%d):", len(land_outputs))
            for name, path in sorted(land_outputs.items()):
                logger.info("  %s", path)

        if not args.skip_aqi:
            from download_aqi import download_aqi
            from process_aqi import process_aqi
            logger.info("-" * 62)
            logger.info("STAGE 6/6 - Air quality: observations, interpolation, AQI")
            aqi_result = download_aqi(cfg, boundary)
            logger.info("AQI observations: %d rows from %s",
                        aqi_result.n_observations, aqi_result.sources)
            aqi_outputs, aqi_stats = process_aqi(cfg, boundary)

            logger.info("-" * 62)
            logger.info("AQI SUMMARY")
            logger.info("Sources             : %s", aqi_stats["source"].get("sources"))
            logger.info("Interpolation       : %s", aqi_stats["grid"]["interpolation_methods"])
            logger.info("AQI mean / max      : %.1f / %.1f",
                        aqi_stats["aqi"]["mean"], aqi_stats["aqi"]["max"])
            logger.info("AQI categories      : %s", aqi_stats["aqi_category_area_percent"])
            logger.info("Outputs (%d):", len(aqi_outputs))
            for name, path in sorted(aqi_outputs.items()):
                logger.info("  %s", path)

        if not args.skip_weather:
            from download_weather import download_weather
            from process_weather import process_weather
            logger.info("-" * 62)
            logger.info("STAGE 5/6 - NASA POWER: download weather, derive, plot, stats")
            weather_result = download_weather(cfg, boundary)
            logger.info("Weather centroid: %.4f N, %.4f E | period %s .. %s",
                        weather_result.centroid_lat, weather_result.centroid_lon,
                        weather_result.start_date, weather_result.end_date)
            weather_outputs, weather_stats = process_weather(cfg)

            logger.info("-" * 62)
            logger.info("WEATHER SUMMARY")
            t = weather_stats["daily_stats"]["T2M"]
            rh = weather_stats["daily_stats"]["RH2M"]
            pr = weather_stats["daily_stats"]["PRECTOTCORR"]
            logger.info("T2M  mean/max/min : %.2f / %.2f / %.2f C",
                        t["mean"], t["max"], t["min"])
            logger.info("RH2M mean         : %.2f %%", rh["mean"])
            logger.info("Rain mean         : %.2f mm/day", pr["mean"])
            logger.info("Heat index >35C   : %s days",
                        weather_stats["heat_index"]["days_above_35c"])
            logger.info("Outputs (%d):", len(weather_outputs))
            for name, path in sorted(weather_outputs.items()):
                logger.info("  %s", path)

        if not args.skip_dem:
            from download_dem import download_dem
            from process_dem import process_dem
            logger.info("-" * 62)
            logger.info("STAGE 4/6 - DEM: download, merge, clip, terrain derivatives")
            dem_result = download_dem(cfg, boundary)
            logger.info("DEM provider: %s (%d tile(s))", dem_result.provider,
                        len(dem_result.tiles))
            dem_outputs, dem_stats = process_dem(cfg, boundary)

            logger.info("-" * 62)
            logger.info("DEM SUMMARY")
            logger.info("Elevation min/max/mean : %.1f / %.1f / %.1f m",
                        dem_stats["elevation"]["min"], dem_stats["elevation"]["max"],
                        dem_stats["elevation"]["mean"])
            logger.info("Mean slope            : %.2f deg", dem_stats["slope"]["mean"])
            logger.info("Aspect distribution   : %s", dem_stats["aspect_distribution_percent"])
            logger.info("Resolution            : %s m", dem_stats["resolution_m"])
            logger.info("CRS                   : %s", dem_stats["crs"])
            logger.info("Contours              : %d lines (every %s m)",
                        dem_stats["contours"]["count"], dem_stats["contours"]["interval_m"])
            logger.info("Outputs (%d):", len(dem_outputs))
            for name, path in sorted(dem_outputs.items()):
                logger.info("  %s", path)

        logger.info("Pipeline finished successfully.")
        return 0

    except PipelineError as e:
        logger.error("Pipeline error: %s", e)
        return 1
    except KeyboardInterrupt:
        logger.warning("Interrupted by user. Run again to resume - completed files are reused.")
        return 130
    except Exception as e:  # pragma: no cover - unexpected failure
        logger.exception("Unexpected error: %s", e)
        return 2


if __name__ == "__main__":
    sys.exit(main())
