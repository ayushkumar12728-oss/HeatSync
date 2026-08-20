"""Pydantic request / response schemas for the Urban Digital Twin API."""

from __future__ import annotations

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------- #
# Health
# ---------------------------------------------------------------------- #
class HealthStatus(BaseModel):
    status: str
    version: str
    app: str


class ArtifactStatus(BaseModel):
    name: str
    path: str
    exists: bool


class Readiness(BaseModel):
    status: str
    model_ready: bool
    missing_artifacts: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------- #
# Data catalogue
# ---------------------------------------------------------------------- #
class LayerInfo(BaseModel):
    name: str
    title: str
    type: str
    category: str
    path: str
    url: str
    size_bytes: int | None = None
    modified_at: float | None = None


class LayerList(BaseModel):
    count: int
    categories: dict[str, int]
    layers: list[LayerInfo]


# ---------------------------------------------------------------------- #
# Prediction
# ---------------------------------------------------------------------- #
class PredictRequest(BaseModel):
    """One or more feature rows.

    ``features`` is a single row; ``batch`` is a list of rows. Both are
    optional but at least one must be supplied.
    """

    features: dict[str, float | int | str | bool] | None = None
    batch: list[dict[str, float | int | str | bool]] | None = None


class PredictionResult(BaseModel):
    predicted_lst_c: float = Field(description="Predicted land surface temperature in °C")
    grid_id: str | None = Field(default=None, description="Grid cell identifier (if supplied)")
    uhi_class: str | None = Field(
        default=None,
        description="Heat class label from the project's fixed breaks (visualization threshold)",
    )


class PredictResponse(BaseModel):
    count: int
    model: str
    predictions: list[PredictionResult]


class ModelInfo(BaseModel):
    model: str
    n_features: int
    features: list[str]


# ---------------------------------------------------------------------- #
# Simulation
# ---------------------------------------------------------------------- #
class SimulationRunRequest(BaseModel):
    """Run a named scenario, or supply a custom perturbation set.

    ``perturbations`` maps feature name -> [kind, value] where kind is one of
    ``add`` (feature += value), ``mul`` (feature *= value), ``min``
    (feature = min(feature, value)) or ``max`` (feature = max(feature, value)).

    ``area_mode`` selects the spatial extent of the intervention:
    - city: Apply to entire city (default, backwards-compatible)
    - polygon: User-drawn polygon (requires area_params.coords)
    - neighborhood: Predefined neighborhood (requires area_params.name)
    - radius: Circular area around a point (requires area_params.center_lon, center_lat, radius_m)
    - cells: Direct cell selection (requires area_params.cell_ids)
    """

    scenario: str | None = None
    perturbations: dict[str, list[str | float]] | None = None
    area_mode: str = "city"
    area_params: dict | None = None


class SimulationResult(BaseModel):
    scenario: str
    description: str = ""
    n_cells: int
    baseline_lst: float
    mean_predicted_lst: float
    mean_delta_lst: float
    min_delta: float
    max_delta: float
    pct_cells_cooler: float
    n_perturbed_features: int | None = None


class ScenarioInfo(BaseModel):
    name: str
    description: str
    perturbations: dict[str, list[str | float]]
