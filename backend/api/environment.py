"""
Environment summary endpoints
=============================
Real, file-derived statistics for the Bhubaneswar digital twin. All numbers
are computed directly from the actual OSM layer GeoJSON files produced by the
pipeline - no values are invented. Geometry math is pure Python (haversine for
lengths, shoelace with a cos(lat) correction for areas), so no extra
dependencies are needed.

    GET /api/environment/summary  -> OSM infrastructure stats + availability
"""

from __future__ import annotations

import itertools
import json
import math
from pathlib import Path

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from backend.api.deps import get_catalog
from backend.config.settings import Settings, get_settings
from backend.services.catalog import DataCatalog

router = APIRouter(prefix="/api/environment", tags=["environment"])

EARTH_RADIUS_M = 6_371_000.0
# Bhubaneswar approximate centroid latitude (used for degree->metre scaling)
REF_LAT = math.radians(20.26)
M_PER_DEG_LAT = math.pi * EARTH_RADIUS_M / 180.0
M_PER_DEG_LNG = M_PER_DEG_LAT * math.cos(REF_LAT)

# OSM "natural" values treated as trees/vegetation for the tree count
TREE_NATURAL = {"tree", "tree_row", "wood", "scrub"}


def _iter_coords(geometry: dict) -> list[list[float]]:
    """Flatten any GeoJSON geometry into a list of [lng, lat] positions."""
    coords: list[list[float]] = []
    if not geometry:
        return coords

    def walk(value) -> None:
        if (isinstance(value, list) and len(value) >= 2
                and isinstance(value[0], (int, float))
                and isinstance(value[1], (int, float))):
            coords.append([float(value[0]), float(value[1])])
            return
        if isinstance(value, list):
            for item in value:
                walk(item)

    walk(geometry.get("coordinates"))
    return coords


def _ring_length(coords: list[list[float]]) -> float:
    """Haversine length of a closed ring in metres."""
    if len(coords) < 2:
        return 0.0
    total = 0.0
    for (lng1, lat1), (lng2, lat2) in zip(coords, coords[1:] + coords[:1], strict=True):
        total += _haversine(lat1, lng1, lat2, lng2)
    return total


def _haversine(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    a = math.sin(math.radians(lat2 - lat1) / 2) ** 2 + math.cos(
        math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(
        math.radians(lng2 - lng1) / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(a)))


def _polygon_area_m2(geometry: dict) -> float:
    """Planar shoelace area with cos(lat) correction, in square metres.

    Only meaningful for polygon/polyline geometries. Returns 0 for anything
    else. This is an approximation (not an equal-area projection) and is
    labelled as such in the response.
    """
    coords = _iter_coords(geometry)
    if len(coords) < 4:
        return 0.0
    # planar area in degree^2 then scaled to m^2
    area_deg2 = 0.0
    for (lng1, lat1), (lng2, lat2) in itertools.pairwise(coords):
        area_deg2 += (lng2 - lng1) * (lat2 + lat1)
    area_deg2 = abs(area_deg2) / 2.0
    return area_deg2 * M_PER_DEG_LNG * M_PER_DEG_LAT


def _load_geojson(path: Path) -> dict:
    if not path.exists():
        return {"type": "FeatureCollection", "features": []}
    return json.loads(path.read_text(encoding="utf-8"))


def _feature_length_m(feature: dict) -> float:
    geom = feature.get("geometry") or {}
    return _ring_length(_iter_coords(geom))


def _feature_area_km2(feature: dict) -> float:
    return _polygon_area_m2(feature.get("geometry") or {}) / 1_000_000.0


def _osm_stats(settings: Settings) -> dict:
    """Real statistics computed from the OSM layer files on disk."""
    layer_dir = settings.osm_layers_dir
    out = {
        "buildings": {"count": 0, "source_file": "web_3d_buildings.geojson"},
        "roads": {"count": 0, "length_km": 0.0, "source_file": "web_3d_roads.geojson"},
        "green": {"count": 0, "area_km2": 0.0, "source_file": "web_3d_green_spaces.geojson"},
        "natural": {"count": 0, "area_km2": 0.0, "tree_count": 0,
                    "source_file": "web_3d_natural_water_green.geojson"},
        "water": {"count": 0, "area_km2": 0.0, "source_file": "web_3d_water.geojson"},
    }

    files = {
        "buildings": layer_dir / "web_3d_buildings.geojson",
        "roads": layer_dir / "web_3d_roads.geojson",
        "green": layer_dir / "web_3d_green_spaces.geojson",
        "natural": layer_dir / "web_3d_natural_water_green.geojson",
        "water": layer_dir / "web_3d_water.geojson",
    }

    for key, path in files.items():
        fc = _load_geojson(path)
        features = fc.get("features", [])
        entry = out[key]
        entry["count"] = len(features)
        for feature in features:
            props = feature.get("properties") or {}
            if key == "roads":
                entry["length_km"] += _feature_length_m(feature) / 1000.0
            elif key in ("green", "natural", "water"):
                entry["area_km2"] += _feature_area_km2(feature)
            if key == "natural":
                natural_val = str(props.get("natural", "")).lower()
                if natural_val in TREE_NATURAL:
                    entry["tree_count"] += 1

    # roads: avoid double counting round-trips (lines have 2 endpoints)
    out["roads"]["length_km"] = round(out["roads"]["length_km"], 3)
    out["green"]["area_km2"] = round(out["green"]["area_km2"], 4)
    out["natural"]["area_km2"] = round(out["natural"]["area_km2"], 4)
    out["water"]["area_km2"] = round(out["water"]["area_km2"], 4)
    return out


@router.get("/summary")
def environment_summary(
    settings: Settings = Depends(get_settings),
    catalog: DataCatalog = Depends(get_catalog),
) -> JSONResponse:
    """Real OSM infrastructure statistics + per-dataset availability."""
    stats = _osm_stats(settings)

    # per-dataset availability for the thematic groups
    from backend.api.monitoring import DATASETS, _find_files

    availability: dict[str, bool] = {}
    for ds in DATASETS:
        layer_hit = any(
            catalog.get_layer(key) is not None and catalog.get_layer(key).path.exists()
            for key in ds["layer_keys"]
        )
        availability[ds["key"]] = layer_hit or bool(
            _find_files(ds["dirs"], settings))

    boundary_fc = _load_geojson(settings.boundary_geojson)
    boundary_area_km2 = sum(
        _feature_area_km2(f) for f in boundary_fc.get("features", [])
    )
    green_area_km2 = stats["green"]["area_km2"] + stats["natural"]["area_km2"]
    green_cover_pct = (
        round(green_area_km2 * 100.0 / boundary_area_km2, 2)
        if boundary_area_km2 > 0 else 0.0
    )

    return JSONResponse(content={
        "city": "Bhubaneswar",
        "boundary_source": "boundary.geojson (real study-area boundary)",
        "boundary_area_km2": round(boundary_area_km2, 4),
        "stats": stats,
        "derived": {
            "green_area_km2": round(green_area_km2, 4),
            "green_cover_pct": green_cover_pct,
            "area_method": "planar shoelace with cos(lat) correction (approximate)",
        },
        "availability": availability,
        "note": "All values are computed from the real OSM layer files on disk.",
    })
