"""
Heat-safe routing endpoints
===========================
Grid-level lower-heat-exposure routing on the real 100 m model lattice.

    GET /api/routing/heat-safe?start_lat=&start_lng=&end_lat=&end_lng=

Returns a FASTEST route and a COOLEST (lower-heat-exposure) route with
distance, walking-time estimate, average/maximum predicted LST and the route
geometry. Deliberately labelled an estimate, never a medical/safety claim.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse

from backend.api.deps import get_city_data
from backend.services.city_data import CityDataService

router = APIRouter(prefix="/api/routing", tags=["routing"])


@router.get("/heat-safe")
def heat_safe_route(
    start_lat: Annotated[float, Query(ge=-90, le=90)],
    start_lng: Annotated[float, Query(ge=-180, le=180)],
    end_lat: Annotated[float, Query(ge=-90, le=90)],
    end_lng: Annotated[float, Query(ge=-180, le=180)],
    city: CityDataService = Depends(get_city_data),
) -> JSONResponse:
    """Fastest vs lower-heat-exposure route between two points."""
    try:
        return JSONResponse(content=city.route(start_lat, start_lng, end_lat, end_lng))
    except (FileNotFoundError, RuntimeError) as exc:
        return JSONResponse(
            status_code=503,
            content={"available": False, "message": str(exc)},
        )
