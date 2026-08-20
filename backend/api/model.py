"""
Model status endpoint
=====================
Reports whether the trained UHI model is actually available and, when it is,
its real metadata (algorithm, version, feature count, evaluation metrics from
``metrics.json``). Never fabricates a model or metrics: with no artifact on
disk it returns a clear ``model_unavailable`` status.

    GET /api/model/info
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from backend.api.deps import get_serving
from backend.services.serving import ServingContext

router = APIRouter(prefix="/api/model", tags=["model"])


@router.get("/info")
def model_info(serving: ServingContext = Depends(get_serving)) -> JSONResponse:
    """Real model availability + metadata (or a clear unavailable state)."""
    return JSONResponse(content=serving.model_status())
