"""
Thematic data monitoring endpoints
==================================
Reports which GIS / environmental datasets the pipeline actually produced on
disk. Every entry is derived from real files (via the data catalogue and the
settings paths) - nothing is assumed to exist. The frontend uses this to
decide which layers it may render and which it must show as unavailable.

    GET /api/monitoring/status   -> per-dataset availability report
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from backend.api.deps import get_catalog
from backend.config.settings import Settings, get_settings
from backend.services.catalog import DataCatalog

router = APIRouter(prefix="/api/monitoring", tags=["monitoring"])

# ---------------------------------------------------------------------- #
# Dataset registry: every thematic dataset the UI can show.
#   key       -> stable identifier used by the frontend
#   name      -> human-readable label
#   group     -> layer group in the UI (vegetation / heat / terrain / ...)
#   layer_keys-> catalogue layer names that count as "this dataset exists"
#   dirs      -> directories that are checked for any raster/vector file
# ---------------------------------------------------------------------- #
DATASETS = [
    {"key": "osm", "name": "OSM City Layers", "group": "city",
     "layer_keys": ["web_3d_buildings", "web_3d_roads", "web_3d_green_spaces",
                    "web_3d_water", "web_3d_natural_water_green"],
     "dirs": [], "source": "OpenStreetMap (processed for web)"},
    {"key": "ndvi", "name": "NDVI", "group": "vegetation",
     "layer_keys": [], "dirs": ["data/processed/ndvi"],
     "source": "Sentinel-2 Level-2A"},
    {"key": "green_cover", "name": "Green Cover", "group": "vegetation",
     "layer_keys": [], "dirs": ["data/processed/greencover"],
     "source": "Sentinel-2 Level-2A (NDVI > threshold)"},
    {"key": "vegetation_density", "name": "Vegetation Density", "group": "vegetation",
     "layer_keys": [], "dirs": ["data/processed/vegetation"],
     "source": "Sentinel-2 Level-2A (5 classes)"},
    {"key": "land_cover", "name": "Land Cover", "group": "land-cover",
     "layer_keys": [], "dirs": ["data/processed/landcover"],
     "source": "Sentinel-2 Level-2A (rule-based)"},
    {"key": "lst", "name": "Land Surface Temperature", "group": "heat",
     "layer_keys": [], "dirs": ["data/processed/lst"],
     "source": "Landsat 8/9 Collection-2 Level-2 (ST_B10)"},
    {"key": "heat_class", "name": "Heat Classification", "group": "heat",
     "layer_keys": [], "dirs": ["data/processed/heatmap"],
     "source": "Landsat LST (6 classes: Very Cool .. Very Hot)"},
    {"key": "elevation", "name": "Elevation (DEM)", "group": "terrain",
     "layer_keys": [], "dirs": ["data/processed/elevation", "data/processed/dem"],
     "source": "Copernicus DEM GLO-30 / SRTM"},
    {"key": "slope", "name": "Slope", "group": "terrain",
     "layer_keys": [], "dirs": ["data/processed/slope"], "source": "DEM derivative"},
    {"key": "aspect", "name": "Aspect", "group": "terrain",
     "layer_keys": [], "dirs": ["data/processed/aspect"], "source": "DEM derivative"},
    {"key": "hillshade", "name": "Hillshade", "group": "terrain",
     "layer_keys": [], "dirs": ["data/processed/hillshade"], "source": "DEM derivative"},
    {"key": "aqi", "name": "Air Quality (AQI)", "group": "air-quality",
     "layer_keys": [], "dirs": ["data/processed/aqi/rasters"],
     "source": "CPCB / OpenAQ / Sentinel-5P interpolation"},
    {"key": "weather", "name": "Weather (NASA POWER)", "group": "weather",
     "layer_keys": [], "dirs": ["data/processed/weather"],
     "source": "NASA POWER daily climatology"},
    {"key": "model", "name": "UHI Model", "group": "model",
     "layer_keys": ["predicted-lst", "predicted-lst-raster", "training-grid"],
     "dirs": [], "source": "Trained XGBoost (ai-engine)"},
]


def _find_files(dirs, settings: Settings) -> list[str]:
    """Return real files (relative paths) found under the given directories."""
    found: list[str] = []
    for d in dirs:
        root = settings.project_root / d
        if not root.exists():
            continue
        for p in sorted(root.rglob("*")):
            if p.is_file() and p.suffix.lower() in (
                ".tif", ".tiff", ".geojson", ".json", ".csv", ".png", ".nc",
            ) and not p.name.startswith("."):
                found.append(str(p.relative_to(settings.project_root)))
    return found


@router.get("/status")
def monitoring_status(
    settings: Settings = Depends(get_settings),
    catalog: DataCatalog = Depends(get_catalog),
) -> JSONResponse:
    """Report which thematic datasets are actually available on disk."""
    now = datetime.now(UTC)
    report: list[dict] = []

    for ds in DATASETS:
        # catalogue layers that exist for this dataset
        files: list[str] = []
        for key in ds["layer_keys"]:
            layer = catalog.get_layer(key)
            if layer is not None and layer.path.exists():
                files.append(str(layer.path.relative_to(settings.project_root)))

        # files found under the expected output directories
        files += _find_files(ds["dirs"], settings)
        files = sorted(set(files))

        # newest modification time across the dataset's files
        last_modified: str | None = None
        for f in files:
            p = settings.project_root / f
            if not p.exists():
                continue
            mtime = datetime.fromtimestamp(p.stat().st_mtime, tz=UTC)
            if last_modified is None or mtime > last_modified:
                last_modified = mtime

        available = len(files) > 0
        report.append({
            "key": ds["key"],
            "name": ds["name"],
            "group": ds["group"],
            "available": available,
            "status": "available" if available else "unavailable",
            "source": ds["source"],
            "file_count": len(files),
            "files": files,
            "last_modified": (
                last_modified.isoformat() if last_modified else None
            ),
        })

    return JSONResponse(content={
        "generated_at": now.isoformat(),
        "datasets": report,
        "summary": {
            "available": sum(1 for r in report if r["available"]),
            "unavailable": sum(1 for r in report if not r["available"]),
            "total": len(report),
        },
    })
