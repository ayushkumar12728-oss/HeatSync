"""Prediction endpoints: model info, live inference, precomputed outputs."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, JSONResponse

from backend.api.deps import get_serving
from backend.config.settings import Settings, get_settings
from backend.schemas import PredictionResult, PredictRequest
from backend.services.serving import ServingContext

log = logging.getLogger("backend.prediction")

router = APIRouter(prefix="/api/prediction", tags=["prediction"])

# Project heat-class temperature breaks (gis-engine HeatClassConfig.fixed_breaks_c)
# used ONLY to label predictions with a class - visualization thresholds.
UHI_CLASS_BREAKS = [("Very Cool", 20.0), ("Cool", 25.0), ("Moderate", 30.0),
                    ("Warm", 35.0), ("Hot", 40.0)]


def uhi_class(celsius: float) -> str:
    """Classify a predicted LST using the project's fixed heat breaks."""
    for label, threshold in UHI_CLASS_BREAKS:
        if celsius < threshold:
            return label
    return "Very Hot"


@router.get("/model")
def model_info(serving: ServingContext = Depends(get_serving)) -> JSONResponse:
    """Describe the deployed model and its feature schema (graceful when absent)."""
    return JSONResponse(content=serving.model_status())


@router.get("/features")
def feature_schema(serving: ServingContext = Depends(get_serving)) -> dict:
    """Feature list with the two categorical encodings used at training time."""
    pre = serving.preprocessor
    return {
        "count": len(serving.features),
        "features": serving.features,
        "categorical_columns": pre.categorical_cols,
        "encodings": {
            # original value -> training code
            col: {str(label): code for label, code in mapping.items()}
            for col, mapping in pre.encodings.items()
        },
        "imputation": pre.fill_values,
    }


@router.get("/heat/current")
def current_heat(serving: ServingContext = Depends(get_serving)) -> JSONResponse:
    """Current predicted LST from the live feature pipeline.

    Returns the XGBoost-predicted Land Surface Temperature for the current
    feature grid constructed from live OpenWeather, AQI, satellite and GIS data.

    Response includes:
    - predicted_lst_c: Current predicted LST in °C
    - source: XGBoost model
    - feature provenance: source and timestamp for each feature
    - data freshness: when weather, AQI and satellite were observed
    - status: availability status
    - snapshot_id: links to authoritative live snapshot
    """
    if not serving.model_available:
        return JSONResponse(
            status_code=503,
            content={
                "success": False,
                "status": "model_unavailable",
                "message": "Trained model artifact is not available.",
                "required": str(serving.settings.model_pkl),
            },
        )

    try:
        prediction = serving.current_prediction
        if prediction is None:
            return JSONResponse(
                status_code=503,
                content={
                    "success": False,
                    "status": "prediction_unavailable",
                    "message": "Could not compute current prediction from live data.",
                },
            )

        # Build provenance-enriched response
        grid = serving.current_feature_grid
        prediction_lst = round(prediction["predicted_lst_c"], 3)

        # Get snapshot ID from the live data manager
        snapshot_id = None
        try:
            from backend.services.live_data_manager.snapshot import get_current_snapshot
            snap = get_current_snapshot()
            snapshot_id = snap.snapshot_id
        except Exception:
            pass

        # Generate data freshness information
        feature_age = grid.get("feature_age", {})
        predicted = {
            "predicted_lst_c": prediction_lst,
            "uhi_class": uhi_class(prediction_lst),
            "source": prediction.get("source", "XGBoost"),
            "model_version": prediction.get("model_version"),
            "features_used": prediction.get("features_used", len(serving.features)),
            "features_status": prediction.get("features_status", "modelled from current data"),
            "generated_at": prediction.get("generated_at"),
            "data_freshness": {
                "weather": feature_age.get("weather", "unknown"),
                "aqi": feature_age.get("aqi", "unknown"),
                "satellite": feature_age.get("satellite", "unknown"),
            },
        }

        # Determine pipeline status for honest reporting
        pipeline_status = grid.get("status", "unknown")
        missing_sources = grid.get("missing_sources", [])
        fallback_used = grid.get("fallback_used", False)

        response = {
            "success": True,
            "predicted_lst_c": prediction_lst,
            "prediction": predicted,
            "status": pipeline_status,
            "missing_sources": missing_sources,
            "fallback_used": fallback_used,
            "snapshot_id": snapshot_id,
        }

        # 200 when we have a valid prediction, even if partial
        return JSONResponse(content=response)

    except Exception as exc:
        log.error("Current heat prediction failed: %s", exc)
        return JSONResponse(
            status_code=500,
            content={"success": False, "status": "prediction_error", "message": str(exc)},
        )


@router.get("/heat/current/grid")
def current_heat_grid(
    serving: ServingContext = Depends(get_serving),
) -> JSONResponse:
    """Return the current 53,802-cell predicted LST grid.

    Uses ServingContext's cached fast-path instead of constructing a new
    SimulationService for every request. This avoids rebuilding the full
    simulation pipeline and greatly reduces Render memory/CPU usage.
    """

    if not serving.model_available:
        return JSONResponse(
            status_code=503,
            content={
                "success": False,
                "status": "model_unavailable",
                "message": "Trained model artifact is not available.",
                "required": str(serving.settings.model_pkl),
            },
        )

    try:
        # IMPORTANT:
        # Do NOT create SimulationService here.
        # ServingContext already has the optimized/cached grid predictor.
        result = serving.get_current_grid_predictions_fast()

        generated_at = datetime.now(UTC).isoformat()

        snapshot_id = None
        try:
            from backend.services.live_data_manager.snapshot import (
                get_current_snapshot,
            )

            snapshot_id = get_current_snapshot().snapshot_id
        except Exception as exc:
            log.warning("Could not obtain snapshot ID: %s", exc)

        return JSONResponse(
            content={
                "success": True,
                "status": "success",
                "data_source": "current",
                "cells": result["count"],
                "generated_at": generated_at,
                "model_version": serving.model_version,
                "feature_count": len(serving.features),
                "summary": result["summary"],
                "predictions": result["cells"],
                "snapshot_id": snapshot_id,
            }
        )

    except Exception as exc:
        log.exception("Current heat grid prediction failed")

        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "status": "prediction_error",
                "message": str(exc),
            },
        )


@router.get("/heat/current/debug")
def current_heat_debug(serving: ServingContext = Depends(get_serving)) -> JSONResponse:
    """Diagnostic endpoint: current feature pipeline with full provenance.

    Returns per-feature provenance (value, source, status), data source
    availability, feature count verification and pipeline health.

    Status values for each feature:
    - LIVE: real-time observation (weather, AQI)
    - LATEST_OBSERVATION: latest available satellite data
    - STATIC_GIS: static GIS/terrain data
    - DERIVED: computed from other features
    - UNAVAILABLE: data not available
    """
    if not serving.model_available:
        return JSONResponse(
            status_code=503,
            content={
                "success": False,
                "status": "model_unavailable",
                "message": "Trained model artifact is not available.",
            },
        )

    try:
        from backend.services.live_feature_pipeline import get_pipeline

        pipeline = get_pipeline(serving.settings)
        grid = pipeline.refresh()

        # Build per-feature provenance
        feature_values = grid.get("feature_values", {})
        features = {}
        for feat_name, prov_tuple in feature_values.items():
            # prov_tuple = (normalized_value, source, status, timestamp)
            features[feat_name] = {
                "value": prov_tuple[0] if prov_tuple else None,
                "source": prov_tuple[1] if prov_tuple else None,
                "status": prov_tuple[2] if prov_tuple else "UNAVAILABLE",
                "acquired_at": prov_tuple[3] if prov_tuple else None,
            }

        # Data source availability
        feature_age = grid.get("feature_age", {})
        data_sources = {
            "weather": {
                "status": (
                    "LIVE" if feature_age.get("weather") not in (None, "never")
                    else "UNAVAILABLE"
                ),
                "last_observed": feature_age.get("weather"),
            },
            "air_quality": {
                "status": (
                    "LIVE" if feature_age.get("aqi") not in (None, "never")
                    else "UNAVAILABLE"
                ),
                "last_observed": feature_age.get("aqi"),
            },
            "satellite": {
                "status": (
                    "LATEST_OBSERVATION"
                    if feature_age.get("satellite") not in (None, "never")
                    else "UNAVAILABLE"
                ),
                "last_acquired": feature_age.get("satellite"),
            },
        }

        # Feature count verification
        expected = len(serving.features)
        actual = len(features)

        return JSONResponse(content={
            "success": True,
            "timestamp": datetime.now(UTC).isoformat(),
            "grid_cells": 53802,
            "model": {
                "type": type(serving.model).__name__,
                "version": serving.model_version,
                "feature_count": expected,
            },
            "features": features,
            "feature_count": {
                "expected": expected,
                "actual": actual,
                "match": expected == actual,
            },
            "data_sources": data_sources,
            "prediction": grid.get("prediction"),
            "pipeline_status": grid.get("status", "unknown"),
        })

    except Exception as exc:
        log.error("Debug endpoint failed: %s", exc)
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "status": "debug_error",
                "message": str(exc),
            },
        )


@router.post("/predict")
def predict(payload: PredictRequest,
            serving: ServingContext = Depends(get_serving)) -> JSONResponse:
    """Predict LST (°C) for one feature row or a batch of rows.

    Returns a structured ``model_unavailable`` response (HTTP 503) when the
    trained model artifact is missing, and ``invalid_request`` (HTTP 400) for
    missing/invalid features. Never fabricates a prediction.
    """
    rows: list[dict] = []
    if payload.features is not None:
        rows.append(payload.features)
    if payload.batch is not None:
        rows.extend(payload.batch)
    if not rows:
        raise HTTPException(status_code=400, detail="Provide 'features' or 'batch'")

    if not serving.model_available:
        return JSONResponse(
            status_code=503,
            content={
                "success": False,
                "status": "model_unavailable",
                "message": "Trained model artifact is not available.",
                "required": str(serving.settings.model_pkl),
            },
        )

    # Phase 11: strict input validation — reject missing/unknown features,
    # NaN/Infinity, wrong types and wrong feature count with HTTP 400.
    try:
        serving.validate_rows_strict(rows)
    except ValueError as exc:
        return JSONResponse(
            status_code=400,
            content={"success": False, "status": "invalid_request", "message": str(exc)},
        )

    try:
        preds = serving.predict_rows(rows)
    except ValueError as exc:
        return JSONResponse(
            status_code=400,
            content={"success": False, "status": "invalid_request", "message": str(exc)},
        )

    grid_ids = [
        str(payload.features.get("Grid_ID")) if payload.features is not None else None
    ] if len(rows) == 1 else [None] * len(rows)

    return JSONResponse(content={
        "success": True,
        "count": len(preds),
        "model": type(serving.model).__name__,
        "model_version": serving.model_version,
        "predictions": [
            PredictionResult(
                grid_id=grid_ids[i] if i < len(grid_ids) else None,
                predicted_lst_c=round(p, 3),
                uhi_class=uhi_class(p),
            ).model_dump()
            for i, p in enumerate(preds)
        ],
    })


@router.get("/metrics")
def metrics(settings: Settings = Depends(get_settings)) -> JSONResponse:
    """The pipeline's evaluation metrics (metrics.json)."""
    path = settings.metrics_json
    if not path.exists():
        raise HTTPException(status_code=404, detail="metrics.json not found")
    return JSONResponse(content=json.loads(path.read_text(encoding="utf-8")))


@router.get("/predictions")
def predictions_csv(settings: Settings = Depends(get_settings)) -> FileResponse:
    """Test-set predictions table (predictions.csv)."""
    path = settings.predictions_csv
    if not path.exists():
        raise HTTPException(status_code=404, detail="predictions.csv not found")
    return FileResponse(path, media_type="text/csv", filename="predictions.csv")


@router.get("/heat")
def heat_geojson(settings: Settings = Depends(get_settings)) -> FileResponse:
    """Full-grid predicted LST as GeoJSON (grid polygons + Predicted_LST)."""
    path = settings.predicted_geojson
    if not path.exists():
        raise HTTPException(status_code=404, detail="Predicted_LST.geojson not found")
    return FileResponse(path, media_type="application/geo+json",
                        filename="Predicted_LST.geojson",
                        headers={"Cache-Control": "public, max-age=3600"})


@router.get("/heat/raster")
def heat_raster(settings: Settings = Depends(get_settings)) -> FileResponse:
    """Predicted LST GeoTIFF (100 m, UTM 45N)."""
    path = settings.predicted_tif
    if not path.exists():
        raise HTTPException(status_code=404, detail="Predicted_LST.tif not found")
    return FileResponse(path, media_type="image/tiff", filename="Predicted_LST.tif",
                        headers={"Cache-Control": "public, max-age=3600"})


@router.get("/heat/preview")
def heat_preview(settings: Settings = Depends(get_settings)) -> FileResponse:
    """Predicted LST map preview (PNG)."""
    path = settings.predicted_png
    if not path.exists():
        raise HTTPException(status_code=404, detail="Predicted_LST.png not found")
    return FileResponse(path, media_type="image/png", filename="Predicted_LST.png",
                        headers={"Cache-Control": "public, max-age=3600"})
