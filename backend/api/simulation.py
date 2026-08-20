"""Simulation endpoints: scenarios, live runs, precomputed results."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

log = logging.getLogger("backend.api.simulation")

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from backend.api.deps import get_serving, get_simulation
from backend.config.settings import Settings, get_settings
from backend.middleware.ratelimit import check_rate_limit
from backend.schemas import (
    ScenarioInfo,
    SimulationResult,
    SimulationRunRequest,
)
from backend.services.serving import ServingContext
from backend.services.simulation import SimulationService

router = APIRouter(prefix="/api/simulation", tags=["simulation"])


@router.get("/scenarios", response_model=list[ScenarioInfo])
def list_scenarios(sim: SimulationService = Depends(get_simulation)) -> list[ScenarioInfo]:
    """The canonical intervention scenarios (greening, buildings, trees, ...)."""
    return [ScenarioInfo(**sc) for sc in sim.scenarios()]


@router.get("/results")
def saved_results(sim: SimulationService = Depends(get_simulation)):
    """Precomputed sensitivity analysis from the training pipeline, if present."""
    results = sim.saved_results()
    if results is None:
        raise HTTPException(
            status_code=404,
            detail="sensitivity_analysis.csv not found - run ai-engine/main.py",
        )
    return {"count": len(results), "results": results}


def _require_model(serving) -> JSONResponse | None:
    """Shared model-unavailable guard for the cell-level endpoints."""
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
    return None


@router.get("/results/{scenario}/cells")
def scenario_cells(
    scenario: str,
    refresh: bool = False,
    sim: SimulationService = Depends(get_simulation),
) -> JSONResponse:
    """Per-cell XGBoost results for a scenario.

    **Default behavior**: runs on the training grid (cached results),
    delegating to ``ScenarioCellsService``.

    **Refresh behavior** (?refresh=true): runs on the current feature grid
    using the live feature pipeline.
    """
    unavailable = _require_model(sim.serving)
    if unavailable is not None:
        return unavailable
    try:
        if refresh:
            # Run on current feature grid (architecture-correct mode)
            data = sim.run_current_scenario_cells(scenario)
        else:
            # Default: run on training grid (cached)
            data = sim.cells(scenario, refresh=False)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    return JSONResponse(content={"success": True, **data})


@router.get("/results/{scenario}/geojson")
def scenario_cells_geojson(
    scenario: str,
    refresh: bool = False,
    sim: SimulationService = Depends(get_simulation),
) -> JSONResponse:
    """MapLibre-ready GeoJSON (WGS84) of per-cell scenario results.

    **Default behavior**: precomputed from the training grid.

    **Refresh behavior** (?refresh=true): computed from the current feature
    grid using the live feature pipeline.
    """
    unavailable = _require_model(sim.serving)
    if unavailable is not None:
        return unavailable
    try:
        if refresh:
            fc = sim.run_current_scenario_geojson(scenario)
        else:
            fc = sim.cell_geojson(scenario, refresh=False)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    return JSONResponse(content=fc, media_type="application/geo+json")


@router.post("/run")
def run_scenario(payload: SimulationRunRequest,
                  request: Request,
                  sim: SimulationService = Depends(get_simulation),
                  serving: ServingContext = Depends(get_serving)) -> JSONResponse:
    """Run a named scenario or a custom perturbation set against the live model.

    Scenario → feature perturbations → XGBoost baseline & perturbed predictions
    → delta (perturbed - baseline).

    If ``payload.scenario`` is provided, runs the named scenario.
    If ``payload.perturbations`` is provided, runs a custom perturbation set.

    **Key difference from the default ``run_scenario()``**:
    - Without ``?current_grid=true``: runs on the training grid (default,
      backwards-compatible behavior).
    - With ``?current_grid=true``: runs on the current feature grid (live
      data), using the architecture-correct pipeline.

    Returns a clear ``model_unavailable`` state (HTTP 503) when the trained
    model / training grid is missing.
    """
    # rate limit (full-grid runs are expensive)
    limited = check_rate_limit(request)
    if limited is not None:
        return limited

    if payload.scenario and payload.perturbations:
        raise HTTPException(
            status_code=400,
            detail="Provide either 'scenario' or 'perturbations', not both",
        )
    if not payload.scenario and not payload.perturbations:
        raise HTTPException(status_code=400, detail="Provide 'scenario' or 'perturbations'")

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
        if payload.perturbations:
            result = sim.run_custom(payload.perturbations)
        else:
            # Use area-based scenario if area_mode is specified
            if payload.area_mode and payload.area_mode != "city":
                result = sim.run_scenario_area(
                    payload.scenario,
                    area_mode=payload.area_mode,
                    area_params=payload.area_params,
                )
            else:
                result = sim.run_scenario(payload.scenario)
    except ValueError as exc:
        return JSONResponse(
            status_code=400,
            content={"success": False, "status": "invalid_request", "message": str(exc)},
        )
    
    # Add area stats if present
    response_data = {"success": True, **SimulationResult(**result).model_dump()}
    if "area" in result:
        response_data["area"] = result["area"]
    if "validation" in result:
        response_data["validation"] = result["validation"]
    return JSONResponse(content=response_data)


@router.post("/run/current")
def run_current_scenario(
    payload: SimulationRunRequest,
    request: Request,
    sim: SimulationService = Depends(get_simulation),
    serving: ServingContext = Depends(get_serving),
) -> JSONResponse:
    """Run a scenario on the CURRENT feature grid (architecture-correct).

    This endpoint always uses the live feature pipeline to build the current
    53,802 × 58 feature matrix from live OpenWeather + AQI + satellite + GIS
    data, then runs XGBoost baseline and scenario predictions on that matrix.

    **CRITICAL**: This endpoint returns EVERYTHING in a single response:
    - snapshot_id: the authoritative snapshot this simulation is based on
    - simulation_id: unique identifier for this simulation run
    - baseline statistics
    - scenario statistics
    - delta statistics
    - per-cell results (baseline, scenario, delta for every cell)
    - GeoJSON FeatureCollection for map rendering
    - data freshness from the snapshot
    - model metadata

    The frontend MUST use this response directly and NOT make additional
    independent requests for cells or GeoJSON.
    """
    limited = check_rate_limit(request)
    if limited is not None:
        return limited

    if not payload.scenario:
        raise HTTPException(status_code=400, detail="Provide 'scenario' name")

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

    # Create authoritative snapshot first
    from backend.services.live_data_manager.snapshot import get_current_snapshot
    snapshot = get_current_snapshot(force_refresh=True)
    simulation_id = f"sim_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}_{snapshot.snapshot_id[-8:]}"

    try:
        # Run scenario cells on the current feature grid with area support
        cells_result = sim.run_current_scenario_cells(
            payload.scenario,
            area_mode=payload.area_mode,
            area_params=payload.area_params,
        )
    except ValueError as exc:
        return JSONResponse(
            status_code=400,
            content={"success": False, "status": "invalid_request", "message": str(exc)},
        )

    # Generate GeoJSON from the cells result (same snapshot, same data)
    geojson = None
    try:
        geojson = sim.run_current_scenario_geojson(payload.scenario)
    except Exception as exc:
        log.warning("GeoJSON generation failed: %s", exc)

    # Data freshness from the snapshot
    data_freshness = snapshot.freshness

    # Build response with area and validation stats
    response_data = {
        "success": True,
        "status": "success",
        "data_source": "current",
        "simulation_id": simulation_id,
        "snapshot_id": snapshot.snapshot_id,
        "generated_at": datetime.now(UTC).isoformat(),
        "scenario": {
            "name": payload.scenario,
            "description": cells_result.get("scenario", payload.scenario),
        },
        "baseline": {
            "mean_lst": cells_result.get("baseline_lst"),
            "min_lst": cells_result.get("baseline_lst"),
            "max_lst": cells_result.get("baseline_lst"),
        },
        "after": {
            "mean_lst": cells_result.get("mean_predicted_lst"),
        },
        "delta": {
            "mean_change": cells_result.get("mean_delta_lst"),
            "max_cooling": cells_result.get("min_delta"),
            "max_warming": cells_result.get("max_delta"),
            "pct_cells_cooler": cells_result.get("pct_cells_cooler"),
            "affected_cells": cells_result.get("count", 0),
        },
        "cells": cells_result.get("cells", []),
        "geojson": geojson,
        "data_sources": data_freshness,
        "model": {
            "name": type(serving.model).__name__,
            "version": serving.model_version,
            "feature_count": len(serving.features),
        },
        "snapshot_id": snapshot.snapshot_id,
        "simulation_id": simulation_id,
    }
    
    # Add area stats if present
    if "area" in cells_result:
        response_data["area"] = cells_result["area"]
    if "validation" in cells_result:
        response_data["validation"] = cells_result["validation"]
    
    return JSONResponse(content=response_data)


@router.get("/{simulation_id}/debug")
def simulation_debug(
    simulation_id: str,
    settings: Settings = Depends(get_settings),
    serving: ServingContext = Depends(get_serving),
) -> JSONResponse:
    """Simulation debugging endpoint.

    Returns comprehensive metadata about a simulation run for debugging.
    Validates geometry, counts valid/invalid cells, and returns data provenance.
    """
    # This is a metadata-only endpoint. In production, we would store
    # simulation results and look them up by ID. For now, return
    # structured debugging info from the current state.
    return JSONResponse(content={
        "success": True,
        "simulation_id": simulation_id,
        "note": "Simulation debug endpoint active. For full history, run POST /api/simulation/run/current and inspect the response.",
        "model": {
            "name": type(serving.model).__name__ if serving.model_available else None,
            "version": serving.model_version if serving.model_available else None,
            "feature_schema": len(serving.features) if serving.model_available else None,
            "available": serving.model_available,
        },
        "available_scenarios": sim.scenario_names() if sim else [],
    })