"""
Unified Live Data API
=====================
Single-source-of-truth endpoints for all live data.

Every endpoint returns data from the same authoritative snapshot,
preventing the "different requests use different data versions" problem.

    GET  /api/live/snapshot       -> complete live snapshot
    GET  /api/live/stream         -> Server-Sent Events for real-time updates
    GET  /api/live/snapshot/debug -> snapshot debugging metadata
    GET  /api/live/weather        -> live weather from current snapshot
    GET  /api/live/air-quality    -> live AQI from current snapshot
    GET  /api/live/temperature    -> live air temperature from current snapshot
    GET  /api/live/status         -> data freshness status for all sources
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse, StreamingResponse

from backend.api.deps import get_serving
from backend.config.settings import Settings, get_settings
from backend.services.live_data_manager.snapshot import get_current_snapshot

log = logging.getLogger("backend.live")

router = APIRouter(prefix="/api/live", tags=["live-data"])

# SSE refresh interval in seconds — how often the server pushes new snapshots
SSE_REFRESH_INTERVAL = 60  # 1 minute


@router.get("/snapshot")
def live_snapshot(
    force: bool = False,
    settings: Settings = Depends(get_settings),
) -> JSONResponse:
    """Complete live data snapshot — one call, one version of truth.

    Returns weather, AQI, prediction, satellite status and data freshness
    from a single authoritative snapshot. All downstream consumers should
    use this endpoint (or the individual sub-endpoints which read from
    the same snapshot).

    Query params:
        force: If true, bypass cache TTL and create a fresh snapshot.
    """
    try:
        snapshot = get_current_snapshot(force_refresh=force)
    except Exception as exc:
        log.error("Failed to create live snapshot: %s", exc)
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "status": "snapshot_error",
                "message": str(exc),
            },
        )

    # Get prediction from the serving context
    prediction_data = None
    try:
        from backend.services.serving import ServingContext
        serving = ServingContext(settings)
        if serving.model_available:
            from backend.services.live_feature_pipeline import refresh_feature_pipeline
            grid = refresh_feature_pipeline(settings)
            pred = grid.get("prediction", {})
            if pred and pred.get("predicted_lst_c") is not None:
                prediction_data = {
                    "predicted_lst_c": round(pred["predicted_lst_c"], 3),
                    "model_version": pred.get("model_version"),
                    "features_used": pred.get("features_used"),
                    "generated_at": pred.get("generated_at"),
                    "status": grid.get("status", "unknown"),
                    "snapshot_id": snapshot.snapshot_id,
                }
    except Exception as exc:
        log.warning("Prediction from snapshot failed: %s", exc)

    response = {
        "success": True,
        "snapshot_id": snapshot.snapshot_id,
        "generated_at": snapshot.generated_at,
        "weather": _format_weather(snapshot.weather),
        "air_quality": _format_aqi(snapshot.air_quality),
        "prediction": prediction_data,
        "satellite": snapshot.satellite,
        "freshness": snapshot.freshness,
        "source_status": snapshot.source_status,
    }

    return JSONResponse(content=response)


@router.get("/weather")
def live_weather(
    settings: Settings = Depends(get_settings),
) -> JSONResponse:
    """Live weather from the current authoritative snapshot."""
    snapshot = get_current_snapshot()
    return JSONResponse(content={
        "success": True,
        "snapshot_id": snapshot.snapshot_id,
        "generated_at": snapshot.generated_at,
        "data": _format_weather(snapshot.weather),
        "freshness": snapshot.freshness.get("weather", {}),
        "source_status": snapshot.source_status.get("weather", "UNAVAILABLE"),
    })


@router.get("/air-quality")
def live_air_quality(
    settings: Settings = Depends(get_settings),
) -> JSONResponse:
    """Live AQI from the current authoritative snapshot."""
    snapshot = get_current_snapshot()
    return JSONResponse(content={
        "success": True,
        "snapshot_id": snapshot.snapshot_id,
        "generated_at": snapshot.generated_at,
        "data": _format_aqi(snapshot.air_quality),
        "freshness": snapshot.freshness.get("air_quality", {}),
        "source_status": snapshot.source_status.get("air_quality", "UNAVAILABLE"),
    })


@router.get("/temperature")
def live_temperature(
    settings: Settings = Depends(get_settings),
) -> JSONResponse:
    """Live air temperature from OpenWeather (NOT predicted LST).

    This endpoint clearly distinguishes between:
    - LIVE AIR TEMPERATURE (from OpenWeather weather station)
    - PREDICTED LAND SURFACE TEMPERATURE (from XGBoost model)

    The air temperature is a point measurement from a single weather
    station and should NOT be presented as a spatial field.
    """
    snapshot = get_current_snapshot()
    weather = snapshot.weather
    current = weather.get("current", {})

    temp = current.get("temperature")
    status = snapshot.source_status.get("weather", "UNAVAILABLE")

    return JSONResponse(content={
        "success": temp is not None,
        "snapshot_id": snapshot.snapshot_id,
        "generated_at": snapshot.generated_at,
        "air_temperature_c": temp,
        "feels_like_c": current.get("feels_like"),
        "humidity_pct": current.get("humidity"),
        "pressure_hpa": current.get("pressure"),
        "wind_speed_ms": current.get("wind_speed"),
        "wind_direction_deg": current.get("wind_direction"),
        "cloud_cover_pct": current.get("cloud_cover"),
        "source": "OpenWeather Current Weather API",
        "data_type": "LIVE",
        "note": "Point measurement from a single weather station — NOT spatially interpolated",
        "freshness": snapshot.freshness.get("weather", {}),
        "source_status": status,
    })


@router.get("/status")
def live_status(
    settings: Settings = Depends(get_settings),
) -> JSONResponse:
    """Data freshness status for all live sources.

    Returns the status of every data source with timestamps and freshness
    indicators. This is what the UI should use to display data freshness
    indicators (LIVE / LATEST_OBSERVATION / STATIC / CACHED / UNAVAILABLE).
    """
    snapshot = get_current_snapshot()

    # Compute age for each source
    now = datetime.now(UTC)
    statuses = {}

    for source_key in ("weather", "air_quality", "satellite", "gis", "terrain"):
        freshness = snapshot.freshness.get(source_key, {})
        status_val = snapshot.source_status.get(source_key, "UNAVAILABLE")
        observed = freshness.get("observed_at") or freshness.get("acquired") or freshness.get("last_updated")

        age_seconds = None
        if observed:
            try:
                obs_dt = datetime.fromisoformat(observed.replace("Z", "+00:00"))
                age_seconds = (now - obs_dt).total_seconds()
            except (ValueError, TypeError):
                pass

        # Determine staleness
        is_stale = False
        if age_seconds is not None:
            if source_key in ("weather", "air_quality") and age_seconds > 600:
                is_stale = True

        statuses[source_key] = {
            "status": status_val,
            "freshness": freshness.get("status", status_val),
            "observed_at": observed,
            "age_seconds": round(age_seconds, 1) if age_seconds is not None else None,
            "is_stale": is_stale,
            "source": freshness.get("source", ""),
        }

    return JSONResponse(content={
        "success": True,
        "snapshot_id": snapshot.snapshot_id,
        "generated_at": snapshot.generated_at,
        "statuses": statuses,
        "auto_refresh_enabled": True,
    })


@router.get("/snapshot/debug")
def snapshot_debug(
    settings: Settings = Depends(get_settings),
) -> JSONResponse:
    """Snapshot debugging endpoint.

    Returns comprehensive metadata about the current snapshot for debugging.
    Essential for verifying data consistency across the pipeline.
    """
    try:
        snapshot = get_current_snapshot()
    except Exception as exc:
        return JSONResponse(status_code=500, content={"error": str(exc)})

    # Try to get prediction metadata
    model_version = None
    feature_schema = None
    prediction_timestamp = None
    try:
        from backend.services.serving import ServingContext
        serving = ServingContext(settings)
        if serving.model_available:
            model_version = serving.model_version
            feature_schema = len(serving.features)
            from backend.services.live_feature_pipeline import refresh_feature_pipeline
            grid = refresh_feature_pipeline(settings)
            pred = grid.get("prediction", {})
            if pred:
                prediction_timestamp = pred.get("generated_at")
    except Exception:
        pass

    return JSONResponse(content={
        "success": True,
        "snapshot_id": snapshot.snapshot_id,
        "generated_at": snapshot.generated_at,
        "weather_timestamp": snapshot.freshness.get("weather", {}).get("observed_at"),
        "aqi_timestamp": snapshot.freshness.get("air_quality", {}).get("observed_at"),
        "satellite_timestamp": snapshot.freshness.get("satellite", {}).get("acquired"),
        "prediction_timestamp": prediction_timestamp,
        "model_version": model_version,
        "feature_schema": feature_schema,
        "source_status": snapshot.source_status,
        "freshness": snapshot.freshness,
    })


# ----------------------------------------------------------------------
# Server-Sent Events stream
# ----------------------------------------------------------------------
async def _sse_event_generator():
    """Yields SSE events with snapshot updates.

    The backend owns the authoritative refresh cycle. It polls live data
    sources at SSE_REFRESH_INTERVAL seconds and pushes updates to all
    connected clients. The frontend subscribes to this stream instead
    of independently polling.
    """
    last_snapshot_id = None
    while True:
        try:
            snapshot = get_current_snapshot(force_refresh=False)

            # Only send if snapshot changed (new data)
            if snapshot.snapshot_id != last_snapshot_id:
                last_snapshot_id = snapshot.snapshot_id

                payload = {
                    "type": "snapshot_update",
                    "snapshot_id": snapshot.snapshot_id,
                    "generated_at": snapshot.generated_at,
                    "sources": {
                        "weather": _format_weather(snapshot.weather),
                        "air_quality": _format_aqi(snapshot.air_quality),
                        "satellite": snapshot.satellite,
                    },
                    "freshness": snapshot.freshness,
                    "source_status": snapshot.source_status,
                }
                event_data = json.dumps(payload)
                yield f"event: snapshot_update\ndata: {event_data}\n\n"
            else:
                # Heartbeat to keep connection alive
                yield f": heartbeat {int(time.time())}\n\n"

        except Exception as exc:
            log.error("SSE stream error: %s", exc)
            error_payload = json.dumps({"type": "error", "message": str(exc)})
            yield f"event: error\ndata: {error_payload}\n\n"

        await asyncio.sleep(SSE_REFRESH_INTERVAL)


@router.get("/stream")
def live_stream():
    """Server-Sent Events stream for real-time snapshot updates.

    The backend owns the refresh cycle. The frontend subscribes to this
    stream and receives snapshot_update events whenever live data changes.

    Event types:
    - snapshot_update: new snapshot with weather, AQI, satellite data
    - error: an error occurred during data collection
    - heartbeat (as SSE comment): keep-alive
    """
    return StreamingResponse(
        _sse_event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


def _format_weather(weather: dict) -> dict:
    """Format weather data for API response."""
    if not weather or not weather.get("available"):
        return None
    current = weather.get("current", {})
    return {
        "temperature": current.get("temperature"),
        "feels_like": current.get("feels_like"),
        "humidity": current.get("humidity"),
        "pressure": current.get("pressure"),
        "wind_speed": current.get("wind_speed"),
        "wind_speed_kmh": current.get("wind_speed_kmh"),
        "wind_direction": current.get("wind_direction"),
        "cloud_cover": current.get("cloud_cover"),
        "visibility": current.get("visibility"),
        "precipitation": current.get("precipitation"),
        "weather_condition": current.get("weather_condition"),
        "weather_description": current.get("weather_description"),
        "observed_at": weather.get("observed_at"),
        "source": weather.get("source", "OpenWeather"),
        "is_day": current.get("is_day"),
    }


def _format_aqi(aqi: dict) -> dict:
    """Format AQI data for API response."""
    if not aqi or not aqi.get("available"):
        return None
    current = aqi.get("current", {})
    return {
        "aqi": current.get("aqi"),
        "aqi_label": current.get("aqi_label"),
        "aqi_scale": current.get("aqi_scale"),
        "pm25": current.get("pm2_5"),
        "pm10": current.get("pm10"),
        "no2": current.get("no2"),
        "o3": current.get("o3"),
        "so2": current.get("so2"),
        "co": current.get("co"),
        "nh3": current.get("nh3"),
        "observed_at": aqi.get("observed_at"),
        "source": aqi.get("source", "OpenWeather"),
        "note": "OpenWeather AQI index (1-5 scale, NOT US EPA or Indian CPCB AQI)",
    }
