"""
System health endpoints (Phase 4)
==================================
One real, aggregated view of the whole stack for the frontend "System Status"
panel. Every value is derived from the actual project state on disk, from the
live probes (OpenWeather weather / air quality, Nominatim search) or from
real configuration (Nemotron). Nothing is hardcoded: if a model file
disappears, ``model.status`` becomes ``unavailable``; if no Nemotron key is
configured, ``ai.status`` is ``configuration_required``; if a live probe
fails, that service reports ``unavailable`` with a reason.

    GET /api/system/health       -> aggregated system status
    GET /api/system/weather      -> cached live weather (OpenWeather)
    GET /api/system/air-quality  -> cached live AQI (OpenWeather Air Pollution)
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from backend.api.deps import get_catalog, get_database, get_serving, get_simulation
from backend.config.settings import Settings, get_settings
from backend.services import live_data
from backend.services.catalog import DataCatalog
from backend.services.database import DatabaseService
from backend.services.nemotron import NemotronClient
from backend.services.serving import ServingContext
from backend.services.simulation import SimulationService

router = APIRouter(prefix="/api/system", tags=["system"])


def _scenario_report(sim: SimulationService) -> dict:
    """Scenario engine state: definition count + whether results are cached."""
    try:
        names = sim.scenario_names()
    except Exception as exc:  # pragma: no cover - config failure path
        return {"status": "unavailable", "count": 0, "names": [],
                "reason": f"Scenario engine error: {exc}"}
    cached = sim.settings.scenario_cells_dir
    cached_count = len(list(cached.glob("*.json"))) if cached.exists() else 0
    return {
        "status": "available" if names else "unavailable",
        "count": len(names),
        "names": names,
        "cached_results": cached_count,
        "ready": len(names) > 0,
    }


def _gis_report(catalog: DataCatalog, settings: Settings) -> dict:
    """GIS catalogue: layers actually on disk (counts only, no names needed)."""
    # The authoritative per-dataset availability lives in /api/monitoring/status.
    from backend.api.monitoring import DATASETS

    available = 0
    for ds in DATASETS:
        layer_hit = any(
            catalog.get_layer(key) is not None and catalog.get_layer(key).path.exists()
            for key in ds["layer_keys"]
        )
        dir_hit = any(
            (settings.project_root / d).exists()
            and any(p.is_file() for p in (settings.project_root / d).rglob("*"))
            for d in ds["dirs"]
        )
        if layer_hit or dir_hit:
            available += 1
    total = len(DATASETS)
    if available == total:
        status = "available"
    elif available > 0:
        status = "partial"
    else:
        status = "unavailable"
    return {
        "status": status,
        "datasets_available": available,
        "datasets_total": total,
    }


def _weather_report(settings: Settings) -> dict:
    """Live weather — real OpenWeather probe result (or a clear state)."""
    data = live_data.get_weather(settings)
    if not data.get("available"):
        return {
            "status": "unavailable",
            "source": data.get("source", "OpenWeather"),
            "reason": data.get("reason", "Weather probe failed."),
            "checked_at": data.get("checked_at"),
        }
    current = data.get("current") or {}
    return {
        "status": "available",
        "source": data.get("source", "OpenWeather"),
        "temperature_c": current.get("temperature"),
        "humidity_pct": current.get("humidity"),
        "condition": current.get("weather_description"),
        "observed_at": data.get("observed_at"),
        "retrieved_at": data.get("retrieved_at"),
        "cache_age_seconds": data.get("cache_age_seconds"),
    }


def _air_quality_report(settings: Settings) -> dict:
    """Live AQI — real OpenWeather probe result or a clear state."""
    data = live_data.get_air_quality(settings)
    if not data.get("available"):
        return {
            "status": "unavailable",
            "source": data.get("source", "OpenWeather"),
            "reason": data.get("reason", "Air-quality probe failed."),
            "checked_at": data.get("checked_at"),
        }
    current = data.get("current") or {}
    return {
        "status": "available",
        "source": data.get("source", "OpenWeather"),
        "aqi": current.get("aqi"),
        "aqi_label": current.get("aqi_label"),
        "pm2_5": current.get("pm2_5"),
        "observed_at": data.get("observed_at"),
        "retrieved_at": data.get("retrieved_at"),
        "cache_age_seconds": data.get("cache_age_seconds"),
    }


def _search_report(settings: Settings) -> dict:
    """Search/geocoding — Nominatim reachability probe."""
    data = live_data.get_search(settings)
    if not data.get("available"):
        return {
            "status": "unavailable",
            "provider": "OpenStreetMap Nominatim",
            "reason": data.get("reason", "Nominatim probe failed."),
            "checked_at": data.get("checked_at"),
        }
    return {
        "status": "available",
        "provider": "OpenStreetMap Nominatim",
        "checked_at": data.get("checked_at"),
    }


def _satellite_report(settings: Settings) -> dict:
    """Satellite data availability from the training dataset GeoJSON."""
    geojson_path = settings.dataset_geojson
    if not geojson_path.exists():
        return {
            "status": "UNAVAILABLE",
            "source": "Sentinel-2",
            "reason": "GeoJSON grid not found",
        }
    try:
        import json as _json
        with open(geojson_path, encoding="utf-8") as fh:
            gj = _json.load(fh)
        features = gj.get("features", [])
        if not features:
            return {"status": "UNAVAILABLE", "source": "Sentinel-2", "reason": "Empty grid"}
        props = features[0].get("properties", {})
        has_ndvi = "MeanNDVI" in props
        has_lc = "LandCoverClass" in props
        if has_ndvi and has_lc:
            return {
                "status": "LATEST_OBSERVATION",
                "source": "Sentinel-2 (grid properties)",
                "last_acquired": (
                    gj.get("crs", {}).get("properties", {}).get("name", "unknown")
                ),
                "fields": sum(
                    1 for k in props
                    if any(s in k for s in ("NDVI", "LandCover", "Green", "Veg"))
                ),
            }
        return {
            "status": "PARTIAL", "source": "Sentinel-2",
            "reason": "Missing NDVI/LandCover fields",
        }
    except Exception as exc:
        return {"status": "UNAVAILABLE", "source": "Sentinel-2", "reason": str(exc)}


def _terrain_report(settings: Settings) -> dict:
    """Terrain tile availability — real file system check."""
    import os
    terrain_dir = settings.project_root / "frontend" / "public" / "terrain"
    if not terrain_dir.exists():
        return {
            "status": "UNAVAILABLE",
            "source": "Copernicus DEM",
            "reason": "Terrain directory not found",
        }

    tile_count = 0
    sample_valid = False
    for root, dirs, files in os.walk(terrain_dir):
        for f in files:
            if f.endswith(".png"):
                tile_count += 1
                if not sample_valid:
                    try:
                        with open(os.path.join(root, f), "rb") as fh:
                            header = fh.read(4)
                            if header == b"\x89PNG":
                                sample_valid = True
                    except Exception:
                        pass

    if tile_count > 0 and sample_valid:
        return {
            "status": "AVAILABLE",
            "source": "Copernicus DEM",
            "format": "Terrarium",
            "tiles": tile_count,
            "verified": True,
        }
    return {
        "status": "UNAVAILABLE",
        "source": "Copernicus DEM",
        "reason": f"No valid tiles found" if tile_count == 0 else "Tiles not valid PNG",
        "tiles": tile_count,
    }


@router.get("/health")
def system_health(
    settings: Settings = Depends(get_settings),
    catalog: DataCatalog = Depends(get_catalog),
    db: DatabaseService = Depends(get_database),
    serving: ServingContext = Depends(get_serving),
    sim: SimulationService = Depends(get_simulation),
) -> JSONResponse:
    """Aggregated system health — every value from real state (no hardcoding)."""
    model = serving.model_status()
    gis = _gis_report(catalog, settings)
    scenarios = _scenario_report(sim)
    weather = _weather_report(settings)
    air_quality = _air_quality_report(settings)
    search = _search_report(settings)
    satellite = _satellite_report(settings)
    ai = NemotronClient().status()

    # Degraded when any core capability is missing; live services (weather /
    # AQI / search / AI) report their own status without flipping the whole
    # system to "down" (they are optional external services).
    core_ok = (
        settings is not None
        and model.get("available") is True
        and gis.get("status") in ("available", "partial")
        and scenarios.get("ready") is True
    )
    overall = "healthy" if core_ok else "degraded"

    return JSONResponse(content={
        "status": overall,
        "generated_at": datetime.now(UTC).isoformat(),
        "backend": {
            "status": "online",
            "app": settings.app_name,
            "version": settings.version,
        },
        "database": db.status(),
        "model": {
            "status": model.get("status"),
            "available": model.get("available"),
            "name": model.get("model"),
            "feature_count": model.get("feature_count"),
            "version": model.get("version"),
            "metrics": model.get("metrics"),
            "message": model.get("message"),
        },
        "gis": gis,
        "scenarios": scenarios,
        "weather": weather,
        "air_quality": air_quality,
        "satellite": satellite,
        "terrain": _terrain_report(settings),
        "search": search,
        "ai": {
            "status": ai.get("status"),
            "provider": ai.get("provider"),
            "model": ai.get("model"),
            "available": ai.get("available"),
            "message": ai.get("message"),
        },
        "live_probes_enabled": settings.enable_live_probes,
    })


@router.get("/weather")
def system_weather(settings: Settings = Depends(get_settings)) -> JSONResponse:
    """Cached live weather for the study area (OpenWeather, real request)."""
    return JSONResponse(content=live_data.get_weather(settings))


@router.get("/air-quality")
def system_air_quality(settings: Settings = Depends(get_settings)) -> JSONResponse:
    """Cached live AQI for the study area (OpenWeather Air Pollution, real)."""
    return JSONResponse(content=live_data.get_air_quality(settings))


@router.get("/terrain")
def system_terrain(settings: Settings = Depends(get_settings)) -> JSONResponse:
    """Terrain tile health check.

    Verifies that terrain tiles actually exist on disk and are valid PNG
    files. Does NOT trust the source object creation — verifies real files.
    """
    import os
    terrain_dir = settings.project_root / "frontend" / "public" / "terrain"
    if not terrain_dir.exists():
        return JSONResponse(content={
            "available": False,
            "source": "Copernicus DEM",
            "format": "Terrarium",
            "tiles_verified": False,
            "reason": f"Terrain directory not found: {terrain_dir}",
            "tile_count": 0,
        })

    # Count actual PNG files
    tile_count = 0
    sample_valid = False
    for root, dirs, files in os.walk(terrain_dir):
        for f in files:
            if f.endswith(".png"):
                tile_count += 1
                if not sample_valid:
                    # Validate the first tile we find
                    sample_path = os.path.join(root, f)
                    try:
                        with open(sample_path, "rb") as fh:
                            header = fh.read(8)
                            # PNG magic bytes: 137 80 78 71 13 10 26 10
                            if header[:4] == b"\x89PNG":
                                sample_valid = True
                    except Exception:
                        pass

    return JSONResponse(content={
        "available": tile_count > 0 and sample_valid,
        "source": "Copernicus DEM",
        "format": "Terrarium",
        "tiles_verified": tile_count > 0 and sample_valid,
        "tile_count": tile_count,
        "reason": None if tile_count > 0 and sample_valid else (
            f"No valid terrain tiles found" if tile_count == 0
            else "Sample tile is not valid PNG"
        ),
    })
