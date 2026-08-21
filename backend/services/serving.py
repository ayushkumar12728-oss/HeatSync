"""
Model serving context
=====================
Lazily loads the trained XGBoost model together with the *exact* preprocessing
state that was used during training:

1. **Features**  — the ``kept`` list written by the AI engine's leakage
   detection (``outputs/reports/leakage_report.json``).
2. **Preprocessor** — fitted once from ``training_dataset.csv`` using the
   unchanged ``ai-engine`` ``Preprocessor`` (median imputation + label
   encoding of the two categorical columns). The fitted state is cached to
   ``outputs/serving/preprocessor.json`` so restarts skip the fit.
3. **Model** — ``models/best_model.pkl`` (joblib, XGBRegressor).
4. **Live feature pipeline** — constructs the current 58-feature vector from
   live observations (OpenWeather, AQI, latest satellite, GIS). The model is
   always run on the current feature vector, never on stale training data.

Everything is lazy: the model is only deserialised on the first prediction
request, and the full grid (``X_all``) is only built for simulation requests.
The live feature pipeline is refreshed on demand (e.g. when weather/AQI changes)
and caches results with a TTL to avoid hammering external APIs.
"""

from __future__ import annotations

import json
import logging
import math
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from backend.config.settings import Settings
from backend.utils import aie

log = logging.getLogger("backend.serving")

def _as_gid(value) -> int | str:
    """Grid_ID is an integer in the dataset; keep it as int when possible."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return value

# Static feature indices (GIS, terrain, satellite - change rarely/never)
# Dynamic feature indices (AQI - changes hourly)
_AQI_FEATURE_INDICES = [44, 45, 46, 47, 48, 49, 50]  # MeanAQI, MeanPM25, MeanPM10, MeanNO2, MeanSO2, MeanCO, MeanO3


def _as_original_type(value: str):
    """Recover the numeric type of a JSON-serialised encoding key."""
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        return value


def _mode_fallback_codes(pre, frame: pd.DataFrame) -> dict[str, float]:
    """For each categorical column, the code of its most frequent value."""
    out: dict[str, float] = {}
    for col in pre.categorical_cols:
        mapping = pre.encodings.get(col, {})
        if not mapping:
            continue
        if frame[col].notna().any():
            mode_val = frame[col].mode().iloc[0]
            out[col] = float(mapping.get(mode_val, max(mapping.values(), default=0.0)))
        else:
            out[col] = float(max(mapping.values(), default=0.0))
    return out


class ServingContext:
    """Thread-safe, lazily-initialised model + preprocessing context.

    Supports both V1 (spatial baseline) and V2 (temporal thermal model).
    The active model version is controlled by settings.active_model_version.
    """

    def __init__(self, settings: Settings):
        self.settings = settings
        self._lock = threading.RLock()
        self._model: object | None = None
        self._features: list[str] | None = None
        self._preprocessor: object | None = None
        self._grid_ids: pd.Series | None = None
        self._x_all: pd.DataFrame | None = None
        # categorical column -> fallback code (code of the most frequent
        # training value) used when a request is missing or has an unseen value
        self._cat_fallback: dict[str, float] = {}
        # V2 model support
        self._model_v2: object | None = None
        self._features_v2: list[str] | None = None
        self._preprocessor_v2: dict | None = None
        # --- Static feature cache ---
        self._static_feature_matrix: np.ndarray | None = None  # 53802 x 58 (static features only)
        self._static_feature_matrix_raw: pd.DataFrame | None = None  # raw DataFrame before transform
        self._satellite_per_cell: dict[str, dict] | None = None  # per-cell satellite data
        self._static_feature_loaded: bool = False
        # --- Prediction cache ---
        self._prediction_cache: dict[str, dict] = {}  # snapshot_id -> prediction result
        self._prediction_cache_lock = threading.RLock()

        # --- Eager startup loading ---
        # Pre-load model + features + static matrix so the first /heat/current
        # request doesn't pay the full cold-start penalty.
        if self.model_available:
            try:
                _ = self.model
                _ = self.features
                _ = self.preprocessor
                self._load_static_feature_matrix()
                log.info("Startup eager-load complete — model, features, and static matrix ready.")
            except Exception as exc:
                log.warning("Startup eager-load failed (will retry lazily): %s", exc)

        # --- GeoJSON resolution diagnostic ---
        self._log_geojson_status()

    def _log_geojson_status(self) -> None:
        """Log the resolved GeoJSON path, existence, feature count, and CRS."""
        geojson_path = self.settings.dataset_geojson
        exists = geojson_path.exists()
        log.info("GeoJSON grid diagnostic:")
        log.info("  resolved path : %s", geojson_path)
        log.info("  exists        : %s", exists)
        if exists:
            try:
                with open(geojson_path, encoding="utf-8") as fh:
                    gj = json.load(fh)
                features = gj.get("features", [])
                crs = gj.get("crs", {}).get("properties", {}).get("name", "unknown")
                log.info("  feature count : %d", len(features))
                log.info("  CRS           : %s", crs)
            except Exception as exc:
                log.warning("  Could not read GeoJSON metadata: %s", exc)
        else:
            log.warning("  File NOT found — spatial outputs and satellite per-cell data will be unavailable.")

    # ------------------------------------------------------------------ #
    # Public properties
    # ------------------------------------------------------------------ #
    @property
    def model_available(self) -> bool:
        """True when the trained model artifact exists on disk (no load)."""
        return self.settings.model_pkl.exists()

    @property
    def model(self):
        with self._lock:
            if self._model is None:
                self._model = self._load_model()
            return self._model

    @property
    def features(self) -> list[str]:
        with self._lock:
            if self._features is None:
                self._features = self._load_features()
            return list(self._features)

    @property
    def preprocessor(self):
        with self._lock:
            if self._preprocessor is None:
                self._preprocessor = self._load_preprocessor()
            return self._preprocessor

    @property
    def grid_ids(self) -> pd.Series:
        with self._lock:
            if self._grid_ids is None:
                df = self._load_dataset()
                self._grid_ids = df["Grid_ID"].astype(str)
            return self._grid_ids

    @property
    def x_all(self) -> pd.DataFrame:
        """Transformed feature matrix for the full grid (simulation use)."""
        with self._lock:
            if self._x_all is None:
                df = self._load_dataset()
                pre = self.preprocessor
                self._x_all = pre.transform(df[self.features])
            return self._x_all

    @property
    def current_feature_grid(self) -> dict:
        """Construct the current feature grid from live observations.

        Returns a dict with:
        - grid_id, latitude, longitude
        - feature_values with provenance (source, timestamp, status)
        - prediction from XGBoost on current features
        - data freshness timestamps

        This is the key property that replaces stale training-data features
        with current live observations for model inference.
        """
        from backend.services.live_feature_pipeline import refresh_feature_pipeline
        result = refresh_feature_pipeline(self.settings)
        # Store the feature map for downstream use
        self._current_feature_grid = result
        return result

    @property
    def current_prediction(self) -> dict | None:
        """Current predicted LST from the live feature pipeline.

        Returns None if the model is unavailable or prediction failed.
        Accepts both 'available' (all sources live) and 'partial' (some
        sources from training dataset) — the prediction is still valid
        but the caller must check the status for data honesty.
        """
        if not self.model_available:
            return None
        try:
            from backend.services.live_feature_pipeline import refresh_feature_pipeline
            grid = refresh_feature_pipeline(self.settings)
            prediction = grid.get("prediction", {})
            lst = prediction.get("predicted_lst_c")
            if lst is not None and grid.get("status") in ("available", "partial"):
                return prediction
            return None
        except Exception as exc:
            log.error("Current prediction failed: %s", exc)
            return None

    @property
    def model_metadata(self) -> dict:
        return {
            "type": type(self.model).__name__,
            "n_features": len(self.features),
            "features": list(self.features),
        }

    @property
    def model_version(self) -> str | None:
        """The installed library version behind the model (best effort)."""
        try:
            import xgboost
            return getattr(xgboost, "__version__", None)
        except Exception:
            return None

    # ------------------------------------------------------------------ #
    # V2 model support
    # ------------------------------------------------------------------ #
    @property
    def model_v2_available(self) -> bool:
        """True when the V2 model artifact exists on disk."""
        return self.settings.model_v2_pkl.exists()

    @property
    def model_v2(self):
        """Load the V2 temporal thermal model."""
        with self._lock:
            if self._model_v2 is None and self.model_v2_available:
                try:
                    self._model_v2 = joblib.load(self.settings.model_v2_pkl)
                    log.info("V2 model loaded: %s", type(self._model_v2).__name__)
                except Exception as exc:
                    log.error("Failed to load V2 model: %s", exc)
            return self._model_v2

    @property
    def features_v2(self) -> list[str]:
        """Feature list for the V2 model."""
        with self._lock:
            if self._features_v2 is None and self.settings.model_v2_schema.exists():
                try:
                    schema = json.loads(self.settings.model_v2_schema.read_text(encoding="utf-8"))
                    self._features_v2 = schema.get("features", [])
                except Exception as exc:
                    log.warning("Could not load V2 feature schema: %s", exc)
                    self._features_v2 = []
            return list(self._features_v2 or [])

    @property
    def active_model(self) -> object:
        """Return the active model (V1 or V2) based on settings."""
        if self.settings.active_model_version == "v2" and self.model_v2_available:
            return self.model_v2
        return self.model

    @property
    def active_features(self) -> list[str]:
        """Return the feature list for the active model."""
        if self.settings.active_model_version == "v2" and self.model_v2_available:
            return self.features_v2
        return self.features

    @property
    def active_model_version_label(self) -> str:
        """Return the active model version label."""
        if self.settings.active_model_version == "v2" and self.model_v2_available:
            return "v2"
        return "v1"

    # ------------------------------------------------------------------ #
    # Static feature matrix loading
    # ------------------------------------------------------------------ #
    def _load_static_feature_matrix(self) -> None:
        """Load and cache the static feature matrix (GIS, terrain, satellite per-cell).
        
        This loads the training dataset once and extracts the static features
        (GIS, terrain, satellite per-cell) that don't change between predictions.
        Only AQI features (7) are dynamic; the rest are static per cell.
        """
        with self._lock:
            if self._static_feature_loaded:
                return
            
            log.info("Loading static feature matrix (53,802 cells x 58 features)...")
            start = time.perf_counter()
            
            # Load dataset
            df = self._load_dataset()
            log.info("Dataset loaded: %d rows x %d cols", *df.shape)
            
            # Extract satellite per-cell data from GeoJSON
            self._satellite_per_cell = self._extract_satellite_per_cell()
            
            # Build raw feature matrix with static features from dataset
            # We'll fill in dynamic features (AQI) later per prediction
            features_list = self.features
            pre = self.preprocessor
            
            # Build raw feature DataFrame
            # For static features: use dataset values
            # For dynamic features (AQI): use fill_values as placeholder
            raw_data = {}
            for feat_name in features_list:
                if feat_name in df.columns:
                    # Use dataset value (static GIS, terrain, satellite per-cell)
                    raw_data[feat_name] = df[feat_name].values
                elif feat_name in pre.fill_values:
                    # Use imputation value as placeholder for dynamic features
                    raw_data[feat_name] = np.full(len(df), pre.fill_values[feat_name], dtype=np.float32)
                else:
                    raw_data[feat_name] = np.zeros(len(df), dtype=np.float32)
            
            raw_df = pd.DataFrame(raw_data, index=range(len(df)))
            
            # Transform using preprocessor
            X_static = pre.transform(raw_df[features_list])
            
            # Store as numpy array for fast access
            self._static_feature_matrix = X_static.values.astype(np.float32)
            self._static_feature_matrix_raw = raw_df
            self._static_feature_loaded = True
            
            elapsed = (time.perf_counter() - start) * 1000
            log.info("Static feature matrix loaded: %dx%d in %.1f ms", 
                     *self._static_feature_matrix.shape, elapsed)
    
    def _extract_satellite_per_cell(self) -> dict[str, dict]:
        """Extract satellite per-cell data from GeoJSON once at startup."""
        sat_path = Path(self.settings.dataset_geojson)
        if not sat_path.exists():
            log.warning("Satellite source not found: %s", sat_path)
            return {}
        
        try:
            with open(sat_path, encoding="utf-8") as fh:
                geojson = json.load(fh)
            
            raw_features = geojson.get("features", [])
            if not raw_features:
                return {}
            
            sat_field_names = [
                "MeanNDVI", "MaxNDVI", "MinNDVI",
                "GreenCover", "VegetationDensity", "VegDensityClass",
                "LandCoverClass",
                "LandCover_WaterPct", "LandCover_VegetationPct",
                "LandCover_BuiltupPct", "LandCover_BareLandPct",
            ]
            
            sat_features_by_cell: dict[str, dict] = {}
            for feat in raw_features:
                props = feat.get("properties", {})
                gid = props.get("Grid_ID")
                if gid is None:
                    continue
                gid_str = str(gid)
                cell_data = {}
                for field in sat_field_names:
                    val = props.get(field)
                    if val is not None:
                        try:
                            cell_data[field] = float(val)
                        except (TypeError, ValueError):
                            pass
                if cell_data:
                    sat_features_by_cell[gid_str] = cell_data
            
            log.info("Satellite per-cell data extracted: %d cells, %d fields", 
                     len(sat_features_by_cell), len(sat_field_names))
            return sat_features_by_cell
            
        except Exception as exc:
            log.warning("Could not extract satellite per-cell data: %s", exc)
            return {}

    # ------------------------------------------------------------------ #
    # Prediction cache
    # ------------------------------------------------------------------ #
    def _get_cached_prediction(self, snapshot_id: str) -> dict | None:
        """Get cached prediction for snapshot if available and valid."""
        cache_key = f"{snapshot_id}:{self.active_model_version_label}"
        with self._prediction_cache_lock:
            cached = self._prediction_cache.get(cache_key)
            if cached is not None:
                log.info("Prediction cache hit for snapshot %s", snapshot_id)
                return cached
        return None
    
    def _set_cached_prediction(self, snapshot_id: str, result: dict) -> None:
        """Cache prediction result for snapshot."""
        cache_key = f"{snapshot_id}:{self.active_model_version_label}"
        with self._prediction_cache_lock:
            self._prediction_cache[cache_key] = result
            log.info("Prediction cached for snapshot %s", snapshot_id)
    
    def _invalidate_prediction_cache(self, snapshot_id: str | None = None) -> None:
        """Invalidate prediction cache for a snapshot or all."""
        with self._prediction_cache_lock:
            if snapshot_id is None:
                self._prediction_cache.clear()
                log.info("Prediction cache fully invalidated")
            else:
                cache_key = f"{snapshot_id}:{self.active_model_version_label}"
                if cache_key in self._prediction_cache:
                    del self._prediction_cache[cache_key]
                    log.info("Prediction cache invalidated for snapshot %s", snapshot_id)

    # ------------------------------------------------------------------ #
    # Optimized prediction methods
    # ------------------------------------------------------------------ #
    def get_current_prediction_fast(self) -> dict | None:
        """Fast path: Get current prediction with caching by snapshot.
        
        This avoids rebuilding the feature grid if the snapshot hasn't changed.
        """
        # Get current snapshot ID
        snapshot_id = None
        try:
            from backend.services.live_data_manager.snapshot import get_current_snapshot
            snap = get_current_snapshot()
            snapshot_id = snap.snapshot_id
        except Exception:
            pass
        
        # Check cache first
        if snapshot_id:
            cached = self._get_cached_prediction(snapshot_id)
            if cached is not None:
                return cached
        
        # Fallback to slow path
        if not self.model_available:
            return None
        try:
            from backend.services.live_feature_pipeline import refresh_feature_pipeline
            grid = refresh_feature_pipeline(self.settings)
            prediction = grid.get("prediction", {})
            lst = prediction.get("predicted_lst_c")
            if lst is not None and grid.get("status") in ("available", "partial"):
                result = prediction
                if snapshot_id:
                    self._set_cached_prediction(snapshot_id, result)
                return result
            return None
        except Exception as exc:
            log.error("Fast current prediction failed: %s", exc)
            return None

    def get_current_grid_predictions_fast(self) -> dict:
        """Fast path: Get current grid predictions with caching by snapshot."""
        # Get current snapshot ID
        snapshot_id = None
        try:
            from backend.services.live_data_manager.snapshot import get_current_snapshot
            snap = get_current_snapshot()
            snapshot_id = snap.snapshot_id
        except Exception:
            pass
        
        # Check cache first
        cache_key = f"{snapshot_id}:{self.active_model_version_label}:grid"
        with self._prediction_cache_lock:
            cached = self._prediction_cache.get(cache_key)
            if cached is not None:
                log.info("Grid prediction cache hit for snapshot %s", snapshot_id)
                return cached
        
        # Load static feature matrix if not loaded
        if not self._static_feature_loaded:
            self._load_static_feature_matrix()
        
        # Get current snapshot for dynamic features
        from backend.services.live_data_manager.snapshot import get_current_snapshot
        snap = get_current_snapshot()
        snapshot_id = snap.snapshot_id
        
        # Build dynamic feature overrides (AQI only)
        dynamic_overrides = self._get_dynamic_overrides(snap)
        
        # Build feature matrix: static base + dynamic overrides (AQI)
        # Apply overrides FIRST, then predict ONCE.
        X = self._apply_overrides(self._static_feature_matrix, dynamic_overrides)

        log.info(
            "Grid prediction: snapshot=%s, cells=%d, overrides=%d",
            snapshot_id, self._static_feature_matrix.shape[0], len(dynamic_overrides),
        )

        predictions = self.model.predict(X)
        
        predictions = np.asarray(predictions).ravel()
        grid_ids = list(self.grid_ids[:len(predictions)])

        log.info(
            "Grid prediction complete: predictions=%d, grid_ids=%d, min=%.2f, max=%.2f, mean=%.2f",
            len(predictions), len(grid_ids),
            float(np.min(predictions)), float(np.max(predictions)), float(np.mean(predictions)),
        )

        cells = [
            {
                "grid_id": _as_gid(grid_ids[i]),
                "predicted_lst": float(predictions[i]),
            }
            for i in range(len(grid_ids))
        ]
        
        result = {
            "count": len(cells),
            "cells": cells,
            "summary": {
                "mean_lst": float(np.mean(predictions)),
                "min_lst": float(np.min(predictions)),
                "max_lst": float(np.max(predictions)),
            },
        }
        
        # Cache result
        cache_key = f"{snapshot_id}:{self.active_model_version_label}:grid"
        with self._prediction_cache_lock:
            self._prediction_cache[cache_key] = result
        
        return result
    
    def _get_dynamic_overrides(self, snapshot) -> dict[int, float]:
        """Extract dynamic feature overrides (AQI) from snapshot."""
        overrides = {}
        # AQI feature indices: 44-50 (MeanAQI, MeanPM25, MeanPM10, MeanNO2, MeanSO2, MeanCO, MeanO3)
        aqi_indices = _AQI_FEATURE_INDICES
        
        # Get AQI data from snapshot
        aqi = snapshot.air_quality
        if not aqi or not aqi.get("available"):
            return overrides
        
        current = aqi.get("current", {})
        aqi_key_map = {
            44: "aqi",       # MeanAQI
            45: "pm2_5",     # MeanPM25
            46: "pm10",      # MeanPM10
            47: "no2",       # MeanNO2
            48: "so2",       # MeanSO2
            49: "co",        # MeanCO
            50: "o3",        # MeanO3
        }
        
        for idx, aqi_key in aqi_key_map.items():
            val = current.get(aqi_key)
            if val is not None:
                overrides[idx] = float(val)
        
        return overrides
    
    def _apply_overrides(self, base_matrix: np.ndarray, overrides: dict[int, float]) -> np.ndarray:
        """Apply dynamic feature overrides to base matrix efficiently."""
        if not overrides:
            return base_matrix
        
        # Create a copy to avoid modifying cached static matrix
        X = base_matrix.copy()
        for idx, val in overrides.items():
            X[:, idx] = val
        return X
    
    def invalidate_caches(self) -> None:
        """Invalidate all caches (call when model changes)."""
        with self._lock:
            self._static_feature_matrix = None
            self._static_feature_matrix_raw = None
            self._satellite_per_cell = None
            self._static_feature_loaded = False
        self._invalidate_prediction_cache()
        log.info("All caches invalidated")

    def model_status(self) -> dict:
        """Non-raising availability report used by /api/model/info.

        Never loads the model just to report status; only checks artifacts on
        disk. Never fabricates metrics.
        """
        missing: list[str] = []
        for label, path in (
            ("model", self.settings.model_pkl),
            ("features", self.settings.leakage_report),
            ("dataset", self.settings.dataset_csv),
        ):
            if not path.exists():
                missing.append(label)

        if not self.model_available:
            return {
                "available": False,
                "status": "model_unavailable",
                "message": (
                    "Trained model artifact is not available. Required: "
                    f"{self.settings.model_pkl} (generated by `python ai-engine/main.py`)."
                ),
                "model": None,
                "version": None,
                "feature_count": None,
                "features": None,
                "missing_artifacts": missing,
                "metrics": None,
            }

        # Model exists: load once (cached) and report real metadata.
        try:
            model = self.model
            features = self.features
            metrics = self._read_metrics()
            return {
                "available": True,
                "status": "available",
                "model": type(model).__name__,
                "version": self.model_version,
                "feature_count": len(features),
                "features": list(features),
                "missing_artifacts": missing,
                "metrics": metrics,
                "preprocessor_cache": self.settings.preprocessor_cache.exists(),
            }
        except Exception as exc:  # pragma: no cover - artifact corruption path
            return {
                "available": False,
                "status": "model_load_error",
                "message": f"Model artifact present but could not be loaded: {exc}",
                "model": None,
                "version": None,
                "feature_count": None,
                "features": None,
                "missing_artifacts": missing,
                "metrics": None,
            }

    def _read_metrics(self) -> dict | None:
        """Pipeline evaluation metrics (metrics.json) if the file exists."""
        path = self.settings.metrics_json
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None

    # ------------------------------------------------------------------ #
    # Loading
    # ------------------------------------------------------------------ #
    def _load_model(self):
        path = self.settings.model_pkl
        if not path.exists():
            raise FileNotFoundError(
                f"Trained model not found: {path}. Run `python ai-engine/main.py` "
                "or point UDT_MODEL_PKL at an existing artifact."
            )
        log.info("Loading model from %s", path)
        model = joblib.load(path)
        log.info("Model loaded: %s", type(model).__name__)
        return model

    def _load_features(self) -> list[str]:
        """Feature list from the leakage report (single source of truth).

        Falls back to the fitted model's own feature names when the report is
        missing, so the model remains usable if only the pkl exists.
        """
        path = self.settings.leakage_report
        if path.exists():
            with open(path, encoding="utf-8") as fh:
                report = json.load(fh)
            features = report.get("kept") or report.get("selected_features")
            if features:
                log.info("Loaded %d model features from %s", len(features), path)
                return list(features)
            raise ValueError(f"No kept features in {path}")

        # Fallback: read feature names straight from the fitted model.
        log.warning(
            "Leakage report missing (%s) - deriving features from the model.",
            path,
        )
        model = self.model
        names = None
        for attr in ("feature_names_in_", "feature_names"):
            if hasattr(model, attr) and getattr(model, attr) is not None:
                names = list(getattr(model, attr))
                break
        if names is None and hasattr(model, "get_booster"):
            booster_names = model.get_booster().feature_names
            if booster_names:
                names = list(booster_names)
        if not names:
            raise ValueError(
                f"Cannot derive the feature list (no leakage report at {path} "
                "and the model exposes no feature names)."
            )
        log.info("Derived %d model features from the fitted model", len(names))
        return names

    def _load_preprocessor(self):
        """Restore the fitted preprocessor (cache) or fit it from the CSV."""
        cache = self.settings.preprocessor_cache
        if cache.exists():
            try:
                state = json.loads(cache.read_text(encoding="utf-8"))
                pre = self._restore_preprocessor(state)
                log.info("Preprocessor restored from cache (%s)", cache)
                return pre
            except Exception as exc:
                log.warning("Preprocessor cache unusable (%s) - refitting.", exc)

        log.info("Fitting preprocessor from %s ...", self.settings.dataset_csv)
        pre = self._fit_preprocessor()
        try:
            self._save_preprocessor_cache(pre)
        except Exception as exc:
            log.warning("Could not write preprocessor cache: %s", exc)
        return pre

    def _fit_preprocessor(self):
        """Re-run the unchanged ai-engine column-role + leakage + preprocessing steps."""
        cfg = aie.aie_config().Config()
        # honour env overrides for non-default artifact locations
        cfg.paths.dataset_csv = self.settings.dataset_csv
        cfg.paths.dataset_geojson = self.settings.dataset_geojson

        loader = aie.aie_data_loader().DataLoader(cfg)
        df = loader.load()
        schema = loader.report()

        selector = aie.aie_feature_selection().FeatureSelector(cfg, schema)
        df_clean, features = selector.run(df)
        if set(features) != set(self._load_features()):
            log.warning(
                "Refitted feature list differs from leakage report "
                "(%d vs %d features) - using refitted list.",
                len(features), len(self._load_features()),
            )

        pre = aie.aie_preprocessing().Preprocessor(cfg)
        pre.fit_transform(df_clean[features], schema["categorical_columns"])
        self._features = features
        self._cat_fallback = _mode_fallback_codes(pre, df_clean[features])
        log.info("Preprocessor fitted: %d features, %d categoricals",
                 len(features), len(pre.categorical_cols))
        return pre

    def _restore_preprocessor(self, state: dict):
        pre = aie.aie_preprocessing().Preprocessor(aie.aie_config().Config())
        pre.categorical_cols = list(state.get("categorical_cols", []))
        pre.numeric_cols = list(state.get("numeric_cols", []))
        pre.fill_values = dict(state.get("fill_values", {}))
        # JSON object keys are always strings; recover the original value type
        # (int / float / str) so .map() matches the training DataFrame.
        pre.encodings = {
            k: {_as_original_type(a): b for a, b in v.items()}
            for k, v in state.get("encodings", {}).items()
        }
        if state.get("features"):
            # keep the feature list consistent with the cached preprocessor
            self._features = list(state["features"])
        self._cat_fallback = {k: float(v)
                              for k, v in state.get("categorical_fallback_codes", {}).items()}
        return pre

    def _save_preprocessor_cache(self, pre) -> None:
        state = {
            "categorical_cols": pre.categorical_cols,
            "numeric_cols": pre.numeric_cols,
            "fill_values": pre.fill_values,
            "encodings": {k: {str(a): b for a, b in v.items()}
                          for k, v in pre.encodings.items()},
            "categorical_fallback_codes": self._cat_fallback,
            "features": self.features,
            "dataset_csv": str(self.settings.dataset_csv),
            "n_rows": int(pd.read_csv(self.settings.dataset_csv, usecols=["Grid_ID"]).shape[0])
            if self.settings.dataset_csv.exists() else None,
            "created_at": datetime.now(UTC).isoformat(),
        }
        self.settings.preprocessor_cache.parent.mkdir(parents=True, exist_ok=True)
        self.settings.preprocessor_cache.write_text(
            json.dumps(state, indent=2), encoding="utf-8"
        )
        log.info("Preprocessor cache written: %s", self.settings.preprocessor_cache)

    def _load_dataset(self) -> pd.DataFrame:
        path = self.settings.dataset_csv
        if not path.exists():
            raise FileNotFoundError(
                f"Training dataset not found: {path}. It is required for "
                "grid-wide prediction and simulation endpoints."
            )
        log.info("Loading training dataset %s ...", path)
        df = pd.read_csv(path)
        log.info("Dataset loaded: %d rows x %d cols", *df.shape)
        return df

    # ------------------------------------------------------------------ #
    # Prediction API
    # ------------------------------------------------------------------ #
    def transform_rows(self, rows: list[dict]) -> pd.DataFrame:
        """Turn request payloads into a model-ready feature DataFrame.

        * Drops unknown keys, fills missing features with the fitted median /
          mode (same as training-time imputation), and maps unseen
          categorical values to the most common training code.
        """
        if not rows:
            raise ValueError("No rows provided")
        if len(rows) > self.settings.max_batch_predict:
            raise ValueError(
                f"Batch too large: {len(rows)} rows (max {self.settings.max_batch_predict})"
            )

        pre = self.preprocessor
        features = self.features
        frame = pd.DataFrame(rows)

        # unknown columns -> drop; missing feature columns -> impute
        extra = [c for c in frame.columns if c not in features]
        if extra:
            log.info("Ignoring unknown input columns: %s", extra)
            frame = frame.drop(columns=extra)
        if frame.shape[1] == 0 or not any(c in features for c in frame.columns):
            raise ValueError(
                "None of the provided columns are model features. "
                "See GET /api/prediction/features for the accepted schema."
            )

        for col in features:
            if col not in frame.columns:
                if col in pre.categorical_cols:
                    frame[col] = self._fallback_code(col)
                else:
                    frame[col] = pre.fill_values.get(col, 0.0)

        out = pre.transform(frame[features])

        # unseen categorical values -> most common training code
        for col in pre.categorical_cols:
            codes = set(pre.encodings[col].values())
            unknown = ~out[col].isin(codes)
            if unknown.any():
                out.loc[unknown, col] = self._fallback_code(col)
        return out

    def _fallback_code(self, col: str) -> float:
        """Code used when a categorical is missing or has an unseen value."""
        cached = self._cat_fallback.get(col)
        if cached is not None:
            return float(cached)
        codes = self.preprocessor.encodings.get(col, {})
        return float(max(codes.values(), default=0.0))

    # ------------------------------------------------------------------ #
    # Strict input validation (Phase 11)
    # ------------------------------------------------------------------ #
    def validate_rows_strict(self, rows: list[dict]) -> None:
        """Reject invalid user input for the public prediction API.

        Raises :class:`ValueError` (mapped to HTTP 400 by the API) when any
        row is missing a model feature, contains an unknown feature, carries
        a NaN/Infinity, or uses a non-numeric type. ``Grid_ID`` is allowed as
        a metadata key. Never silently imputes missing features for user
        input — imputation is reserved for the internal grid pipeline.
        """
        if not rows:
            raise ValueError("No rows provided")
        features = self.features
        allowed_extra = {"Grid_ID"}
        for i, row in enumerate(rows):
            if not isinstance(row, dict):
                raise ValueError(f"Row {i}: expected an object of feature values.")
            unknown = set(row) - set(features) - allowed_extra
            if unknown:
                raise ValueError(
                    f"Row {i}: unknown feature(s) {sorted(unknown)}. "
                    f"Expected: {features}"
                )
            missing = set(features) - set(row)
            if missing:
                raise ValueError(
                    f"Row {i}: missing feature(s) {sorted(missing)}. "
                    f"Expected all {len(features)} features."
                )
            for key in features:
                value = row[key]
                if value is None:
                    raise ValueError(f"Row {i}: feature '{key}' is missing (None).")
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    raise ValueError(
                        f"Row {i}: feature '{key}' has an invalid type "
                        f"{type(value).__name__} (expected a number)."
                    )
                if not math.isfinite(float(value)):
                    raise ValueError(
                        f"Row {i}: feature '{key}' is not finite (NaN/Infinity)."
                    )

    def predict_rows(self, rows: list[dict]) -> list[float]:
        X = self.transform_rows(rows)
        pred = self.model.predict(X)
        return [float(v) for v in np.asarray(pred).ravel()]

    # ------------------------------------------------------------------ #
    # Simulation support
    # ------------------------------------------------------------------ #
    def sample_grid(self, size: int | None = None) -> pd.DataFrame:
        """Feature matrix for simulation (optionally a random sample)."""
        X = self.x_all
        if size and size < len(X):
            return X.sample(n=size, random_state=42)
        return X
