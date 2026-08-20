"""
AI explanation endpoints (Session 5)
====================================
Nemotron never computes numbers — it explains real project data. The backend
builds the whitelisted context, enforces that missing data stays unavailable,
and keeps the API key server-side.

Updated to include historical Landsat LST data for temporal queries.

    GET  /api/ai/status   -> configuration / availability report
    POST /api/ai/ask      -> {question, context?} -> structured explanation
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from backend.api.deps import get_serving
from backend.middleware.ratelimit import check_rate_limit
from backend.services.ai_context import (
    SYSTEM_PROMPT,
    build_context,
    render_context_for_prompt,
)
from backend.services.nemotron import NemotronClient, NemotronError
from backend.services.serving import ServingContext

router = APIRouter(prefix="/api/ai", tags=["ai"])


def get_ai_client() -> NemotronClient:
    """Lazy Nemotron client (fresh config per call so tests can override)."""
    return NemotronClient()


class AIAskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    # Whitelisted optional context supplied by the frontend (location,
    # environment, urban, air_quality, weather, prediction, scenario,
    # historical_lst).
    context: dict | None = None


@router.get("/status")
def ai_status(client: NemotronClient = Depends(get_ai_client)) -> JSONResponse:
    """Nemotron configuration / availability (no network call)."""
    return JSONResponse(content=client.status())


def _data_used(context: dict) -> list[str]:
    """Which real datasets actually made it into the context."""
    used: list[str] = []
    if context.get("environment"):
        keys = list(context["environment"])
        if "ndvi" in keys:
            used.append("NDVI")
        if "lst" in keys:
            used.append("LST (training data)")
        if "green_cover" in keys:
            used.append("Green cover")
        if "elevation" in keys or "slope" in keys:
            used.append("DEM/Terrain")
    if context.get("urban"):
        used.append("OSM (building/road/tree density)")
    if context.get("air_quality"):
        used.append("Air quality")
    if context.get("weather"):
        used.append("Weather (OpenWeather)")
    pred = context.get("prediction") or {}
    if pred.get("available"):
        used.append("XGBoost prediction")
    if context.get("scenario"):
        used.append("Scenario engine (XGBoost)")
    hist = context.get("historical_lst") or {}
    if hist.get("observation_date"):
        used.append(f"Landsat historical LST ({hist['observation_date']})")
    elif hist.get("observation_count"):
        used.append(f"Landsat historical LST ({hist['observation_count']} observations)")
    return used


@router.post("/ask")
def ai_ask(payload: AIAskRequest,
           request: Request,
           client: NemotronClient = Depends(get_ai_client),
           serving: ServingContext = Depends(get_serving)) -> JSONResponse:
    """Answer a city question with a Nemotron explanation of real context."""
    # 0) rate limit (paid NIM calls must not be loopable from the UI)
    limited = check_rate_limit(request)
    if limited is not None:
        return limited

    # 1) server-side context: real model availability (never claimed active)
    model_status = serving.model_status()

    # 1b) live pipeline data freshness and missing sources — Nemotron must
    # never present stale satellite values as live observations.
    data_freshness = None
    missing_sources = None
    try:
        from backend.services.live_feature_pipeline import get_pipeline
        pipeline = get_pipeline(serving.settings)
        result = pipeline.refresh()
        data_freshness = result.get("feature_age")
        missing_sources = result.get("missing_sources")
    except Exception as exc:  # pragma: no cover
        import logging
        logging.getLogger("backend.ai").debug(
            "Could not load pipeline data for context: %s", exc
        )

    # 1c) historical Landsat LST context
    historical_lst = None
    try:
        from backend.services.landsat_historical import get_landsat_service
        landsat = get_landsat_service(serving.settings)
        status = landsat.get_status()
        if status.get("status") == "available":
            historical_lst = {
                "status": "available",
                "analytics": landsat.get_analytics(),
            }
            # Include the selected date's observation if provided in context
            client_ctx = payload.context or {}
            selected_date = client_ctx.get("historical_lst", {}).get("date")
            if selected_date:
                obs = landsat.get_observation_metadata(selected_date)
                if obs:
                    historical_lst["observation"] = obs
    except Exception as exc:
        import logging
        logging.getLogger("backend.ai").debug(
            "Could not load historical Landsat data for context: %s", exc
        )

    # 2) whitelisted context: server model status + client-supplied blocks
    client_ctx = payload.context or {}
    # Get current snapshot_id for data provenance
    snapshot_id = client_ctx.get("snapshot_id")
    if not snapshot_id:
        try:
            from backend.services.live_data_manager.snapshot import get_current_snapshot
            snap = get_current_snapshot()
            snapshot_id = snap.snapshot_id
        except Exception:
            snapshot_id = None

    context = build_context(
        question=payload.question,
        location=client_ctx.get("location"),
        environment=client_ctx.get("environment"),
        urban=client_ctx.get("urban"),
        air_quality=client_ctx.get("air_quality"),
        weather=client_ctx.get("weather"),
        prediction=client_ctx.get("prediction"),
        scenario=client_ctx.get("scenario"),
        historical_lst=historical_lst,
        model_status=model_status,
        data_freshness=data_freshness,
        missing_sources=missing_sources,
        snapshot_id=snapshot_id,
    )
    data_used = _data_used(context)

    # 3) Nemotron availability (no key -> no fake connection attempt)
    if not client.config.configured:
        return JSONResponse(content={
            "success": False,
            "status": "configuration_required",
            "message": (
                "Nemotron configuration required: set NEMOTRON_API_KEY in .env "
                "(see .env.example)."
            ),
            "answer": None,
            "data_used": data_used,
            "context_used": context,
            "key_factors": None,
            "limitations": None,
        })

    # 4) call Nemotron with the authoritative context
    prompt_block = render_context_for_prompt(context)
    try:
        answer = client.ask(
            question=payload.question,
            system_prompt=SYSTEM_PROMPT,
            context_text=prompt_block,
        )
    except NemotronError as exc:
        return JSONResponse(content={
            "success": False,
            "status": exc.category,
            "message": "AI explanation unavailable.",
            "detail": str(exc),
            "answer": None,
            "data_used": data_used,
            "context_used": context,
            "key_factors": None,
            "limitations": None,
        })

    return JSONResponse(content={
        "success": True,
        "status": "ok",
        "answer": answer,
        "data_used": data_used,
        "context_used": context,
        "key_factors": None,   # plain-text provider: never fabricate structure
        "limitations": None,
    })
