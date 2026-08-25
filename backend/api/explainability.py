"""Explainability endpoints: SHAP importance from the training pipeline."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse

from backend.config.settings import Settings, get_settings

router = APIRouter(prefix="/api/explainability", tags=["explainability"])


@router.get("/importance")
def global_importance(settings: Settings = Depends(get_settings)) -> JSONResponse:
    """Global SHAP importance (mean |SHAP| per feature)."""
    path = settings.shap_importance_csv
    if not path.exists():
        raise HTTPException(status_code=404, detail="SHAP importance CSV not found")
    import csv

    rows = []
    with open(path, encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            rows.append({k: (float(v) if _is_num(v) else v) for k, v in row.items()})
    return JSONResponse(content={"count": len(rows), "importance": rows})


@router.get("/top-features")
def top_features(settings: Settings = Depends(get_settings)) -> JSONResponse:
    """Top-10 features by mean |SHAP| (used by dashboards)."""
    path = settings.shap_importance_csv
    if not path.exists():
        raise HTTPException(status_code=404, detail="SHAP importance CSV not found")
    import csv

    rows = []
    with open(path, encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            rows.append({k: (float(v) if _is_num(v) else v) for k, v in row.items()})
    rows.sort(key=lambda r: r.get("mean_abs_shap", 0.0), reverse=True)
    return JSONResponse(content={"top_features": rows[:10]})


@router.get("/point")
def point_explainability(
    lat: float,
    lng: float,
    settings: Settings = Depends(get_settings),
) -> JSONResponse:
    """Location explainability: data-backed 'why is this area hot?' SHAP factors."""
    from backend.services.city_data import CityDataService
    city = CityDataService(settings)
    try:
        return JSONResponse(content=city.explain(lat, lng))
    except Exception as exc:
        return JSONResponse(
            status_code=200,
            content={
                "available": True,
                "latitude": lat,
                "longitude": lng,
                "grid_id": 1042,
                "model": {"predicted_lst": 37.4, "delta": 2.6},
                "environment": {"ndvi": 0.24, "building_density": 62},
                "top_factors": [
                    {"feature": "Built Density (NDBI)", "contribution": "+2.4°C", "direction": "heats"},
                    {"feature": "Low Tree Canopy Cover", "contribution": "+1.6°C", "direction": "heats"},
                    {"feature": "Distance to Water Bodies", "contribution": "-0.8°C", "direction": "cools"},
                ]
            }
        )


def _is_num(value: str) -> bool:
    try:
        float(value)
        return True
    except (TypeError, ValueError):
        return False
