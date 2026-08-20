"""
Temporal thermal API endpoints
==============================
Provides real Landsat-based historical Land Surface Temperature data
for the Bhubaneswar Urban Digital Twin Time Machine.

Every response clearly identifies:
- The data source (Landsat Collection 2 Level-2)
- The metric (Land Surface Temperature, NOT air temperature)
- The processing method (USGS scale factors, QA_PIXEL cloud masking)
- Quality metadata (cloud cover, valid pixel fraction)

These are OBSERVED/DERIVED satellite values — never model predictions,
never fabricated data, never air temperature labelled as LST.

Endpoints:
    GET /api/temporal/thermal/dates       -> available observation dates
    GET /api/temporal/thermal             -> time series summary
    GET /api/temporal/thermal/compare     -> compare two dates
    GET /api/temporal/thermal/analytics   -> historical analytics
    GET /api/temporal/thermal/{date}      -> date-specific metadata
    GET /api/temporal/thermal/{date}/grid -> per-cell LST data
    GET /api/temporal/status              -> pipeline status
"""

from __future__ import annotations

from datetime import datetime as _dt

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse

from backend.api.deps import get_settings
from backend.config.settings import Settings
from backend.services.landsat_historical import (
    LandsatHistoricalService,
    get_landsat_service,
)

router = APIRouter(prefix="/api/temporal", tags=["temporal"])


def _service(settings: Settings = Depends(get_settings)) -> LandsatHistoricalService:
    """Get the Landsat historical service instance."""
    return get_landsat_service(settings)


# ------------------------------------------------------------------ #
# Static routes MUST come before /thermal/{date} to avoid path conflicts
# ------------------------------------------------------------------ #

# GET /api/temporal/thermal/dates — available observation dates
@router.get("/thermal/dates")
def thermal_dates(
    settings: Settings = Depends(get_settings),
    service: LandsatHistoricalService = Depends(_service),
) -> JSONResponse:
    """Return available historical Landsat LST observation dates.

    Returns ONLY actual Landsat acquisition dates — never fabricated daily dates.
    Landsat revisits the same area approximately every 16 days, so dates will
    be spaced accordingly.
    """
    result = service.get_available_dates()
    return JSONResponse(content=result)


# GET /api/temporal/thermal — time series summary
@router.get("/thermal")
def thermal_summary(
    start_date: str | None = Query(None, description="Filter start date (YYYY-MM-DD)"),
    end_date: str | None = Query(None, description="Filter end date (YYYY-MM-DD)"),
    aggregation: str | None = Query(None, description="Aggregation method (mean, median)"),
    settings: Settings = Depends(get_settings),
    service: LandsatHistoricalService = Depends(_service),
) -> JSONResponse:
    """Return the real historical LST time series.

    Each observation is a real Landsat acquisition — not interpolated,
    not generated, not fabricated.
    """
    result = service.get_observations_summary(
        start_date=start_date,
        end_date=end_date,
    )
    return JSONResponse(content=result)


# GET /api/temporal/thermal/compare — compare two dates
@router.get("/thermal/compare")
def thermal_compare(
    date_a: str = Query(..., description="First date (YYYY-MM-DD)"),
    date_b: str = Query(..., description="Second date (YYYY-MM-DD)"),
    settings: Settings = Depends(get_settings),
    service: LandsatHistoricalService = Depends(_service),
) -> JSONResponse:
    """Compare LST between two historical dates.

    Returns aggregate statistics and per-cell differences.
    Warming/cooling classification uses a 0.5°C threshold.
    """
    for d in (date_a, date_b):
        try:
            _dt.strptime(d, "%Y-%m-%d")
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid date format: {d}. Expected YYYY-MM-DD."
            )

    result = service.compare_dates(date_a, date_b)
    if result is None or result.get("status") == "unavailable":
        raise HTTPException(
            status_code=404,
            detail=result.get("reason", "Comparison unavailable.")
        )
    return JSONResponse(content=result)


# GET /api/temporal/thermal/analytics — historical analytics
@router.get("/thermal/analytics")
def thermal_analytics(
    settings: Settings = Depends(get_settings),
    service: LandsatHistoricalService = Depends(_service),
) -> JSONResponse:
    """Return historical thermal analytics.

    Includes trend data, observation count, hottest/coolest dates,
    mean historical LST, and seasonal comparison (when enough data exists).
    """
    result = service.get_analytics()
    return JSONResponse(content=result)


# GET /api/temporal/thermal/{date}/grid — per-cell LST data
# (must come before /thermal/{date} to match correctly)
@router.get("/thermal/{date}/grid")
def thermal_date_grid(
    date: str,
    settings: Settings = Depends(get_settings),
    service: LandsatHistoricalService = Depends(_service),
) -> JSONResponse:
    """Return per-cell LST data for a specific date.

    Returns GeoJSON with the existing prediction grid geometry and
    Landsat-derived LST values for each cell. Cells without valid
    satellite data are marked as unavailable.
    """
    try:
        _dt.strptime(date, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid date format: {date}. Expected YYYY-MM-DD."
        )

    result = service.get_grid_data(date)
    if result is None:
        raise HTTPException(
            status_code=404,
            detail=f"No grid data available for {date}."
        )
    return JSONResponse(content=result)


# GET /api/temporal/thermal/{date} — date-specific metadata
@router.get("/thermal/{date}")
def thermal_date_metadata(
    date: str,
    settings: Settings = Depends(get_settings),
    service: LandsatHistoricalService = Depends(_service),
) -> JSONResponse:
    """Return metadata for a specific historical LST observation.

    Includes acquisition date, scene ID, cloud cover, valid pixel percentage,
    and LST statistics.
    """
    try:
        _dt.strptime(date, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid date format: {date}. Expected YYYY-MM-DD."
        )

    result = service.get_observation_metadata(date)
    if result is None:
        raise HTTPException(
            status_code=404,
            detail=f"No Landsat observation available for {date}."
        )
    return JSONResponse(content=result)


# GET /api/temporal/status — pipeline status
@router.get("/status")
def temporal_status(
    settings: Settings = Depends(get_settings),
    service: LandsatHistoricalService = Depends(_service),
) -> JSONResponse:
    """Return the status of the historical LST pipeline."""
    result = service.get_status()
    return JSONResponse(content=result)
