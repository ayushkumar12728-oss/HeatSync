"""Data catalogue endpoints: list layers and serve layer files."""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse

from backend.api.deps import get_catalog
from backend.config.settings import Settings, get_settings
from backend.schemas import LayerList
from backend.services.catalog import CONTENT_TYPES, DataCatalog

router = APIRouter(prefix="/api/data", tags=["data"])


@router.get("/layers", response_model=LayerList)
def list_layers(
    type: str | None = Query(
        None, description="raster | vector | timeseries | table | plot | model"
    ),
    category: str | None = None,
    catalog: DataCatalog = Depends(get_catalog),
) -> LayerList:
    """List every layer the pipeline produced."""
    layers = catalog.list_layers(type_filter=type, category=category)
    return LayerList(count=len(layers), categories=catalog.categories(), layers=layers)


@router.get("/layers/{name}")
def get_layer_file(name: str, catalog: DataCatalog = Depends(get_catalog)):
    """Download a layer file (GeoJSON / GeoTIFF / PNG / CSV)."""
    layer = catalog.get_layer(name)
    if layer is None or not layer.path.exists():
        raise HTTPException(status_code=404, detail=f"Unknown layer: {name}")
    media_type = CONTENT_TYPES.get(layer.path.suffix.lower(), "application/octet-stream")
    return FileResponse(
        layer.path,
        media_type=media_type,
        filename=layer.path.name,
        headers={
            "Cache-Control": "public, max-age=3600",
            "X-Layer-Type": layer.type,
            "X-Layer-Category": layer.category,
        },
    )


@router.get("/boundary")
def boundary(settings: Settings = Depends(get_settings)) -> JSONResponse:
    """Study-area boundary GeoJSON."""
    path = settings.boundary_geojson
    if not path.exists():
        raise HTTPException(status_code=404, detail="boundary.geojson not found")
    return JSONResponse(content=json.loads(path.read_text(encoding="utf-8")))


@router.get("/buildings/audit")
def buildings_audit(settings: Settings = Depends(get_settings)) -> JSONResponse:
    """Building geometry audit.

    Reports total buildings, valid/invalid geometry, height availability,
    and height source distribution. Used by the frontend to display honest
    building data statistics.
    """
    buildings_path = settings.project_root / "frontend" / "public" / "3d-layers" / "web_3d_buildings.geojson"
    if not buildings_path.exists():
        return JSONResponse(content={
            "available": False,
            "reason": f"Buildings file not found: {buildings_path}",
        })

    try:
        with open(buildings_path, encoding="utf-8") as fh:
            gj = json.load(fh)
        features = gj.get("features", [])
    except Exception as exc:
        return JSONResponse(content={
            "available": False,
            "reason": f"Could not load buildings: {exc}",
        })

    total = len(features)
    valid = 0
    invalid = 0
    height_available = 0
    height_source_counts = {}

    for feat in features:
        geom = feat.get("geometry", {})
        props = feat.get("properties", {})

        # Validate geometry
        if not geom or not geom.get("coordinates"):
            invalid += 1
            continue

        # Check polygon type
        geom_type = geom.get("type", "")
        if geom_type not in ("Polygon", "MultiPolygon"):
            invalid += 1
            continue

        valid += 1

        # Check height
        render_height = props.get("render_height_m")
        height = props.get("height_m")
        if render_height or height:
            height_available += 1

        height_source = props.get("height_source", "none")
        height_source_counts[height_source] = height_source_counts.get(height_source, 0) + 1

    return JSONResponse(content={
        "available": True,
        "total_buildings": total,
        "valid_buildings": valid,
        "invalid_buildings": invalid,
        "height_available": height_available,
        "height_source_distribution": height_source_counts,
        "render_rate_pct": round(valid / total * 100, 1) if total > 0 else 0,
    })
