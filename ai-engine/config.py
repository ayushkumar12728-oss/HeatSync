"""
Central configuration for the Urban Heat Island AI Engine
==========================================================
All input paths, column roles, model settings, Optuna search space,
scenario definitions and output locations are defined here so the
pipeline stays parameter-free.

Run the whole pipeline with::

    cd ai-engine
    python main.py
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

# ai-engine/config.py -> ai-engine -> urban-digital-twin (project root)
PROJECT_ROOT = Path(__file__).resolve().parent.parent


@dataclass
class PathsConfig:
    """Every input file the engine reads and where everything is written."""

    # --- Inputs (produced by gis-engine/feature_engineering) ------------
    dataset_csv: Path = PROJECT_ROOT / "data" / "feature_engineering" / "training_dataset.csv"
    dataset_geojson: Path = PROJECT_ROOT / "data" / "feature_engineering" / "training_dataset.geojson"

    # --- Outputs (pipeline deliverables under data/outputs) ----------------
    output_root: Path = PROJECT_ROOT / "data" / "outputs"
    models_dir: Path = PROJECT_ROOT / "models"
    plots_dir: Path = PROJECT_ROOT / "data" / "outputs" / "plots"
    shap_dir: Path = PROJECT_ROOT / "data" / "outputs" / "plots" / "SHAP"
    reports_dir: Path = PROJECT_ROOT / "data" / "outputs" / "reports"
    logs_dir: Path = PROJECT_ROOT / "data" / "outputs" / "logs"

    # --- Deliverables (written at the output root, as requested) ---------
    best_model_pkl: Path = PROJECT_ROOT / "models" / "best_model.pkl"
    best_model_onnx: Path = PROJECT_ROOT / "models" / "best_model.onnx"
    leaderboard_csv: Path = PROJECT_ROOT / "data" / "outputs" / "leaderboard.csv"
    metrics_json: Path = PROJECT_ROOT / "data" / "outputs" / "metrics.json"
    predictions_csv: Path = PROJECT_ROOT / "data" / "predictions" / "predictions.csv"
    predicted_geojson: Path = PROJECT_ROOT / "data" / "predictions" / "Predicted_LST.geojson"
    predicted_tif: Path = PROJECT_ROOT / "data" / "predictions" / "Predicted_LST.tif"
    predicted_png: Path = PROJECT_ROOT / "data" / "predictions" / "Predicted_LST.png"

    def ensure(self) -> None:
        """Create all output directories (idempotent)."""
        for d in (self.output_root, self.models_dir, self.plots_dir,
                  self.shap_dir, self.reports_dir, self.logs_dir):
            d.mkdir(parents=True, exist_ok=True)


@dataclass
class DataConfig:
    """Column roles inside training_dataset.csv."""

    target: str = "Target_LST"

    # Explicitly known leakage columns (duplicate target information).
    known_leakage: List[str] = field(default_factory=lambda: ["MeanLST", "MaxLST", "MinLST"])

    # Columns that are identifiers, never features.
    id_columns: List[str] = field(default_factory=lambda: ["Grid_ID"])

    # Columns that carry no information (single value across the dataset)
    # are dropped automatically; these names are just documented here.
    constant_columns: List[str] = field(default_factory=lambda: [
        "Temperature", "Temperature_7d", "Humidity", "Humidity_7d",
        "WindSpeed", "WindSpeed_7d", "Pressure", "Pressure_7d",
        "SolarRadiation", "SolarRadiation_7d", "Rainfall", "Rainfall_7d",
        "HeatIndex", "HeatIndex_7d", "Season", "Month",
        "Temperature_MonthlyMean", "Humidity_MonthlyMean", "WindSpeed_MonthlyMean",
        "Pressure_MonthlyMean", "SolarRadiation_MonthlyMean", "Rainfall_MonthlyMean",
        "HeatIndex_MonthlyMean",
    ])

    # Autodetected leakage threshold: |corr(feature, target)| above this is
    # treated as duplicated target information and removed.
    leakage_corr_threshold: float = 0.99

    # Numeric-coded categorical columns (ordinal class codes already in data).
    categorical_columns: List[str] = field(default_factory=lambda: [
        "LandCoverClass", "VegDensityClass",
    ])

    # Categorical columns that are truly categorical for CatBoost.
    catboost_categoricals: List[str] = field(default_factory=lambda: [
        "LandCoverClass", "VegDensityClass",
    ])

    max_categorical_nunique: int = 12  # int-coded col with <= this many values -> categorical


@dataclass
class SplitConfig:
    """Train / test split settings."""

    test_size: float = 0.20
    random_state: int = 42
    cv_folds: int = 5


@dataclass
class ModelConfig:
    """Baseline hyper-parameters for the model comparison round."""

    n_jobs: int = max(1, (os.cpu_count() or 4) - 1)
    random_state: int = 42

    # XGBoost: GPU is used automatically when a CUDA device is available.
    use_gpu: bool = True

    # Random Forest / ExtraTrees baseline parameters.
    rf: Dict = field(default_factory=lambda: dict(
        n_estimators=400, max_depth=None, min_samples_leaf=2,
        max_features="sqrt", n_jobs=-1, random_state=42,
    ))
    extratrees: Dict = field(default_factory=lambda: dict(
        n_estimators=400, max_depth=None, min_samples_leaf=2,
        max_features="sqrt", n_jobs=-1, random_state=42,
    ))
    # HistGradientBoosting baseline.
    hgb: Dict = field(default_factory=lambda: dict(
        max_iter=800, learning_rate=0.08, max_depth=8, l2_regularization=1.0,
        early_stopping=True, validation_fraction=0.1, n_iter_no_change=30,
        random_state=42,
    ))
    # XGBoost baseline.
    xgb: Dict = field(default_factory=lambda: dict(
        n_estimators=2000, learning_rate=0.06, max_depth=8,
        subsample=0.9, colsample_bytree=0.9,
        min_child_weight=1, gamma=0.0, reg_alpha=0.0, reg_lambda=1.0,
        tree_method="hist", early_stopping_rounds=50, verbosity=0,
    ))
    # LightGBM baseline.
    lgb: Dict = field(default_factory=lambda: dict(
        n_estimators=2000, learning_rate=0.06, num_leaves=127,
        max_depth=10, subsample=0.9, colsample_bytree=0.9,
        reg_alpha=0.0, reg_lambda=1.0, min_child_samples=20,
        early_stopping_rounds=50, verbose=-1,
    ))
    # CatBoost baseline.
    cat: Dict = field(default_factory=lambda: dict(
        iterations=2000, learning_rate=0.06, depth=8,
        l2_leaf_reg=3.0, random_seed=42, verbose=0,
        early_stopping_rounds=50,
    ))


@dataclass
class OptunaConfig:
    """Hyper-parameter optimisation settings (STEP 6)."""

    n_trials: int = 100
    timeout_seconds: Optional[int] = None  # e.g. 1800 -> hard time cap
    random_state: int = 42
    n_startup_trials: int = 10
    # Optuna objective uses a validation split inside the training set
    # (with early stopping) for speed; final model is re-evaluated with
    # full 5-fold CV afterwards.
    val_fraction: float = 0.10
    min_learning_rate: float = 0.01
    max_learning_rate: float = 0.30


@dataclass
class ExplainabilityConfig:
    """SHAP sampling sizes (keep runs fast on 53k rows)."""

    global_sample: int = 3000      # global importance + summary plot
    local_sample: int = 300        # interaction values
    waterfall_samples: int = 3     # representative test rows
    n_dependence: int = 4          # top-N dependence plots
    n_top_features: int = 15       # features shown in global importance


@dataclass
class Scenario:
    """A sensitivity scenario: name + feature perturbations."""

    name: str
    description: str
    # feature -> (kind, value) where kind in {"add", "mul", "min", "max"}
    #   add : feature += value
    #   mul : feature *= value
    #   min : feature = min(feature, value)
    #   max : feature = max(feature, value)
    perturbations: Dict[str, tuple] = field(default_factory=dict)


@dataclass
class ScenarioConfig:
    """STEP 9 - sensitivity scenarios (green / built / tree / park / water)."""

    # Evaluated on the full training grid (all 53,802 cells) so the stored
    # aggregate results agree with the live simulation API and the cell-level
    # scenario outputs (which share the same grid and perturbation code).
    scenarios: List[Scenario] = field(default_factory=lambda: [
        Scenario(
            name="increase_green_10",
            description="Increase green cover by 10% (GreenCover, NDVI, vegetation pct up)",
            perturbations={
                "GreenCover": ("add", 10.0),
                "MeanNDVI": ("add", 0.06),
                "MaxNDVI": ("add", 0.03),
                "LandCover_VegetationPct": ("add", 5.0),
                "VegetationDensity": ("add", 5.0),
                "GreenSpacePct": ("add", 5.0),
                "TreeCount": ("add", 10.0),
                "TreeDensity": ("add", 5.0),
                "GreenToBuiltRatio": ("mul", 1.20),
                "VegetationCoolingIndex": ("mul", 1.15),
                "LandCover_BuiltupPct": ("add", -5.0),
                "ImperviousSurfaceRatio": ("add", -5.0),
                "HeatVulnerabilityIndex": ("add", -0.03),
            },
        ),
        Scenario(
            name="increase_green_20",
            description="Increase green cover by 20% (stronger greening)",
            perturbations={
                "GreenCover": ("add", 20.0),
                "MeanNDVI": ("add", 0.12),
                "MaxNDVI": ("add", 0.06),
                "LandCover_VegetationPct": ("add", 10.0),
                "VegetationDensity": ("add", 10.0),
                "GreenSpacePct": ("add", 10.0),
                "TreeCount": ("add", 20.0),
                "TreeDensity": ("add", 10.0),
                "GreenToBuiltRatio": ("mul", 1.40),
                "VegetationCoolingIndex": ("mul", 1.30),
                "LandCover_BuiltupPct": ("add", -10.0),
                "ImperviousSurfaceRatio": ("add", -10.0),
                "HeatVulnerabilityIndex": ("add", -0.06),
            },
        ),
        Scenario(
            name="decrease_buildings_10",
            description="Reduce building footprint & density by 10%",
            perturbations={
                "BuildingCoveragePct": ("mul", 0.9),
                "BuildingDensity": ("mul", 0.9),
                "BuildingCount": ("mul", 0.9),
                "LandCover_BuiltupPct": ("mul", 0.9),
                "ImperviousSurfaceRatio": ("mul", 0.9),
                "HeatVulnerabilityIndex": ("add", -0.02),
                "GreenToBuiltRatio": ("mul", 1.10),
            },
        ),
        Scenario(
            name="decrease_buildings_20",
            description="Reduce building footprint & density by 20%",
            perturbations={
                "BuildingCoveragePct": ("mul", 0.8),
                "BuildingDensity": ("mul", 0.8),
                "BuildingCount": ("mul", 0.8),
                "LandCover_BuiltupPct": ("mul", 0.8),
                "ImperviousSurfaceRatio": ("mul", 0.8),
                "HeatVulnerabilityIndex": ("add", -0.04),
                "GreenToBuiltRatio": ("mul", 1.20),
            },
        ),
        Scenario(
            name="increase_trees",
            description="Increase tree count and tree density",
            perturbations={
                "TreeCount": ("add", 50.0),
                "TreeDensity": ("add", 10.0),
                "MeanNDVI": ("add", 0.04),
                "VegetationDensity": ("add", 5.0),
                "GreenCover": ("add", 5.0),
                "VegetationCoolingIndex": ("mul", 1.10),
            },
        ),
        Scenario(
            name="increase_parks",
            description="Increase park area / bring parks closer (DistToPark reduced)",
            perturbations={
                "DistToPark": ("mul", 0.75),
                "CoolingDistanceIndex": ("mul", 1.15),
                "GreenSpacePct": ("add", 5.0),
                "GreenToBuiltRatio": ("mul", 1.10),
            },
        ),
        Scenario(
            name="increase_water",
            description="Increase water bodies (DistToWater reduced, water pct up)",
            perturbations={
                "DistToWater": ("mul", 0.75),
                "LandCover_WaterPct": ("add", 2.0),
                "CoolingDistanceIndex": ("mul", 1.10),
            },
        ),
    ])


@dataclass
class PredictionConfig:
    """STEP 10 - full-grid prediction settings."""

    crs: str = "EPSG:32645"     # UTM 45N, same as the feature-engineering grid
    cell_size_m: float = 100.0
    nodata: float = -9999.0


@dataclass
class Config:
    """Top-level configuration bundle."""

    paths: PathsConfig = field(default_factory=PathsConfig)
    data: DataConfig = field(default_factory=DataConfig)
    split: SplitConfig = field(default_factory=SplitConfig)
    model: ModelConfig = field(default_factory=ModelConfig)
    optuna: OptunaConfig = field(default_factory=OptunaConfig)
    explainability: ExplainabilityConfig = field(default_factory=ExplainabilityConfig)
    scenarios: ScenarioConfig = field(default_factory=ScenarioConfig)
    prediction: PredictionConfig = field(default_factory=PredictionConfig)

    log_level: str = "INFO"
    log_file: Path = Path("outputs/logs/ai_engine.log")

    @property
    def log_path(self) -> Path:
        return self.paths.logs_dir / self.log_file.name

    @classmethod
    def from_env(cls) -> "Config":
        cfg = cls()
        if os.environ.get("AIE_SEED"):
            seed = int(os.environ["AIE_SEED"])
            cfg.split.random_state = seed
            cfg.model.random_state = seed
            cfg.optuna.random_state = seed
        if os.environ.get("AIE_TRIALS"):
            cfg.optuna.n_trials = int(os.environ["AIE_TRIALS"])
        if os.environ.get("AIE_NO_GPU") and os.environ["AIE_NO_GPU"].lower() in ("1", "true", "yes"):
            cfg.model.use_gpu = False
        return cfg
