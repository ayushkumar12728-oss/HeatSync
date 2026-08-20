"""
City-wide digital-twin endpoints (added for the 3D city upgrade)
================================================================
New, non-breaking endpoints that power the city-scale 3D digital twin UI:

    GET /api/city/point?lat=&lng=        -> location intelligence (nearest cell)
    GET /api/city/hotspots?limit=        -> hottest modelled cells
    GET /api/city/cooling-potential      -> model-derived intervention potential
    GET /api/city/cooling-potential/geojson
    GET /api/city/interventions          -> ranked cooling opportunities
    GET /api/city/intelligence           -> compact command-centre aggregates
    GET /api/city/explain?lat=&lng=      -> "why is this area hot?" factors
    GET /api/routing/heat-safe           -> fastest vs lower-heat-exposure route

Every response is derived from the real artifacts on disk (100 m feature grid,
per-cell XGBoost predictions, cached scenario results, global SHAP importance).
Nothing is fabricated: when an artifact is missing the endpoint reports it.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse

from backend.api.deps import get_city_data
from backend.services.city_data import CityDataService

router = APIRouter(prefix="/api/city", tags=["city"])


@router.get("/point")
def city_point(
    lat: Annotated[float, Query(ge=-90, le=90)],
    lng: Annotated[float, Query(ge=-180, le=180)],
    city: CityDataService = Depends(get_city_data),
) -> JSONResponse:
    """Location intelligence for any point (nearest real grid cell)."""
    try:
        return JSONResponse(content=city.point_profile(lat, lng))
    except FileNotFoundError as exc:
        return JSONResponse(
            status_code=503,
            content={"available": False, "message": str(exc)},
        )


@router.get("/hotspots")
def city_hotspots(
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
    city: CityDataService = Depends(get_city_data),
) -> JSONResponse:
    """Top-N hottest cells by the trained model's prediction."""
    try:
        return JSONResponse(content={
            "available": True,
            "count": limit,
            "label": "Hottest cells by predicted LST (XGBoost)",
            "hotspots": city.hotspots(limit=limit),
        })
    except FileNotFoundError as exc:
        return JSONResponse(
            status_code=503,
            content={"available": False, "message": str(exc)},
        )


@router.get("/cooling-potential")
def city_cooling_potential(
    city: CityDataService = Depends(get_city_data),
) -> JSONResponse:
    """Model-derived intervention potential per cell."""
    return JSONResponse(content=city.cooling_potential())


@router.get("/cooling-potential/geojson")
def city_cooling_potential_geojson(
    city: CityDataService = Depends(get_city_data),
) -> JSONResponse:
    """MapLibre-ready cooling-potential layer (model-derived)."""
    return JSONResponse(content=city.cooling_potential_geojson())


@router.get("/interventions")
def city_interventions(
    per_scenario: Annotated[int, Query(ge=1, le=50)] = 5,
    city: CityDataService = Depends(get_city_data),
) -> JSONResponse:
    """Ranked 'where should we intervene?' cooling opportunities."""
    return JSONResponse(content=city.interventions(per_scenario=per_scenario))


@router.get("/intelligence")
def city_intelligence(
    city: CityDataService = Depends(get_city_data),
) -> JSONResponse:
    """Compact city command-centre aggregates."""
    return JSONResponse(content=city.city_intelligence())


@router.get("/distribution")
def city_distribution(
    city: CityDataService = Depends(get_city_data),
) -> JSONResponse:
    """Real histograms across the full grid (analytics charts)."""
    try:
        return JSONResponse(content={
            "available": True,
            "distributions": city.distributions(),
        })
    except FileNotFoundError as exc:
        return JSONResponse(
            status_code=503,
            content={"available": False, "message": str(exc)},
        )


@router.get("/explain")
def city_explain(
    lat: Annotated[float, Query(ge=-90, le=90)],
    lng: Annotated[float, Query(ge=-180, le=180)],
    city: CityDataService = Depends(get_city_data),
) -> JSONResponse:
    """Data-backed 'why is this area hot?' factors."""
    try:
        return JSONResponse(content=city.explain(lat, lng))
    except FileNotFoundError as exc:
        return JSONResponse(
            status_code=503,
            content={"available": False, "message": str(exc)},
        )
