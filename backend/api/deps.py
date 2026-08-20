"""Shared FastAPI dependencies (settings, services)."""

from __future__ import annotations

from collections.abc import Iterator

from fastapi import Request

from backend.config.settings import Settings, get_settings
from backend.services.catalog import DataCatalog
from backend.services.city_data import CityDataService
from backend.services.database import DatabaseService
from backend.services.serving import ServingContext
from backend.services.simulation import SimulationService


def get_serving(request: Request) -> Iterator[ServingContext]:
    """Application-scoped lazy serving context."""
    yield request.app.state.serving


def get_catalog(request: Request) -> DataCatalog:
    return request.app.state.catalog


def get_simulation(request: Request) -> SimulationService:
    return request.app.state.simulation


def get_city_data(request: Request) -> CityDataService:
    """Application-scoped city-wide data service (lazy artifact loading)."""
    return request.app.state.city_data


def get_database(request: Request) -> DatabaseService:
    return request.app.state.database


def get_app_settings() -> Settings:
    return get_settings()
