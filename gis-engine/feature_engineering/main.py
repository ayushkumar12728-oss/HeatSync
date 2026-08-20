"""
GIS Feature Engineering Engine - Urban Heat Island training dataset
===================================================================
Merges every processed dataset (OSM vectors, Sentinel-2 rasters, Landsat
LST, DEM terrain, air quality, NASA POWER weather) into a single unified
machine-learning table on a regular 100 m grid:

    python main.py                       # run the full pipeline
    python main.py --grid-size 200       # coarser grid
    python main.py --acquisition-date 2026-05-16   # explicit weather join date
    python main.py --no-parallel         # single-process (debugging)
    python main.py --skip-quality        # skip reports/plots/baseline

Outputs (in data/feature_engineering/):
    training_dataset.csv, training_dataset_normalized.csv,
    training_dataset.geojson, feature_statistics.json,
    correlation_matrix.csv, feature_importance_baseline.csv,
    missing_value_report.json, quality_report.json, plots/*.png

Exit codes: 0 success, 1 pipeline error, 2 unexpected error, 130 Ctrl-C.
"""

from __future__ import annotations

import argparse
import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from config import Config

logger = logging.getLogger("feature_engineering.main")


class PipelineError(Exception):
    """Raised for expected, user-facing pipeline failures."""


def setup_logging(cfg: Config) -> None:
    cfg.paths.ensure()
    level = getattr(logging, cfg.log_level.upper(), logging.INFO)
    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(fmt)
    root.addHandler(console)

    log_file = cfg.paths.output / "feature_engineering.log"
    fh = RotatingFileHandler(log_file, maxBytes=5 << 20, backupCount=2,
                             encoding="utf-8")
    fh.setFormatter(fmt)
    root.addHandler(fh)
    logger.info("Logging to %s", log_file)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="main.py",
        description="GIS feature engineering for Urban Heat Island modelling "
                    "(Bhubaneswar digital twin)",
    )
    p.add_argument("--grid-size", type=float, default=None,
                   help="grid cell size in metres (default 100)")
    p.add_argument("--acquisition-date", type=str, default=None,
                   help="weather join date YYYY-MM-DD (default: from LST "
                        "statistics JSON)")
    p.add_argument("--no-parallel", action="store_true",
                   help="run single-process (no process pool)")
    p.add_argument("--skip-quality", action="store_true",
                   help="skip reports, baseline importance and plots")
    p.add_argument("--log-level", default=None,
                   choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    return p.parse_args()


def main() -> int:
    args = parse_args()
    cfg = Config.from_env()
    if args.grid_size is not None:
        cfg.grid.cell_size_m = args.grid_size
    if args.no_parallel:
        cfg.n_jobs = 1
    if args.log_level is not None:
        cfg.log_level = args.log_level

    setup_logging(cfg)

    logger.info("=" * 62)
    logger.info("GIS FEATURE ENGINEERING - UHI training dataset")
    logger.info("Grid size      : %g m", cfg.grid.cell_size_m)
    logger.info("Working CRS    : EPSG:%d", cfg.grid.target_epsg)
    logger.info("Parallel jobs  : %d", cfg.n_jobs)
    logger.info("=" * 62)

    try:
        from merge_features import build_merged_features
        from quality_checks import run_quality_checks

        gdf, cleaning = build_merged_features(
            cfg,
            acquisition_date=args.acquisition_date,
            grid_size_m=args.grid_size,
        )

        if args.skip_quality:
            logger.info("STEP 7 skipped (--skip-quality)")
            return 0

        logger.info("-" * 62)
        logger.info("STEP 7 - Final dataset, reports & visualisations")
        summary = run_quality_checks(gdf, cfg, cleaning)

        logger.info("-" * 62)
        logger.info("PIPELINE COMPLETE")
        logger.info("Rows x columns : %d x %d", summary["rows"], summary["columns"])
        logger.info("Importance     : %s", summary["importance_method"])
        logger.info("Top predictors : %s", summary["top_predictors"])
        logger.info("Outputs        :")
        for path in sorted(cfg.paths.output.rglob("*")):
            if path.is_file():
                logger.info("  %s", path)
        logger.info("Feature engineering finished successfully.")
        return 0

    except PipelineError as exc:
        logger.error("Pipeline error: %s", exc)
        return 1
    except KeyboardInterrupt:
        logger.warning("Interrupted by user.")
        return 130
    except Exception as exc:  # noqa: BLE001 - unexpected failure
        logger.exception("Unexpected error: %s", exc)
        return 2


if __name__ == "__main__":
    sys.exit(main())
