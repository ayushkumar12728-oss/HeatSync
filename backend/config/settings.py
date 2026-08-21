"""
Backend settings (environment-driven)
=====================================
All runtime configuration for the Urban Digital Twin API. Values are read
from environment variables prefixed with ``UDT_`` (see ``.env.example``) and
default to the project's artifact layout, so the API runs out of the box on a
machine where the pipeline has produced ``data/outputs`` and
``data/processed``.

Example::

    export UDT_DATABASE_URL=postgresql://admin:password@localhost:5432/urban_digital_twin
    export UDT_CORS_ORIGINS='["http://localhost:3000"]'
    uvicorn backend.main:app
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/config/settings.py -> backend -> project root
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


class Settings(BaseSettings):
    """Application settings, overridable via ``UDT_*`` environment variables."""

    model_config = SettingsConfigDict(
        env_prefix="UDT_",
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- application ----------------------------------------------------
    app_name: str = "Urban Digital Twin API"
    version: str = "1.0.0"
    debug: bool = False
    log_level: str = "INFO"
    log_file: Path = Field(
        default_factory=lambda: PROJECT_ROOT / "backend" / "logs" / "api.log"
    )

    # --- network --------------------------------------------------------
    cors_origins: list[str] = Field(
        default_factory=lambda: [
            "http://localhost:3000", "http://127.0.0.1:3000",
            "http://localhost:5173", "http://127.0.0.1:5173",
            "https://heatsync.netlify.app",
        ]
    )
    trust_proxy: bool = False

    # --- project layout -------------------------------------------------
    project_root: Path = PROJECT_ROOT
    data_dir: Path = Field(default_factory=lambda: PROJECT_ROOT / "data")
    ai_engine_dir: Path = Field(default_factory=lambda: PROJECT_ROOT / "ai-engine")
    outputs_dir: Path = Field(default_factory=lambda: PROJECT_ROOT / "data" / "outputs")
    osm_layers_dir: Path = Field(
        default_factory=lambda: PROJECT_ROOT / "data" / "raw" / "osm" / "layers"
    )
    boundary_geojson: Path = Field(
        default_factory=lambda: PROJECT_ROOT / "boundary.geojson"
    )

    # --- trained model --------------------------------------------------
    model_pkl: Path = Field(
        default_factory=lambda: PROJECT_ROOT / "models" / "best_model.pkl"
    )
    model_onnx: Path = Field(
        default_factory=lambda: PROJECT_ROOT / "models" / "best_model.onnx"
    )
    leakage_report: Path = Field(
        default_factory=lambda: PROJECT_ROOT
        / "data" / "outputs" / "reports" / "leakage_report.json"
    )
    preprocessor_cache: Path = Field(
        default_factory=lambda: PROJECT_ROOT
        / "data" / "predictions" / "serving" / "preprocessor.json"
    )

    # --- training / prediction data -------------------------------------
    dataset_csv: Path = Field(
        default_factory=lambda: PROJECT_ROOT
        / "data" / "feature_engineering" / "training_dataset.csv"
    )
    dataset_geojson: Path = Field(
        default_factory=lambda: PROJECT_ROOT
        / "data" / "feature_engineering" / "training_dataset.geojson"
    )
    metrics_json: Path = Field(
        default_factory=lambda: PROJECT_ROOT / "data" / "outputs" / "metrics.json"
    )
    predictions_csv: Path = Field(
        default_factory=lambda: PROJECT_ROOT / "data" / "predictions" / "predictions.csv"
    )
    sensitivity_csv: Path = Field(
        default_factory=lambda: PROJECT_ROOT
        / "data" / "outputs" / "reports" / "sensitivity_analysis.csv"
    )
    # Cell-level scenario outputs (per-cell GeoJSON / JSON caches).
    scenario_cells_dir: Path = Field(
        default_factory=lambda: PROJECT_ROOT / "data" / "outputs" / "scenarios"
    )
    shap_importance_csv: Path = Field(
        default_factory=lambda: PROJECT_ROOT
        / "data" / "outputs" / "plots" / "SHAP" / "global_shap_importance.csv"
    )
    predicted_geojson: Path = Field(
        default_factory=lambda: PROJECT_ROOT
        / "data" / "predictions" / "Predicted_LST.geojson"
    )
    predicted_tif: Path = Field(
        default_factory=lambda: PROJECT_ROOT
        / "data" / "predictions" / "Predicted_LST.tif"
    )
    predicted_png: Path = Field(
        default_factory=lambda: PROJECT_ROOT
        / "data" / "predictions" / "Predicted_LST.png"
    )

    # --- optional PostgreSQL / PostGIS ----------------------------------
    database_url: str | None = None

    # --- rate limiting (backend/middleware/ratelimit.py) -----------------
    rate_limit_enabled: bool = True
    rate_limit_ai_per_minute: int = 20    # POST /api/ai/ask (paid NIM calls)
    rate_limit_sim_per_minute: int = 10   # POST /api/simulation/run (full grid)

    # --- serving behaviour ----------------------------------------------
    max_batch_predict: int = 1000
    simulation_sample_size: int | None = None  # None -> use the full grid

    # --- Landsat historical LST pipeline ---------------------------------
    landsat_enabled: bool = True
    landsat_max_cloud_cover: float = 30.0
    landsat_cache_dir: Path = Field(
        default_factory=lambda: PROJECT_ROOT / "data" / "processed" / "temporal"
    )
    landsat_start_date: str | None = None
    landsat_end_date: str | None = None

    # --- Model V2 (temporal thermal model) --------------------------------
    model_registry_dir: Path = Field(
        default_factory=lambda: PROJECT_ROOT / "model_registry"
    )
    model_v2_dir: Path = Field(
        default_factory=lambda: PROJECT_ROOT / "model_registry" / "v2"
    )
    model_v2_pkl: Path = Field(
        default_factory=lambda: PROJECT_ROOT / "model_registry" / "v2" / "model_v2.joblib"
    )
    model_v2_schema: Path = Field(
        default_factory=lambda: PROJECT_ROOT / "model_registry" / "v2" / "feature_schema_v2.json"
    )
    model_v2_metrics: Path = Field(
        default_factory=lambda: PROJECT_ROOT / "model_registry" / "v2" / "metrics_v2.json"
    )
    model_v2_preprocessor: Path = Field(
        default_factory=lambda: PROJECT_ROOT / "model_registry" / "v2" / "preprocessor_v2.joblib"
    )
    historical_lst_dir: Path = Field(
        default_factory=lambda: PROJECT_ROOT / "data" / "historical_lst"
    )
    temporal_dataset_csv: Path = Field(
        default_factory=lambda: PROJECT_ROOT / "data" / "processed" / "temporal" / "temporal_dataset.csv"
    )
    # Which model version to use for live inference ("v1" or "v2")
    active_model_version: str = "v1"

    # --- live data probes (OpenWeather weather / AQ, Nominatim search) ----
    # The /api/system endpoints probe the public services with a short
    # timeout and cache results. Set to false in offline / CI environments
    # so health checks stay fast and deterministic.
    enable_live_probes: bool = True
    live_probe_timeout_seconds: float = 5.0
    live_weather_cache_seconds: int = 600      # 10 min
    live_aqi_cache_seconds: int = 600          # 10 min
    search_probe_cache_seconds: int = 900      # 15 min

    @property
    def db_enabled(self) -> bool:
        return bool(self.database_url)


@lru_cache
def get_settings() -> Settings:
    """Cached settings singleton (FastAPI dependency)."""
    return Settings()
