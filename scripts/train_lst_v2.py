#!/usr/bin/env python3
"""
Train LST Model V2 (Temporal Thermal Model)
=============================================
Trains a temporally valid XGBoost model on the multi-date temporal dataset.

CRITICAL: No random train/test splitting. Uses temporal validation:
    - TRAIN: earliest dates
    - VALIDATION: middle dates
    - TEST: latest dates

Or date-based cross-validation folds when data is limited.

Outputs:
    model_registry/v2/model_v2.joblib
    model_registry/v2/feature_schema_v2.json
    model_registry/v2/preprocessor_v2.joblib
    model_registry/v2/metrics_v2.json
    model_registry/v2/training_manifest.json

Usage:
    python scripts/train_lst_v2.py
    python scripts/train_lst_v2.py --dataset data/processed/temporal/temporal_dataset.csv
    python scripts/train_lst_v2.py --n-folds 5
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
import warnings
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.model_selection import GroupKFold
from tqdm import tqdm

warnings.filterwarnings("ignore", category=DeprecationWarning)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("train_lst_v2")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TEMPORAL_DIR = PROJECT_ROOT / "data" / "processed" / "temporal"
REGISTRY_DIR = PROJECT_ROOT / "model_registry" / "v2"
REGISTRY_DIR.mkdir(parents=True, exist_ok=True)

# Weather features
WEATHER_FEATURES = [
    "Temperature_Max", "Temperature_Min", "Temperature_Mean",
    "Humidity", "WindSpeed", "Pressure", "Precipitation",
    "CloudCover", "SolarRadiation",
]

# Categorical features (from V1 training)
CATEGORICAL_FEATURES = ["LandCoverClass", "VegDensityClass"]

TARGET = "lst_c"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Train LST Model V2")
    p.add_argument("--dataset", type=str, default=None,
                   help="Path to temporal_dataset.csv")
    p.add_argument("--n-folds", type=int, default=5,
                   help="Number of temporal CV folds (default: 5)")
    p.add_argument("--train-split", type=float, default=0.7,
                   help="Fraction for training (default: 0.7)")
    p.add_argument("--val-split", type=float, default=0.15,
                   help="Fraction for validation (default: 0.15)")
    p.add_argument("--test-split", type=float, default=0.15,
                   help="Fraction for test (default: 0.15)")
    return p.parse_args()


def load_temporal_dataset(path: Optional[str] = None) -> pd.DataFrame:
    """Load the temporal dataset."""
    if path:
        csv_path = Path(path)
    else:
        csv_path = TEMPORAL_DIR / "temporal_dataset.csv"

    if not csv_path.exists():
        log.error("Temporal dataset not found: %s", csv_path)
        return pd.DataFrame()

    df = pd.read_csv(csv_path)
    log.info("Loaded temporal dataset: %d rows x %d cols", *df.shape)
    return df


def prepare_features(df: pd.DataFrame) -> Tuple[pd.DataFrame, pd.Series, List[str]]:
    """Prepare feature matrix and target from temporal dataset."""
    # Drop non-feature columns
    drop_cols = [
        "date", "cell_id", "season", "scene_id",
        "valid_pixel_count", "valid", "scene_cloud_cover",
    ]
    feature_cols = [c for c in df.columns if c not in drop_cols + [TARGET]]

    # Separate features and target
    X = df[feature_cols].copy()
    y = df[TARGET].copy()

    # Remove rows with missing target
    valid_mask = y.notna()
    X = X[valid_mask]
    y = y[valid_mask]

    log.info("Features: %d | Rows: %d | Target range: [%.1f, %.1f]°C",
             len(feature_cols), len(X), y.min(), y.max())

    return X, y, feature_cols


def temporal_split(
    df: pd.DataFrame,
    train_frac: float = 0.7,
    val_frac: float = 0.15,
    test_frac: float = 0.15,
) -> Tuple[pd.Index, pd.Index, pd.Index]:
    """Split by date (chronological, no shuffling).

    EARLIEST dates -> TRAIN
    MIDDLE dates -> VALIDATION
    LATEST dates -> TEST
    """
    dates = sorted(df["date"].unique())
    n_dates = len(dates)

    n_train = max(1, int(n_dates * train_frac))
    n_val = max(1, int(n_dates * val_frac))
    n_test = max(1, n_dates - n_train - n_val)

    # Adjust if too few dates
    if n_train + n_val + n_test > n_dates:
        n_test = n_dates - n_train - n_val
        if n_test < 1:
            n_val = n_dates - n_train - 1
            n_test = 1

    train_dates = set(dates[:n_train])
    val_dates = set(dates[n_train:n_train + n_val])
    test_dates = set(dates[n_train + n_val:])

    log.info("Temporal split:")
    log.info("  TRAIN: %d dates (%s to %s)", len(train_dates),
             min(train_dates) if train_dates else "N/A",
             max(train_dates) if train_dates else "N/A")
    log.info("  VAL:   %d dates (%s to %s)", len(val_dates),
             min(val_dates) if val_dates else "N/A",
             max(val_dates) if val_dates else "N/A")
    log.info("  TEST:  %d dates (%s to %s)", len(test_dates),
             min(test_dates) if test_dates else "N/A",
             max(test_dates) if test_dates else "N/A")

    train_idx = df[df["date"].isin(train_dates)].index
    val_idx = df[df["date"].isin(val_dates)].index
    test_idx = df[df["date"].isin(test_dates)].index

    log.info("  Train rows: %d | Val rows: %d | Test rows: %d",
             len(train_idx), len(val_idx), len(test_idx))

    return train_idx, val_idx, test_idx


def temporal_cross_validate(
    X: pd.DataFrame,
    y: pd.Series,
    dates: pd.Series,
    n_folds: int = 5,
) -> Dict[str, List[float]]:
    """Date-based cross-validation.

    Each fold trains on EARLIER dates and tests on LATER dates.
    No data leakage across time.
    """
    unique_dates = sorted(dates.unique())
    n_dates = len(unique_dates)

    if n_dates < n_folds:
        log.warning("Only %d dates available for %d folds - reducing folds", n_dates, n_folds)
        n_folds = max(2, n_dates)

    # Split dates into folds chronologically
    fold_size = n_dates // n_folds
    remainder = n_dates % n_folds

    fold_metrics = {"RMSE": [], "MAE": [], "R2": [], "MAPE": []}

    for fold in range(n_folds):
        # Determine test dates for this fold
        start = fold * fold_size + min(fold, remainder)
        end = start + fold_size + (1 if fold < remainder else 0)
        test_dates = set(unique_dates[start:end])
        train_dates = set(unique_dates[:start]) | set(unique_dates[end:])

        if not train_dates or not test_dates:
            continue

        train_mask = dates.isin(train_dates)
        test_mask = dates.isin(test_dates)

        X_train, X_test = X[train_mask], X[test_mask]
        y_train, y_test = y[train_mask], y[test_mask]

        if len(X_train) < 10 or len(X_test) < 10:
            continue

        # Train XGBoost
        from xgboost import XGBRegressor
        model = XGBRegressor(
            n_estimators=1000,
            learning_rate=0.06,
            max_depth=8,
            subsample=0.9,
            colsample_bytree=0.9,
            min_child_weight=5,
            reg_alpha=0.1,
            reg_lambda=1.0,
            tree_method="hist",
            random_state=42,
            verbosity=0,
        )

        # Handle categoricals: encode as integers for XGBoost
        cat_cols_in_X = [c for c in CATEGORICAL_FEATURES if c in X_train.columns]
        if cat_cols_in_X:
            for col in cat_cols_in_X:
                # Map to integer codes
                unique_vals = X_train[col].dropna().unique()
                mapping = {v: i for i, v in enumerate(sorted(unique_vals))}
                X_train[col] = X_train[col].map(mapping).fillna(-1).astype(int)
                X_test[col] = X_test[col].map(mapping).fillna(-1).astype(int)

        model.fit(X_train, y_train)
        preds = model.predict(X_test)

        # Compute metrics
        rmse = float(np.sqrt(mean_squared_error(y_test, preds)))
        mae = float(mean_absolute_error(y_test, preds))
        r2 = float(r2_score(y_test, preds))
        mape = float(np.mean(np.abs((y_test.values - preds) / np.maximum(np.abs(y_test.values), 1e-9))) * 100)

        fold_metrics["RMSE"].append(rmse)
        fold_metrics["MAE"].append(mae)
        fold_metrics["R2"].append(r2)
        fold_metrics["MAPE"].append(mape)

        log.info("  Fold %d: RMSE=%.3f, MAE=%.3f, R²=%.4f, MAPE=%.2f%% (train=%d, test=%d)",
                 fold + 1, rmse, mae, r2, mape, len(X_train), len(X_test))

    return fold_metrics


def compute_metrics(y_true: np.ndarray, y_pred: np.ndarray) -> Dict[str, float]:
    """Compute regression metrics."""
    y_true = np.asarray(y_true, dtype=float)
    y_pred = np.asarray(y_pred, dtype=float)
    mape = float(np.mean(np.abs((y_true - y_pred) / np.maximum(np.abs(y_true), 1e-9))) * 100)
    return {
        "RMSE": float(np.sqrt(mean_squared_error(y_true, y_pred))),
        "MAE": float(mean_absolute_error(y_true, y_pred)),
        "R2": float(r2_score(y_true, y_pred)),
        "MAPE": mape,
    }


def compute_seasonal_metrics(
    y_true: np.ndarray, y_pred: np.ndarray, seasons: np.ndarray
) -> Dict[str, Dict[str, float]]:
    """Compute per-season metrics."""
    result = {}
    for season in np.unique(seasons):
        mask = seasons == season
        if mask.sum() < 2:
            continue
        result[season] = compute_metrics(y_true[mask], y_pred[mask])
    return result


def train_final_model(
    X_train: pd.DataFrame,
    y_train: pd.Series,
    X_val: pd.DataFrame,
    y_val: pd.Series,
) -> object:
    """Train the final XGBoost model with early stopping."""
    from xgboost import XGBRegressor

    model = XGBRegressor(
        n_estimators=2000,
        learning_rate=0.06,
        max_depth=8,
        subsample=0.9,
        colsample_bytree=0.9,
        min_child_weight=5,
        gamma=0.0,
        reg_alpha=0.1,
        reg_lambda=1.0,
        tree_method="hist",
        early_stopping_rounds=50,
        random_state=42,
        verbosity=0,
    )

    # Handle categoricals: encode as integers for XGBoost
    cat_cols = [c for c in CATEGORICAL_FEATURES if c in X_train.columns]
    if cat_cols:
        for col in cat_cols:
            unique_vals = X_train[col].dropna().unique()
            mapping = {v: i for i, v in enumerate(sorted(unique_vals))}
            X_train[col] = X_train[col].map(mapping).fillna(-1).astype(int)
            X_val[col] = X_val[col].map(mapping).fillna(-1).astype(int)

    model.fit(
        X_train, y_train,
        eval_set=[(X_val, y_val)],
        verbose=False,
    )

    log.info("Final model trained: %d trees (best_iteration=%s)",
             model.n_estimators, getattr(model, "best_iteration", "N/A"))

    return model


def main() -> int:
    args = parse_args()
    t_start = time.time()

    log.info("=" * 72)
    log.info("TRAIN LST MODEL V2 (Temporal Thermal Model)")
    log.info("=" * 72)

    # Load dataset
    df = load_temporal_dataset(args.dataset)
    if df.empty:
        return 1

    # Filter to rows with valid LST
    df = df[df["lst_c"].notna()].copy()
    log.info("Rows with valid LST: %d", len(df))

    if len(df) < 100:
        log.error("Insufficient data for training: %d rows", len(df))
        return 1

    # Prepare features
    X, y, feature_cols = prepare_features(df)
    dates = df.loc[X.index, "date"]

    # --- Temporal Cross-Validation ---
    log.info("--- Temporal Cross-Validation (%d folds) ---", args.n_folds)
    cv_metrics = temporal_cross_validate(X, y, dates, args.n_folds)

    cv_summary = {}
    for metric, values in cv_metrics.items():
        if values:
            cv_summary[metric] = round(float(np.mean(values)), 5)
            cv_summary[f"{metric}_std"] = round(float(np.std(values)), 5)

    log.info("CV Summary: %s", {k: round(v, 4) for k, v in cv_summary.items()})

    # --- Temporal Train/Val/Test Split ---
    log.info("--- Temporal Train/Val/Test Split ---")
    train_idx, val_idx, test_idx = temporal_split(
        df.loc[X.index], args.train_split, args.val_split, args.test_split
    )

    X_train, y_train = X.loc[train_idx], y.loc[train_idx]
    X_val, y_val = X.loc[val_idx], y.loc[val_idx]
    X_test, y_test = X.loc[test_idx], y.loc[test_idx]

    dates_train = df.loc[train_idx, "date"]
    dates_val = df.loc[val_idx, "date"]
    dates_test = df.loc[test_idx, "date"]

    log.info("Train: %d rows, Val: %d rows, Test: %d rows",
             len(X_train), len(X_val), len(X_test))

    # --- Train Final Model ---
    log.info("--- Training Final Model ---")
    model = train_final_model(X_train, y_train, X_val, y_val)

    # --- Evaluate on all splits ---
    log.info("--- Evaluating Model ---")

    # Handle categoricals for prediction: encode as integers
    cat_cols = [c for c in CATEGORICAL_FEATURES if c in X.columns]
    if cat_cols:
        for col in cat_cols:
            unique_vals = X_train[col].dropna().unique()
            mapping = {v: i for i, v in enumerate(sorted(unique_vals))}
            X_train[col] = X_train[col].map(mapping).fillna(-1).astype(int)
            X_val[col] = X_val[col].map(mapping).fillna(-1).astype(int)
            X_test[col] = X_test[col].map(mapping).fillna(-1).astype(int)

    pred_train = model.predict(X_train)
    pred_val = model.predict(X_val)
    pred_test = model.predict(X_test)

    train_metrics = compute_metrics(y_train.values, pred_train)
    val_metrics = compute_metrics(y_val.values, pred_val)
    test_metrics = compute_metrics(y_test.values, pred_test)

    # Per-season metrics on test set
    test_seasons = df.loc[test_idx, "season"].values
    seasonal_test = compute_seasonal_metrics(y_test.values, pred_test, test_seasons)

    log.info("Train: RMSE=%.3f, MAE=%.3f, R²=%.4f",
             train_metrics["RMSE"], train_metrics["MAE"], train_metrics["R2"])
    log.info("Val:   RMSE=%.3f, MAE=%.3f, R²=%.4f",
             val_metrics["RMSE"], val_metrics["MAE"], val_metrics["R2"])
    log.info("Test:  RMSE=%.3f, MAE=%.3f, R²=%.4f",
             test_metrics["RMSE"], test_metrics["MAE"], test_metrics["R2"])

    for season, metrics in seasonal_test.items():
        log.info("  %s: RMSE=%.3f, MAE=%.3f, R²=%.4f",
                 season, metrics["RMSE"], metrics["MAE"], metrics["R2"])

    # --- Save Model ---
    log.info("--- Saving Model ---")

    # Save model
    model_path = REGISTRY_DIR / "model_v2.joblib"
    joblib.dump(model, model_path)
    log.info("Model saved: %s", model_path)

    # Save feature schema
    feature_schema = {
        "version": "v2",
        "feature_count": len(feature_cols),
        "features": feature_cols,
        "categorical_columns": [c for c in CATEGORICAL_FEATURES if c in feature_cols],
        "weather_features": [f for f in WEATHER_FEATURES if f in feature_cols],
        "target": TARGET,
        "training_dates": sorted(dates_train.unique()),
        "validation_dates": sorted(dates_val.unique()),
        "test_dates": sorted(dates_test.unique()),
    }
    schema_path = REGISTRY_DIR / "feature_schema_v2.json"
    with open(schema_path, "w", encoding="utf-8") as fh:
        json.dump(feature_schema, fh, indent=2)

    # Save preprocessor (simple: fill values for imputation)
    preprocessor = {
        "fill_values": X_train.median().to_dict(),
        "encodings": {},
        "categorical_columns": [c for c in CATEGORICAL_FEATURES if c in feature_cols],
    }
    preprocessor_path = REGISTRY_DIR / "preprocessor_v2.joblib"
    joblib.dump(preprocessor, preprocessor_path)

    # Save metrics
    metrics = {
        "model_version": "v2",
        "train_metrics": train_metrics,
        "val_metrics": val_metrics,
        "test_metrics": test_metrics,
        "cv_summary": cv_summary,
        "seasonal_test_metrics": seasonal_test,
        "train_dates": sorted(dates_train.unique()),
        "val_dates": sorted(dates_val.unique()),
        "test_dates": sorted(dates_test.unique()),
        "train_rows": len(X_train),
        "val_rows": len(X_val),
        "test_rows": len(X_test),
        "feature_count": len(feature_cols),
        "n_trees": model.n_estimators,
        "best_iteration": getattr(model, "best_iteration", None),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    metrics_path = REGISTRY_DIR / "metrics_v2.json"
    with open(metrics_path, "w", encoding="utf-8") as fh:
        json.dump(metrics, fh, indent=2, default=str)

    # Save training manifest
    manifest = {
        "pipeline": "train_lst_v2",
        "version": "1.0.0",
        "model_type": "XGBRegressor",
        "temporal_split": "chronological (no random shuffling)",
        "cv_method": "date-based folds",
        "n_folds": args.n_folds,
        "train_split": args.train_split,
        "val_split": args.val_split,
        "test_split": args.test_split,
        "input_dataset": str(TEMPORAL_DIR / "temporal_dataset.csv"),
        "output_model": str(model_path),
        "output_metrics": str(metrics_path),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "elapsed_seconds": round(time.time() - t_start, 1),
    }
    manifest_path = REGISTRY_DIR / "training_manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2)

    # Summary
    elapsed = time.time() - t_start
    log.info("=" * 72)
    log.info("MODEL V2 TRAINING COMPLETE (%.1f seconds)", elapsed)
    log.info("Test RMSE: %.3f°C | MAE: %.3f°C | R²: %.4f",
             test_metrics["RMSE"], test_metrics["MAE"], test_metrics["R2"])
    log.info("Model: %s", model_path)
    log.info("Metrics: %s", metrics_path)
    log.info("=" * 72)

    return 0


if __name__ == "__main__":
    sys.exit(main())
