#!/usr/bin/env python3
"""
GIS data verification (Phase 9)
===============================
Reads every raster / vector dataset the pipeline claims to have produced and
reports REAL metadata from disk using rasterio (CRS, bounds, dimensions,
nodata, dtype, min/max) plus file size and modification time. Nothing is
assumed: if a file is missing it is reported ``unavailable``.

Usage::

    python scripts/verify_gis_data.py            # text report
    python scripts/verify_gis_data.py --json     # JSON report

The monitoring endpoint (``GET /api/monitoring/status``) already reports
filesystem availability; this script adds deep raster verification for audits.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# dataset key -> list of paths to verify (raster preferred, fallbacks allowed)
DATASETS: dict[str, list[str]] = {
    "ndvi": ["data/processed/ndvi/ndvi.tif"],
    "green_cover": ["data/processed/greencover/green_cover.tif"],
    "vegetation_density": ["data/processed/vegetation/vegetation_density.tif"],
    "land_cover": ["data/processed/landcover/landcover.tif"],
    "lst": ["data/processed/lst/LST.tif"],
    "heat_class": ["data/processed/heatmap/heat_classes.tif"],
    "elevation": ["data/processed/elevation/Elevation.tif",
                  "data/processed/dem/dem_clipped.tif"],
    "slope": ["data/processed/slope/Slope.tif"],
    "aspect": ["data/processed/aspect/Aspect.tif"],
    "hillshade": ["data/processed/hillshade/Hillshade.tif"],
    "aqi": ["data/processed/aqi/rasters/AQI.tif"],
    "aqi_co": ["data/processed/aqi/rasters/CO.tif"],
    "aqi_no2": ["data/processed/aqi/rasters/NO2.tif"],
    "aqi_o3": ["data/processed/aqi/rasters/O3.tif"],
    "aqi_pm25": ["data/processed/aqi/rasters/PM25.tif"],
    "aqi_pm10": ["data/processed/aqi/rasters/PM10.tif"],
    "aqi_so2": ["data/processed/aqi/rasters/SO2.tif"],
    "predicted_lst": ["data/predictions/Predicted_LST.tif"],
}

VECTOR_DATASETS: dict[str, list[str]] = {
    "osm_web_layers": [
        "data/raw/osm/layers/web_3d_buildings.geojson",
        "data/raw/osm/layers/web_3d_roads.geojson",
        "data/raw/osm/layers/web_3d_green_spaces.geojson",
        "data/raw/osm/layers/web_3d_water.geojson",
        "data/raw/osm/layers/web_3d_trees.geojson",
    ],
    "boundary": ["boundary.geojson"],
    "predicted_grid": ["data/predictions/Predicted_LST.geojson"],
    "training_grid": ["data/feature_engineering/training_dataset.geojson"],
}


def _raster_meta(path: Path) -> dict:
    """Read real raster metadata via rasterio (min/max via the first band)."""
    import rasterio

    with rasterio.open(path) as src:
        band = src.read(1, masked=True)
        nodata = src.nodata
        # masked array: compressed() drops masked (nodata/outside) cells
        valid = band.compressed()
        data_min = float(valid.min()) if valid.size else None
        data_max = float(valid.max()) if valid.size else None
        return {
            "crs": str(src.crs) if src.crs else None,
            "bounds": list(src.bounds),
            "width": src.width,
            "height": src.height,
            "dtype": str(src.dtypes[0]) if src.dtypes else None,
            "nodata": nodata,
            "min": data_min,
            "max": data_max,
            "bands": src.count,
        }


def _relative(path: Path) -> str:
    """Relative path string (safe for absolute/relative inputs)."""
    try:
        return str(path.resolve().relative_to(ROOT.resolve()))
    except ValueError:
        return str(path)


def _verify_raster(path: Path) -> dict:
    entry = {
        "path": _relative(path),
        "exists": path.exists(),
        "status": "available" if path.exists() else "unavailable",
    }
    if not path.exists():
        return entry
    st = path.stat()
    entry["size_bytes"] = st.st_size
    entry["modified_at"] = datetime.fromtimestamp(st.st_mtime, tz=UTC).isoformat()
    try:
        entry.update(_raster_meta(path))
    except Exception as exc:  # pragma: no cover - corrupt file path
        entry["status"] = "unreadable"
        entry["error"] = str(exc)
    return entry


def _verify_vector(path: Path) -> dict:
    entry = {
        "path": _relative(path),
        "exists": path.exists(),
        "status": "available" if path.exists() else "unavailable",
    }
    if not path.exists():
        return entry
    st = path.stat()
    entry["size_bytes"] = st.st_size
    entry["modified_at"] = datetime.fromtimestamp(st.st_mtime, tz=UTC).isoformat()
    try:
        import json as _json
        with open(path, encoding="utf-8") as fh:
            fc = _json.load(fh)
        entry["type"] = fc.get("type")
        entry["feature_count"] = len(fc.get("features", []))
    except Exception as exc:  # pragma: no cover
        entry["status"] = "unreadable"
        entry["error"] = str(exc)
    return entry


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify GIS datasets on disk")
    parser.add_argument("--json", action="store_true", help="emit JSON report")
    args = parser.parse_args()

    report: dict = {
        "generated_at": datetime.now(UTC).isoformat(),
        "rasters": {},
        "vectors": {},
        "summary": {"rasters_available": 0, "rasters_total": 0,
                    "vectors_available": 0, "vectors_total": 0},
    }

    for key, paths in DATASETS.items():
        # first existing path wins (fallback chain)
        result = None
        for p in paths:
            full = ROOT / p
            if full.exists():
                result = _verify_raster(full)
                break
        if result is None:
            result = _verify_raster(ROOT / paths[0])
        report["rasters"][key] = result

    for key, paths in VECTOR_DATASETS.items():
        results = [_verify_vector(ROOT / p) for p in paths]
        report["vectors"][key] = {
            "status": "available" if any(r["exists"] for r in results) else "unavailable",
            "files": results,
        }

    avail_r = sum(1 for v in report["rasters"].values()
                  if v.get("status") == "available")
    total_r = len(report["rasters"])
    avail_v = sum(1 for v in report["vectors"].values()
                  if v.get("status") == "available")
    total_v = len(report["vectors"])
    report["summary"] = {
        "rasters_available": avail_r, "rasters_total": total_r,
        "vectors_available": avail_v, "vectors_total": total_v,
    }

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"GIS verification report ({report['generated_at']})")
        print(f"Rasters: {avail_r}/{total_r} available | "
              f"Vectors: {avail_v}/{total_v} available")
        for key, entry in report["rasters"].items():
            status = entry.get("status")
            detail = ""
            if status == "available":
                detail = (f" crs={entry.get('crs')} {entry.get('width')}x"
                          f"{entry.get('height')} dtype={entry.get('dtype')} "
                          f"min={entry.get('min')} max={entry.get('max')}")
            print(f"  [{status:11s}] {key:16s} {detail}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
