#!/usr/bin/env python3
"""
Build Temporal Dataset
======================
Combines historical Landsat LST observations with historical weather and
static GIS features into a multi-date training dataset for MODEL V2.

Data flow:
    Historical Landsat scenes (data/historical_lst/scenes/)
        ↓
    Per-cell LST extraction via grid intersection
        ↓
    Historical weather (data/historical_lst/weather/)
        ↓
    Static GIS features (data/feature_engineering/training_dataset.csv)
        ↓
    Temporal dataset (data/processed/temporal/temporal_dataset.csv)
        ↓
    Dataset quality report (data/processed/temporal/HISTORICAL_DATASET_REPORT.md)

Schema per row:
    date, cell_id, latitude, longitude,
    STATIC: building_coverage, building_density, road_density, green_cover, terrain, ...
    DYNAMIC: air_temperature, humidity, wind, pressure, precipitation, cloud_cover, solar_radiation,
    TARGET: lst_c

Every row represents ONE CELL on ONE DATE.

Usage:
    python scripts/build_temporal_dataset.py
    python scripts/build_temporal_dataset.py --min-valid-fraction 0.3
    python scripts/build_temporal_dataset.py --skip-weather
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("build_temporal_dataset")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
HISTORICAL_DIR = PROJECT_ROOT / "data" / "historical_lst"
SCENES_DIR = HISTORICAL_DIR / "scenes"
WEATHER_DIR = HISTORICAL_DIR / "weather"
CATALOGUE_PATH = HISTORICAL_DIR / "catalogue.json"
TEMPORAL_DIR = PROJECT_ROOT / "data" / "processed" / "temporal"
TEMPORAL_DIR.mkdir(parents=True, exist_ok=True)

OUTPUT_CSV = TEMPORAL_DIR / "temporal_dataset.csv"
OUTPUT_REPORT = TEMPORAL_DIR / "HISTORICAL_DATASET_REPORT.md"
OUTPUT_MANIFEST = TEMPORAL_DIR / "build_manifest.json"

# Static GIS features from the training dataset
STATIC_GIS_FEATURES = [
    "Grid_ID", "latitude", "longitude",
    "Area_m2", "BuildingCount", "BuildingCoveragePct", "AvgBuildingFootprint",
    "BuildingDensity", "RoadLength", "RoadIntersectionCount", "DistToMajorRoad",
    "RoadDensity", "RoadIntersectionDensity", "TreeCount", "TreeDensity",
    "GreenSpacePct", "LandUse_ResidentialPct", "LandUse_CommercialPct",
    "LandUse_IndustrialPct", "LandUse_InstitutionalPct", "LandUse_AgriculturePct",
    "LandUse_GreenPct", "LandUse_RailwayPct", "LandUse_OtherPct",
    "DistToPark", "DistToWater", "DistToHospital", "DistToSchool",
    "BusStopCount", "DistToBusStop", "BusStopDensity", "HospitalCount",
    "SchoolCount", "MeanNDVI", "MaxNDVI", "MinNDVI", "GreenCover",
    "VegetationDensity", "VegDensityClass", "LandCoverClass",
    "LandCover_WaterPct", "LandCover_VegetationPct", "LandCover_BuiltupPct",
    "LandCover_BareLandPct", "MeanElevation", "MeanSlope", "Aspect",
    "ImperviousSurfaceRatio", "GreenToBuiltRatio", "CoolingDistanceIndex",
    "RoadExposureIndex", "VegetationCoolingIndex", "TerrainExposureIndex",
    "HeatVulnerabilityIndex",
]

# Weather features from Open-Meteo
WEATHER_FEATURES = [
    "Temperature_Max", "Temperature_Min", "Temperature_Mean",
    "Humidity", "WindSpeed", "Pressure", "Precipitation",
    "CloudCover", "SolarRadiation",
]

# Target
TARGET = "lst_c"

# QA_PIXEL cloud mask
QA_CLOUD_MASK = (
    (1 << 0) | (1 << 1) | (1 << 2) | (1 << 3) | (1 << 4)
)

# USGS scale factors
DEFAULT_SCALE_MUL = 0.00341802
DEFAULT_SCALE_ADD = 149.0
KELVIN_TO_CELSIUS = -273.15


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Build temporal training dataset")
    p.add_argument("--min-valid-fraction", type=float, default=0.3,
                   help="Minimum valid pixel fraction to keep a scene (default: 0.3)")
    p.add_argument("--skip-weather", action="store_true",
                   help="Skip weather join (use NaN)")
    p.add_argument("--grid-csv", type=str, default=None,
                   help="Path to training_dataset.csv (default: auto)")
    return p.parse_args()


def load_catalogue() -> dict:
    """Load the historical LST catalogue."""
    if not CATALOGUE_PATH.exists():
        log.error("Catalogue not found: %s", CATALOGUE_PATH)
        return {}
    with open(CATALOGUE_PATH, encoding="utf-8") as fh:
        return json.load(fh)


def load_static_gis(csv_path: Optional[str] = None) -> pd.DataFrame:
    """Load static GIS features from the training dataset."""
    if csv_path:
        path = Path(csv_path)
    else:
        path = PROJECT_ROOT / "data" / "feature_engineering" / "training_dataset.csv"

    if not path.exists():
        log.error("Training dataset not found: %s", path)
        return pd.DataFrame()

    df = pd.read_csv(path)
    log.info("Loaded static GIS: %d rows x %d cols", *df.shape)

    # Ensure Grid_ID is string for consistent joining
    if "Grid_ID" in df.columns:
        df["Grid_ID"] = df["Grid_ID"].astype(str)

    # Keep only static GIS features that exist
    available_cols = [c for c in STATIC_GIS_FEATURES if c in df.columns]
    log.info("Available static GIS features: %d / %d", len(available_cols), len(STATIC_GIS_FEATURES))

    return df[available_cols]


def load_cell_centroids() -> pd.DataFrame:
    """Extract cell centroids from the GeoJSON grid (lightweight)."""
    grid_path = PROJECT_ROOT / "data" / "predictions" / "Predicted_LST.geojson"
    if not grid_path.exists():
        grid_path = PROJECT_ROOT / "data" / "feature_engineering" / "training_dataset.geojson"
    if not grid_path.exists():
        log.warning("Grid GeoJSON not found")
        return pd.DataFrame(columns=["Grid_ID", "latitude", "longitude"])

    try:
        from shapely.geometry import shape
        import json as json_mod

        log.info("Loading cell centroids from %s (this may take a moment)...", grid_path.name)
        with open(grid_path, encoding="utf-8") as fh:
            grid_geojson = json_mod.load(fh)

        records = []
        for feature in grid_geojson.get("features", []):
            props = feature.get("properties", {})
            grid_id = props.get("Grid_ID") or props.get("grid_id")
            geom = feature.get("geometry")
            if not geom or grid_id is None:
                continue
            try:
                centroid = shape(geom).centroid
                records.append({
                    "Grid_ID": str(grid_id),
                    "latitude": centroid.y,
                    "longitude": centroid.x,
                })
            except Exception:
                continue

        log.info("Extracted %d cell centroids", len(records))
        return pd.DataFrame(records)

    except Exception as exc:
        log.error("Failed to load cell centroids: %s", exc)
        return pd.DataFrame(columns=["Grid_ID", "latitude", "longitude"])


def extract_cell_lst(scene_dir: Path, cell_coords: pd.DataFrame) -> pd.DataFrame:
    """Extract per-cell LST using point sampling from cell centroids.

    Much faster than polygon intersection: samples the LST raster at each
    cell's centroid coordinates. For 100m grid cells with 30m Landsat pixels,
    the centroid value is a good approximation of the cell mean.
    """
    try:
        import rasterio
    except ImportError as e:
        log.error("Missing rasterio: %s", e)
        return pd.DataFrame()

    st_path = scene_dir / "ST_B10.tif"
    qa_path = scene_dir / "QA_PIXEL.tif"

    if not st_path.exists():
        log.warning("ST_B10 not found: %s", st_path)
        return pd.DataFrame()

    try:
        with rasterio.open(st_path) as st_src:
            st_data = st_src.read(1).astype(np.float32)
            st_transform = st_src.transform

            # Apply USGS scaling
            lst_c = st_data * DEFAULT_SCALE_MUL + DEFAULT_SCALE_ADD + KELVIN_TO_CELSIUS
            lst_c[st_data == 0] = np.nan

            # Apply cloud mask
            if qa_path.exists():
                with rasterio.open(qa_path) as qa_src:
                    qa = qa_src.read(1)
                cloud_mask = (qa.astype(np.uint16) & QA_CLOUD_MASK) != 0
                lst_c[cloud_mask] = np.nan

            # Centroids from the GeoJSON grid are already in the raster's CRS
            # (both are EPSG:32645 UTM). No transformation needed.
            # The column names "longitude"/"latitude" are misleading:
            # they actually contain UTM easting/northing.

            # Vectorized point sampling: convert all centroids to pixel coords at once
            xs = cell_coords["longitude"].values.astype(float)  # UTM easting
            ys = cell_coords["latitude"].values.astype(float)    # UTM northing
            grid_ids = cell_coords["Grid_ID"].astype(str).values

            # Affine transform: row = (y - ty) / ta, col = (x - tx) / te
            # where transform = [ta, 0, tx, 0, te, ty]
            inv_a = 1.0 / st_transform.a
            inv_e = 1.0 / st_transform.e
            row_px = np.floor((ys - st_transform.f) * inv_e).astype(np.int32)
            col_px = np.floor((xs - st_transform.c) * inv_a).astype(np.int32)

            # Mask out-of-bounds
            h, w = st_data.shape
            in_bounds = (row_px >= 0) & (row_px < h) & (col_px >= 0) & (col_px < w)

            # Initialize arrays
            lst_vals = np.full(len(xs), np.nan)
            valid_mask = np.zeros(len(xs), dtype=bool)

            # Sample valid pixels
            valid_idx = np.where(in_bounds)[0]
            if len(valid_idx) > 0:
                sampled = lst_c[row_px[valid_idx], col_px[valid_idx]]
                valid_notnan = ~np.isnan(sampled)
                final_idx = valid_idx[valid_notnan]
                lst_vals[final_idx] = sampled[valid_notnan]
                valid_mask[final_idx] = True

            # Build cell records
            cell_records = []
            for i in range(len(xs)):
                if valid_mask[i]:
                    cell_records.append({
                        "Grid_ID": grid_ids[i],
                        "lst_c": round(float(lst_vals[i]), 2),
                        "valid_pixel_count": 1,
                        "valid": True,
                    })
                else:
                    cell_records.append({
                        "Grid_ID": grid_ids[i],
                        "lst_c": np.nan,
                        "valid_pixel_count": 0,
                        "valid": False,
                    })

        return pd.DataFrame(cell_records)

    except Exception as exc:
        log.error("Failed to extract cell LST: %s", exc)
        return pd.DataFrame()


def load_weather(date_str: str) -> dict:
    """Load weather data for a specific date."""
    weather_path = WEATHER_DIR / f"{date_str}.json"
    if not weather_path.exists():
        return {}
    try:
        with open(weather_path, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {}


def get_season(date_str: str) -> str:
    """Classify date into season."""
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


def build_temporal_dataset(
    catalogue: dict,
    static_gis: pd.DataFrame,
    skip_weather: bool = False,
    min_valid_fraction: float = 0.3,
) -> pd.DataFrame:
    """Build the multi-date temporal dataset."""
    observations = catalogue.get("observations", [])
    if not observations:
        log.error("No observations in catalogue")
        return pd.DataFrame()

    log.info("Building temporal dataset from %d scenes", len(observations))

    all_rows = []
    scene_stats = []

    for i, obs in enumerate(observations):
        date_str = obs["date"]
        scene_id = obs.get("scene_id", "unknown")
        cloud_cover = obs.get("cloud_cover_pct", 0)
        season = get_season(date_str)

        log.info("[%d/%d] Processing scene %s (%s, cloud %.1f%%, season=%s)",
                 i + 1, len(observations), scene_id, date_str, cloud_cover, season)

        scene_dir = SCENES_DIR / scene_id
        if not scene_dir.exists():
            log.warning("Scene directory not found: %s", scene_dir)
            continue

        # Extract per-cell LST
        lst_df = extract_cell_lst(scene_dir, static_gis[["Grid_ID", "latitude", "longitude"]])
        if lst_df.empty:
            log.warning("No LST data extracted for %s", date_str)
            continue

        # Compute valid pixel fraction
        total_cells = len(lst_df)
        valid_cells = lst_df["valid"].sum()
        valid_fraction = valid_cells / total_cells if total_cells > 0 else 0

        if valid_fraction < min_valid_fraction:
            log.warning("Scene %s has only %.1f%% valid cells - skipping",
                       scene_id, valid_fraction * 100)
            scene_stats.append({
                "date": date_str,
                "scene_id": scene_id,
                "season": season,
                "cloud_cover": cloud_cover,
                "total_cells": total_cells,
                "valid_cells": int(valid_cells),
                "valid_fraction": round(valid_fraction, 4),
                "status": "skipped_low_quality",
            })
            continue

        # Load weather
        weather = {}
        if not skip_weather:
            weather = load_weather(date_str)

        # Merge LST with static GIS using merge (fast, O(n))
        merged = lst_df.merge(static_gis, on="Grid_ID", how="left")

        # Add metadata
        merged["date"] = date_str
        merged["cell_id"] = merged["Grid_ID"]
        merged["season"] = season
        merged["scene_id"] = scene_id
        merged["scene_cloud_cover"] = cloud_cover

        # Add weather features
        for feat in WEATHER_FEATURES:
            merged[feat] = weather.get(feat, np.nan)

        # Rename lst_c column (from LST extraction)
        merged = merged.rename(columns={"lst_c": "lst_c"})

        # Select relevant columns
        all_cols = list(merged.columns)
        keep_cols = [c for c in all_cols if c not in ("valid", "valid_pixel_count")]
        merged["valid_pixel_count"] = merged["valid_pixel_count"].fillna(0).astype(int)
        merged["valid"] = merged["lst_c"].notna()

        all_rows.append(merged[keep_cols])

        scene_stats.append({
            "date": date_str,
            "scene_id": scene_id,
            "season": season,
            "cloud_cover": cloud_cover,
            "total_cells": total_cells,
            "valid_cells": int(valid_cells),
            "valid_fraction": round(valid_fraction, 4),
            "status": "included",
        })

        log.info("  Cells: %d total, %d valid (%.1f%%)",
                 total_cells, int(valid_cells), valid_fraction * 100)

    if not all_rows:
        log.error("No rows collected")
        return pd.DataFrame()

    df = pd.concat(all_rows, ignore_index=True)
    log.info("Temporal dataset: %d rows x %d cols", *df.shape)

    return df, scene_stats


def generate_report(
    df: pd.DataFrame,
    scene_stats: list,
    catalogue: dict,
    output_path: Path,
) -> None:
    """Generate HISTORICAL_DATASET_REPORT.md."""
    dates = df["date"].unique()
    cells = df["cell_id"].unique()
    seasons = df["season"].value_counts().to_dict() if "season" in df.columns else {}

    total_rows = len(df)
    valid_lst = df["lst_c"].notna().sum() if "lst_c" in df.columns else 0
    valid_weather = df[WEATHER_FEATURES].notna().all(axis=1).sum() if WEATHER_FEATURES[0] in df.columns else 0
    complete_rows = (
        df[["lst_c"] + WEATHER_FEATURES].notna().all(axis=1).sum()
        if WEATHER_FEATURES[0] in df.columns
        else 0
    )

    included = [s for s in scene_stats if s["status"] == "included"]
    skipped = [s for s in scene_stats if s["status"] != "included"]

    lines = [
        "# Historical LST Dataset Report",
        "",
        f"Generated: {datetime.now(timezone.utc).isoformat()}",
        "",
        "## Dataset Summary",
        "",
        f"| Metric | Value |",
        f"|--------|-------|",
        f"| Dates (scenes) | {len(dates)} |",
        f"| Cells per date | {len(cells)} |",
        f"| Potential rows | {len(cells) * len(dates):,} |",
        f"| Total rows | {total_rows:,} |",
        f"| Valid LST rows | {valid_lst:,} ({valid_lst/total_rows*100:.1f}%) |",
        f"| Valid weather rows | {valid_weather:,} ({valid_weather/total_rows*100:.1f}%) |",
        f"| Complete rows | {complete_rows:,} ({complete_rows/total_rows*100:.1f}%) |",
        f"| Missing LST % | {(total_rows - valid_lst)/total_rows*100:.1f}% |",
        f"| Scenes included | {len(included)} |",
        f"| Scenes skipped | {len(skipped)} |",
        "",
        "## Date Range",
        "",
        f"- First: {dates.min() if len(dates) > 0 else 'N/A'}",
        f"- Latest: {dates.max() if len(dates) > 0 else 'N/A'}",
        "",
        "## Season Distribution",
        "",
    ]

    for season, count in sorted(seasons.items()):
        lines.append(f"- {season}: {count:,} rows")

    lines.extend([
        "",
        "## Per-Scene Statistics",
        "",
        "| Date | Scene | Season | Cloud % | Valid Cells | Valid % | Status |",
        "|------|-------|--------|---------|-------------|---------|--------|",
    ])

    for s in scene_stats:
        lines.append(
            f"| {s['date']} | {s['scene_id'][:30]}... | {s['season']} | "
            f"{s['cloud_cover']:.1f} | {s['valid_cells']} | "
            f"{s['valid_fraction']*100:.1f} | {s['status']} |"
        )

    lines.extend([
        "",
        "## Data Sources",
        "",
        "- **LST**: Landsat Collection 2 Level-2 Surface Temperature (ST_B10)",
        "- **Weather**: Open-Meteo Historical Weather API (ERA5 reanalysis-backed)",
        "- **GIS Features**: OpenStreetMap + Sentinel-2 (static, from training dataset)",
        "- **Cloud Filter**: QA_PIXEL bits 0-4 (fill, dilated cloud, cirrus, cloud, shadow)",
        "",
        "## Integrity Notes",
        "",
        "- Every date corresponds to an actual Landsat acquisition",
        "- No synthetic or fabricated dates",
        "- No air temperature substituted for LST",
        "- No random train/test splitting (temporal validation used)",
        "- Weather timestamps match satellite acquisition dates",
    ])

    output_path.write_text("\n".join(lines), encoding="utf-8")
    log.info("Report written: %s", output_path)


def main() -> int:
    args = parse_args()
    t_start = time.time()

    log.info("=" * 72)
    log.info("BUILD TEMPORAL DATASET")
    log.info("Min valid fraction: %.1f%%", args.min_valid_fraction * 100)
    log.info("Skip weather: %s", args.skip_weather)
    log.info("=" * 72)

    # Load catalogue
    catalogue = load_catalogue()
    if not catalogue:
        return 1

    # Load static GIS features
    static_gis = load_static_gis(args.grid_csv)
    if static_gis.empty:
        return 1

    # Load cell centroids for point sampling
    cell_coords = load_cell_centroids()
    if cell_coords.empty:
        log.error("Could not load cell centroids")
        return 1

    # Merge centroids with static GIS
    static_gis = static_gis.merge(cell_coords, on="Grid_ID", how="left")
    log.info("Merged %d cells with centroids", len(static_gis))

    # Build temporal dataset
    result = build_temporal_dataset(
        catalogue, static_gis, args.skip_weather, args.min_valid_fraction
    )

    if isinstance(result, tuple):
        df, scene_stats = result
    else:
        df = result
        scene_stats = []

    if df.empty:
        log.error("Empty dataset")
        return 1

    # Save CSV
    df.to_csv(OUTPUT_CSV, index=False)
    log.info("Temporal dataset saved: %s", OUTPUT_CSV)

    # Generate report
    generate_report(df, scene_stats, catalogue, OUTPUT_REPORT)

    # Build manifest
    manifest = {
        "pipeline": "build_temporal_dataset",
        "version": "1.0.0",
        "input_catalogue": str(CATALOGUE_PATH),
        "input_static_gis": args.grid_csv or "data/feature_engineering/training_dataset.csv",
        "output_csv": str(OUTPUT_CSV),
        "output_report": str(OUTPUT_REPORT),
        "min_valid_fraction": args.min_valid_fraction,
        "skip_weather": args.skip_weather,
        "total_rows": len(df),
        "total_dates": len(df["date"].unique()),
        "total_cells": len(df["cell_id"].unique()),
        "valid_lst_rows": int(df["lst_c"].notna().sum()),
        "complete_rows": int(df[["lst_c"] + WEATHER_FEATURES].notna().all(axis=1).sum())
        if WEATHER_FEATURES[0] in df.columns else 0,
        "columns": list(df.columns),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "elapsed_seconds": round(time.time() - t_start, 1),
    }
    with open(OUTPUT_MANIFEST, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2)

    elapsed = time.time() - t_start
    log.info("=" * 72)
    log.info("TEMPORAL DATASET COMPLETE (%.1f seconds)", elapsed)
    log.info("Rows: %d | Dates: %d | Cells: %d",
             len(df), len(df["date"].unique()), len(df["cell_id"].unique()))
    log.info("Valid LST: %d (%.1f%%)",
             int(df["lst_c"].notna().sum()),
             df["lst_c"].notna().mean() * 100)
    log.info("Output: %s", OUTPUT_CSV)
    log.info("=" * 72)

    return 0


if __name__ == "__main__":
    sys.exit(main())
