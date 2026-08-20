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


def _is_num(value: str) -> bool:
    try:
        float(value)
        return True
    except (TypeError, ValueError):
        return False
