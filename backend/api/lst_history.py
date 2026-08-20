"""
LST History & Model V2 API Endpoints
=====================================
Provides endpoints for:
    - Historical LST time series (Time Machine)
    - Historical LST for specific dates
    - Model V2 information and metrics
    - Current vs historical comparison
    - Latest satellite observation metadata

Endpoints:
    GET /api/lst/history                 -> list available historical dates
    GET /api/lst/history/{date}          -> LST grid data for a specific date
    GET /api/lst/observations/latest     -> latest satellite observation metadata
    GET /api/model/v2/info               -> Model V2 information
    GET /api/model/v2/metrics            -> Model V2 evaluation metrics
    GET /api/model/v2/compare            -> V1 vs V2 comparison
    GET /api/lst/current-vs-historical   -> current modelled vs historical observed

These endpoints clearly distinguish:
    OBSERVED LST: satellite acquisition date
    MODELLED LST: model inference time
"""
from __future__ import annotations

import json
import logging
from datetime import datetime as _dt
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse

from backend.api.deps import get_settings
from backend.config.settings import Settings

log = logging.getLogger("backend.lst_history")

router = APIRouter(prefix="/api", tags=["lst-history"])


# ------------------------------------------------------------------ #
# Helpers
# ------------------------------------------------------------------ #

def _load_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _historical_dir(settings: Settings) -> Path:
    return settings.historical_lst_dir


def _registry_v2(settings: Settings) -> Path:
    return settings.model_v2_dir


# ------------------------------------------------------------------ #
# GET /api/lst/history — available historical dates
# ------------------------------------------------------------------ #

@router.get("/lst/history")
def lst_history(
    settings: Settings = Depends(get_settings),
) -> JSONResponse:
    """List available historical Landsat LST observation dates.

    Returns ONLY actual Landsat acquisition dates — never fabricated daily dates.
    Landsat revisits the same area approximately every 16 days.
    """
    hdir = _historical_dir(settings)
    catalogue = _load_json(hdir / "catalogue.json")

    if not catalogue:
        return JSONResponse(content={
            "status": "unavailable",
            "reason": "Historical LST catalogue not found. Run download_historical_lst.py first.",
            "dates": [],
            "observation_count": 0,
        })

    observations = catalogue.get("observations", [])
    dates = [obs["date"] for obs in observations]

    # Build per-date metadata
    date_info = []
    for obs in observations:
        date_info.append({
            "date": obs["date"],
            "scene_id": obs.get("scene_id", "unknown"),
            "cloud_cover_pct": obs.get("cloud_cover_pct", 0),
            "season": obs.get("season", "unknown"),
            "valid_pixel_fraction": obs.get("valid_pixel_fraction", 0),
            "mean_lst": obs.get("lst_stats", {}).get("mean_lst_c"),
            "min_lst": obs.get("lst_stats", {}).get("min_lst_c"),
            "max_lst": obs.get("lst_stats", {}).get("max_lst_c"),
            "source": "Landsat Collection 2 Level-2",
            "resolution_m": 30,
        })

    return JSONResponse(content={
        "status": "available",
        "source": catalogue.get("source", "Landsat Collection 2 Level-2"),
        "location": catalogue.get("location", "Bhubaneswar"),
        "resolution_m": catalogue.get("resolution_m", 30),
        "dates": dates,
        "date_info": date_info,
        "first_date": catalogue.get("first_date"),
        "latest_date": catalogue.get("latest_date"),
        "observation_count": len(dates),
        "seasons": catalogue.get("seasons", {}),
    })


# ------------------------------------------------------------------ #
# GET /api/lst/history/{date} — LST grid data for a specific date
# ------------------------------------------------------------------ #

@router.get("/lst/history/{date}")
def lst_history_date(
    date: str,
    settings: Settings = Depends(get_settings),
) -> JSONResponse:
    """Return historical LST grid data for a specific Landsat acquisition date.

    Returns GeoJSON with the prediction grid geometry and Landsat-derived LST
    values for each cell. Cells without valid satellite data are marked.
    """
    try:
        _dt.strptime(date, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid date format: {date}. Expected YYYY-MM-DD.",
        )

    # Check if date exists in catalogue
    hdir = _historical_dir(settings)
    catalogue = _load_json(hdir / "catalogue.json")
    if not catalogue:
        raise HTTPException(status_code=404, detail="Historical LST catalogue not found.")

    observation = None
    for obs in catalogue.get("observations", []):
        if obs["date"] == date:
            observation = obs
            break

    if not observation:
        raise HTTPException(
            status_code=404,
            detail=f"No Landsat observation available for {date}.",
        )

    # Try to load grid data from cache
    grid_cache = hdir / "grid" / f"grid_{date}.json"
    grid_data = _load_json(grid_cache)

    if not grid_data:
        # Build response without grid data
        grid_data = {
            "status": "metadata_only",
            "date": date,
            "scene_id": observation.get("scene_id"),
            "source": observation.get("source", "Landsat Collection 2 Level-2"),
            "resolution_m": observation.get("resolution", 30),
            "cloud_cover_pct": observation.get("cloud_cover_pct", 0),
            "valid_pixel_fraction": observation.get("valid_pixel_fraction", 0),
            "lst_stats": observation.get("lst_stats", {}),
            "note": "Grid-level data not yet generated. Run build_temporal_dataset.py first.",
        }

    return JSONResponse(content=grid_data)


# ------------------------------------------------------------------ #
# GET /api/lst/observations/latest — latest satellite observation
# ------------------------------------------------------------------ #

@router.get("/lst/observations/latest")
def lst_latest_observation(
    settings: Settings = Depends(get_settings),
) -> JSONResponse:
    """Return metadata for the latest Landsat satellite observation.

    This is NOT live data — it's the most recent satellite acquisition.
    Landsat revisits approximately every 16 days.
    """
    hdir = _historical_dir(settings)
    catalogue = _load_json(hdir / "catalogue.json")

    if not catalogue or not catalogue.get("observations"):
        return JSONResponse(content={
            "status": "unavailable",
            "reason": "No Landsat observations available.",
        })

    latest = catalogue["observations"][-1]

    return JSONResponse(content={
        "status": "available",
        "observation_type": "SATELLITE_OBSERVATION",
        "note": "This is the latest satellite observation, not a live measurement.",
        "date": latest["date"],
        "scene_id": latest.get("scene_id"),
        "source": "Landsat Collection 2 Level-2 Surface Temperature",
        "resolution_m": 30,
        "cloud_cover_pct": latest.get("cloud_cover_pct", 0),
        "valid_pixel_fraction": latest.get("valid_pixel_fraction", 0),
        "lst_stats": latest.get("lst_stats", {}),
        "season": latest.get("season", "unknown"),
    })


# ------------------------------------------------------------------ #
# GET /api/model/v2/info — Model V2 information
# ------------------------------------------------------------------ #

@router.get("/model/v2/info")
def model_v2_info(
    settings: Settings = Depends(get_settings),
) -> JSONResponse:
    """Return Model V2 (temporal thermal model) information."""
    v2_dir = _registry_v2(settings)

    schema = _load_json(v2_dir / "feature_schema_v2.json")
    metrics = _load_json(v2_dir / "metrics_v2.json")
    model_exists = (v2_dir / "model_v2.joblib").exists()

    if not schema and not metrics:
        return JSONResponse(content={
            "status": "unavailable",
            "reason": "Model V2 not trained yet. Run train_lst_v2.py first.",
            "model_version": "v2",
            "model_type": "XGBRegressor (temporal thermal model)",
            "available": False,
        })

    return JSONResponse(content={
        "status": "available" if model_exists else "partial",
        "model_version": "v2",
        "model_type": "XGBRegressor",
        "model_class": "temporal_thermal_model",
        "description": (
            "Multi-date temporal model trained on historical Landsat LST, "
            "weather, and static GIS features. Uses chronological train/val/test splits."
        ),
        "available": model_exists,
        "feature_count": schema.get("feature_count", 0) if schema else None,
        "features": schema.get("features", []) if schema else [],
        "categorical_columns": schema.get("categorical_columns", []) if schema else [],
        "weather_features": schema.get("weather_features", []) if schema else [],
        "training_dates": schema.get("training_dates", []) if schema else [],
        "validation_dates": schema.get("validation_dates", []) if schema else [],
        "test_dates": schema.get("test_dates", []) if schema else [],
        "test_metrics": metrics.get("test_metrics", {}) if metrics else {},
        "cv_summary": metrics.get("cv_summary", {}) if metrics else {},
        "temporal_validation": "chronological splits (no random shuffling)",
        "data_sources": {
            "lst": "Landsat Collection 2 Level-2 Surface Temperature",
            "weather": "Open-Meteo Historical Weather API (ERA5 reanalysis-backed)",
            "gis": "OpenStreetMap + Sentinel-2 (static spatial features)",
        },
    })


# ------------------------------------------------------------------ #
# GET /api/model/v2/metrics — Model V2 evaluation metrics
# ------------------------------------------------------------------ #

@router.get("/model/v2/metrics")
def model_v2_metrics(
    settings: Settings = Depends(get_settings),
) -> JSONResponse:
    """Return Model V2 evaluation metrics including per-season breakdown."""
    v2_dir = _registry_v2(settings)
    metrics = _load_json(v2_dir / "metrics_v2.json")

    if not metrics:
        return JSONResponse(content={
            "status": "unavailable",
            "reason": "Model V2 metrics not found. Run train_lst_v2.py first.",
        })

    return JSONResponse(content={
        "status": "available",
        "model_version": "v2",
        "train_metrics": metrics.get("train_metrics", {}),
        "val_metrics": metrics.get("val_metrics", {}),
        "test_metrics": metrics.get("test_metrics", {}),
        "cv_summary": metrics.get("cv_summary", {}),
        "seasonal_test_metrics": metrics.get("seasonal_test_metrics", {}),
        "train_rows": metrics.get("train_rows"),
        "val_rows": metrics.get("val_rows"),
        "test_rows": metrics.get("test_rows"),
        "feature_count": metrics.get("feature_count"),
        "train_dates": metrics.get("train_dates", []),
        "val_dates": metrics.get("val_dates", []),
        "test_dates": metrics.get("test_dates", []),
        "generated_at": metrics.get("generated_at"),
    })


# ------------------------------------------------------------------ #
# GET /api/model/v2/compare — V1 vs V2 comparison
# ------------------------------------------------------------------ #

@router.get("/model/v2/compare")
def model_v2_compare(
    settings: Settings = Depends(get_settings),
) -> JSONResponse:
    """Compare Model V1 (spatial baseline) vs Model V2 (temporal model)."""
    # V1 metrics
    v1_metrics = _load_json(settings.metrics_json)

    # V2 metrics
    v2_dir = _registry_v2(settings)
    v2_metrics = _load_json(v2_dir / "metrics_v2.json")

    v1_test = v1_metrics.get("test_metrics", {}) if v1_metrics else {}
    v2_test = v2_metrics.get("test_metrics", {}) if v2_metrics else {}

    # Compute improvements
    improvements = {}
    for metric in ["RMSE", "MAE"]:
        v1_val = v1_test.get(metric)
        v2_val = v2_test.get(metric)
        if v1_val is not None and v2_val is not None:
            improvements[metric] = {
                "v1": round(v1_val, 5),
                "v2": round(v2_val, 5),
                "improvement": round(v1_val - v2_val, 5),
                "improvement_pct": round((v1_val - v2_val) / v1_val * 100, 2) if v1_val != 0 else 0,
            }

    v1_r2 = v1_test.get("R2")
    v2_r2 = v2_test.get("R2")
    if v1_r2 is not None and v2_r2 is not None:
        improvements["R2"] = {
            "v1": round(v1_r2, 5),
            "v2": round(v2_r2, 5),
            "improvement": round(v2_r2 - v1_r2, 5),
        }

    # Determine recommendation
    v2_better = v2_test.get("RMSE", float("inf")) < v1_test.get("RMSE", float("inf")) if v1_test else False

    return JSONResponse(content={
        "status": "available",
        "v1": {
            "model_version": "v1",
            "model_class": "spatial_baseline",
            "description": "Single-date spatial XGBoost model (random train/test split)",
            "test_metrics": v1_test,
        },
        "v2": {
            "model_version": "v2",
            "model_class": "temporal_thermal_model",
            "description": "Multi-date temporal XGBoost model (chronological splits)",
            "test_metrics": v2_test,
            "seasonal_metrics": v2_metrics.get("seasonal_test_metrics", {}) if v2_metrics else {},
        },
        "improvements": improvements,
        "recommendation": (
            "DEPLOY_V2" if v2_better else "KEEP_V1"
        ),
        "recommendation_reason": (
            "V2 has lower test RMSE than V1" if v2_better
            else "V2 does not outperform V1 on test set — keep V1 as production"
        ),
    })


# ------------------------------------------------------------------ #
# GET /api/lst/current-vs-historical — current modelled vs historical
# ------------------------------------------------------------------ #

@router.get("/lst/current-vs-historical")
def current_vs_historical(
    settings: Settings = Depends(get_settings),
) -> JSONResponse:
    """Compare current modelled LST with latest historical observed LST."""
    hdir = _historical_dir(settings)
    catalogue = _load_json(hdir / "catalogue.json")

    # Latest observation
    latest_obs = None
    if catalogue and catalogue.get("observations"):
        latest = catalogue["observations"][-1]
        latest_obs = {
            "type": "SATELLITE_OBSERVED_LST",
            "date": latest["date"],
            "scene_id": latest.get("scene_id"),
            "source": "Landsat Collection 2 Level-2",
            "resolution_m": 30,
            "cloud_cover_pct": latest.get("cloud_cover_pct", 0),
            "lst_stats": latest.get("lst_stats", {}),
            "note": "Actual satellite observation — not a model prediction",
        }

    # Current modelled prediction (from V1 or V2)
    current_pred = None
    try:
        from backend.services.serving import ServingContext
        serving = ServingContext(settings)
        if serving.model_available:
            pred = serving.current_prediction
            if pred:
                current_pred = {
                    "type": "CURRENT_MODELLED_LST",
                    "predicted_lst_c": pred.get("predicted_lst_c"),
                    "model_version": pred.get("model_version"),
                    "generated_at": pred.get("generated_at"),
                    "features_used": pred.get("features_used"),
                    "source": "XGBoost model inference on current features",
                    "note": "Model prediction — not a direct measurement",
                }
    except Exception as exc:
        log.warning("Could not get current prediction: %s", exc)

    return JSONResponse(content={
        "status": "available",
        "latest_observed": latest_obs,
        "current_modelled": current_pred,
        "distinction": {
            "observed": "Actual Landsat satellite acquisition (date shown)",
            "modelled": "XGBoost prediction using current weather + latest satellite features",
            "important": "Do NOT call modelled values 'measured' or 'observed'",
        },
    })
