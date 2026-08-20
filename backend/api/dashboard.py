"""Dashboard aggregate endpoint: one call with everything a home page needs."""

from __future__ import annotations

import csv
import json

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from backend.api.deps import get_catalog, get_database
from backend.config.settings import Settings, get_settings
from backend.services.catalog import DataCatalog
from backend.services.database import DatabaseService

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("/summary")
def summary(
    settings: Settings = Depends(get_settings),
    catalog: DataCatalog = Depends(get_catalog),
    db: DatabaseService = Depends(get_database),
) -> JSONResponse:
    """Aggregated dashboard data: metrics, sensitivity, features, catalogue."""
    payload: dict = {
        "app": {"name": settings.app_name, "version": settings.version},
        "metrics": _read_json(settings.metrics_json),
        "sensitivity": _read_csv(settings.sensitivity_csv),
        "feature_statistics": _read_json(
            settings.project_root / "data" / "feature_engineering"
            / "feature_statistics.json"
        ),
        "catalogue": {
            "total_layers": len(catalog.layers),
            "by_category": catalog.categories(),
        },
        "database": db.status(),
    }
    return JSONResponse(content=payload)


def _read_json(path) -> dict | None:
    """Read a JSON file, or None if missing."""
    if path is None or not hasattr(path, "exists") or not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _read_csv(path) -> list | None:
    """Read a CSV file as a list of records, or None if missing."""
    if path is None or not hasattr(path, "exists") or not path.exists():
        return None
    try:
        with open(path, encoding="utf-8", newline="") as fh:
            return list(csv.DictReader(fh))
    except Exception:
        return None
