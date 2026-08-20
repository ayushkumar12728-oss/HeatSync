#!/usr/bin/env python3
"""
Urban Digital Twin - Backend API
================================
FastAPI backend serving the trained UHI model, geospatial layers, live
scenario simulations and pipeline metrics. Artifact-first: all endpoints read
the AI engine's outputs from disk; optional PostGIS is used when
``UDT_DATABASE_URL`` is set.

Run::

    uvicorn backend.main:app --reload          # development
    python -m backend.run                      # same, with defaults
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.config.logging import get_logger, setup_logging
from backend.config.settings import Settings, get_settings
from backend.middleware.errors import register_exception_handlers
from backend.middleware.request_logging import RequestLoggingMiddleware
from backend.services.catalog import DataCatalog
from backend.services.city_data import CityDataService
from backend.services.database import DatabaseService
from backend.services.serving import ServingContext
from backend.services.simulation import SimulationService

log = get_logger("backend.main")


def create_app(settings: Settings | None = None) -> FastAPI:
    """Application factory (used by uvicorn and by tests)."""
    settings = settings or get_settings()

    setup_logging(
        settings.log_level,
        log_file=str(settings.log_file) if not settings.debug else None,
    )

    app = FastAPI(
        title=settings.app_name,
        description=(
            "API for Urban Heat Island prediction, geospatial data layers "
            "and scenario simulation (Bhubaneswar digital twin)."
        ),
        version=settings.version,
        debug=settings.debug,
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # --- CORS ------------------------------------------------------------
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(RequestLoggingMiddleware)

    # --- rate limiting (cheap in-memory safeguard for expensive endpoints) -
    from backend.middleware.ratelimit import configure_rate_limits
    configure_rate_limits(
        enabled=settings.rate_limit_enabled,
        ai_per_minute=settings.rate_limit_ai_per_minute,
        sim_per_minute=settings.rate_limit_sim_per_minute,
    )

    # --- state (application-scoped services) -----------------------------
    app.state.settings = settings
    app.state.serving = ServingContext(settings)
    app.state.catalog = DataCatalog(settings)
    app.state.simulation = SimulationService(settings, app.state.serving)
    app.state.database = DatabaseService(settings)
    app.state.city_data = CityDataService(settings)

    # --- exception handlers ----------------------------------------------
    register_exception_handlers(app, debug=settings.debug)

    # --- routers ----------------------------------------------------------
    from backend.api import (
        ai,
        city,
        dashboard,
        data,
        environment,
        explainability,
        health,
        model,
        monitoring,
        prediction,
        routing,
        search,
        simulation,
        system,
    )

    for module in (health, data, prediction, simulation, explainability,
                   dashboard, monitoring, environment, model, ai,
                   city, routing, search, system):
        app.include_router(module.router)

    @app.get("/")
    def root() -> dict:
        """Root endpoint."""
        return {
            "message": settings.app_name,
            "version": settings.version,
            "status": "running",
            "docs": "/docs",
        }

    log.info("%s v%s ready (debug=%s)", settings.app_name, settings.version, settings.debug)
    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "backend.main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.debug,
        log_level=settings.log_level.lower(),
    )
