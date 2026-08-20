"""Health / readiness endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from backend.api.deps import get_app_settings, get_database
from backend.config.settings import Settings
from backend.schemas import ArtifactStatus, HealthStatus, Readiness
from backend.services.database import DatabaseService

router = APIRouter(prefix="/api/health", tags=["health"])


@router.get("", response_model=HealthStatus)
def liveness(settings: Settings = Depends(get_app_settings)) -> HealthStatus:
    """Liveness probe: the process is up."""
    return HealthStatus(status="ok", version=settings.version, app=settings.app_name)


@router.get("/ready", response_model=Readiness)
def readiness(settings: Settings = Depends(get_app_settings)) -> Readiness:
    """Readiness probe: the trained model and key artefacts are available."""
    missing = [str(p) for p in (
        settings.model_pkl, settings.leakage_report, settings.dataset_csv,
        settings.metrics_json,
    ) if not p.exists()]
    return Readiness(
        status="ready" if not missing else "not_ready",
        model_ready=not missing,
        missing_artifacts=missing,
    )


@router.get("/artifacts", response_model=list[ArtifactStatus])
def artifacts(settings: Settings = Depends(get_app_settings)) -> list[ArtifactStatus]:
    """Report the presence of every artefact the API depends on."""
    paths = {
        "model.pkl": settings.model_pkl,
        "model.onnx": settings.model_onnx,
        "leakage_report": settings.leakage_report,
        "training_dataset.csv": settings.dataset_csv,
        "training_grid.geojson": settings.dataset_geojson,
        "metrics.json": settings.metrics_json,
        "predictions.csv": settings.predictions_csv,
        "sensitivity_analysis.csv": settings.sensitivity_csv,
        "shap_importance.csv": settings.shap_importance_csv,
        "predicted_lst.geojson": settings.predicted_geojson,
        "predicted_lst.tif": settings.predicted_tif,
    }
    return [ArtifactStatus(name=n, path=str(p), exists=p.exists())
            for n, p in paths.items()]


@router.get("/database")
def database_status(db: DatabaseService = Depends(get_database)) -> dict:
    """Optional PostGIS connectivity report."""
    return db.status()
