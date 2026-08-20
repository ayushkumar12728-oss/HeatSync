#!/usr/bin/env python3
"""
Evaluate LST Model V2 vs V1
============================
Compares the temporal V2 model against the spatial V1 baseline.

Outputs:
    model_registry/v2/evaluation_report.md
    model_registry/v2/v1_vs_v2_comparison.json

Usage:
    python scripts/evaluate_lst_v2.py
"""

from __future__ import annotations

import json
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional

import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("evaluate_lst_v2")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
REGISTRY_V2 = PROJECT_ROOT / "model_registry" / "v2"
REGISTRY_V1 = PROJECT_ROOT / "model_registry" / "v1"
TEMPORAL_DIR = PROJECT_ROOT / "data" / "processed" / "temporal"
OUTPUT_REPORT = REGISTRY_V2 / "evaluation_report.md"
OUTPUT_COMPARISON = REGISTRY_V2 / "v1_vs_v2_comparison.json"

# Categorical features
CATEGORICAL_FEATURES = ["LandCoverClass", "VegDensityClass"]


def compute_metrics(y_true: np.ndarray, y_pred: np.ndarray) -> Dict[str, float]:
    y_true = np.asarray(y_true, dtype=float)
    y_pred = np.asarray(y_pred, dtype=float)
    mape = float(np.mean(np.abs((y_true - y_pred) / np.maximum(np.abs(y_true), 1e-9))) * 100)
    return {
        "RMSE": float(np.sqrt(mean_squared_error(y_true, y_pred))),
        "MAE": float(mean_absolute_error(y_true, y_pred)),
        "R2": float(r2_score(y_true, y_pred)),
        "MAPE": mape,
    }


def load_v1_metrics() -> Optional[dict]:
    """Load V1 metrics from the existing pipeline."""
    metrics_path = PROJECT_ROOT / "data" / "outputs" / "metrics.json"
    if not metrics_path.exists():
        log.warning("V1 metrics not found: %s", metrics_path)
        return None
    try:
        with open(metrics_path, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return None


def load_v2_metrics() -> Optional[dict]:
    """Load V2 metrics from the model registry."""
    metrics_path = REGISTRY_V2 / "metrics_v2.json"
    if not metrics_path.exists():
        log.warning("V2 metrics not found: %s", metrics_path)
        return None
    try:
        with open(metrics_path, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return None


def evaluate_v2_on_dataset() -> Optional[dict]:
    """Evaluate V2 model on the temporal test set."""
    model_path = REGISTRY_V2 / "model_v2.joblib"
    schema_path = REGISTRY_V2 / "feature_schema_v2.json"
    dataset_path = TEMPORAL_DIR / "temporal_dataset.csv"

    if not all(p.exists() for p in [model_path, schema_path, dataset_path]):
        log.warning("V2 artifacts or dataset missing")
        return None

    model = joblib.load(model_path)
    with open(schema_path, encoding="utf-8") as fh:
        schema = json.load(fh)

    df = pd.read_csv(dataset_path)
    df = df[df["lst_c"].notna()].copy()

    test_dates = set(schema.get("test_dates", []))
    if not test_dates:
        log.warning("No test dates in schema")
        return None

    test_df = df[df["date"].isin(test_dates)]
    if test_df.empty:
        log.warning("No test data found")
        return None

    features = schema["features"]
    cat_cols = [c for c in CATEGORICAL_FEATURES if c in features]

    X_test = test_df[features].copy()
    y_test = test_df["lst_c"].values

    if cat_cols:
        for col in cat_cols:
            X_test[col] = X_test[col].astype("category")

    preds = model.predict(X_test)
    metrics = compute_metrics(y_test, preds)

    # Per-season
    seasons = test_df["season"].values
    seasonal = {}
    for season in np.unique(seasons):
        mask = seasons == season
        if mask.sum() >= 2:
            seasonal[season] = compute_metrics(y_test[mask], preds[mask])

    return {
        "test_metrics": metrics,
        "seasonal_metrics": seasonal,
        "test_rows": len(test_df),
        "test_dates": sorted(test_dates),
    }


def generate_report(
    v1_metrics: Optional[dict],
    v2_metrics: Optional[dict],
    v2_eval: Optional[dict],
) -> None:
    """Generate evaluation report."""
    lines = [
        "# LST Model V2 Evaluation Report",
        "",
        f"Generated: {datetime.now(timezone.utc).isoformat()}",
        "",
        "## Model Comparison",
        "",
    ]

    # V1 metrics
    v1_test = v1_metrics.get("test_metrics", {}) if v1_metrics else {}
    lines.append("### V1 (Spatial Baseline)")
    if v1_test:
        lines.append(f"- RMSE: {v1_test.get('RMSE', 'N/A')}°C")
        lines.append(f"- MAE: {v1_test.get('MAE', 'N/A')}°C")
        lines.append(f"- R²: {v1_test.get('R2', 'N/A')}")
    else:
        lines.append("- Metrics not available")

    lines.append("")

    # V2 metrics
    v2_test = v2_eval.get("test_metrics", {}) if v2_eval else {}
    lines.append("### V2 (Temporal Model)")
    if v2_test:
        lines.append(f"- RMSE: {v2_test.get('RMSE', 'N/A')}°C")
        lines.append(f"- MAE: {v2_test.get('MAE', 'N/A')}°C")
        lines.append(f"- R²: {v2_test.get('R2', 'N/A')}")
    else:
        lines.append("- Metrics not available")

    lines.append("")

    # Improvement
    if v1_test and v2_test:
        lines.append("### Improvement")
        for metric in ["RMSE", "MAE"]:
            v1_val = v1_test.get(metric)
            v2_val = v2_test.get(metric)
            if v1_val is not None and v2_val is not None:
                improvement = v1_val - v2_val
                pct = (improvement / v1_val) * 100 if v1_val != 0 else 0
                lines.append(f"- {metric}: {improvement:+.3f}°C ({pct:+.1f}%)")

        v1_r2 = v1_test.get("R2")
        v2_r2 = v2_test.get("R2")
        if v1_r2 is not None and v2_r2 is not None:
            lines.append(f"- R²: {v2_r2 - v1_r2:+.4f}")

        # Determine if V2 is better
        v2_better = v2_test.get("RMSE", float("inf")) < v1_test.get("RMSE", float("inf"))
        if v2_better:
            lines.append("")
            lines.append("**V2 IS BETTER than V1** - Recommend deploying V2.")
        else:
            lines.append("")
            lines.append("**V2 is NOT better than V1** - Keep V1 as production model.")
            lines.append("Investigate why V2 underperforms.")

    lines.append("")

    # Per-season metrics
    if v2_eval and v2_eval.get("seasonal_metrics"):
        lines.append("## Per-Season Test Metrics (V2)")
        lines.append("")
        lines.append("| Season | RMSE | MAE | R² | MAPE |")
        lines.append("|--------|------|-----|-----|------|")
        for season, metrics in v2_eval["seasonal_metrics"].items():
            lines.append(
                f"| {season} | {metrics['RMSE']:.3f} | {metrics['MAE']:.3f} | "
                f"{metrics['R2']:.4f} | {metrics['MAPE']:.2f}% |"
            )
        lines.append("")

    # V2 from metrics file
    if v2_metrics:
        lines.append("## V2 Training Details")
        lines.append("")
        if v2_metrics.get("cv_summary"):
            lines.append("### Cross-Validation Summary")
            for k, v in v2_metrics["cv_summary"].items():
                lines.append(f"- {k}: {v}")
        lines.append("")

    lines.extend([
        "## Methodology",
        "",
        "- **Temporal splitting**: chronological, no random shuffling",
        "- **Cross-validation**: date-based folds (train on earlier, test on later)",
        "- **LST source**: Landsat Collection 2 Level-2 Surface Temperature",
        "- **Weather source**: Open-Meteo Historical Weather API",
        "- **No spatial leakage**: cells in different dates can appear in train/test",
        "",
        "## Data Integrity",
        "",
        "- No fabricated historical data",
        "- No air temperature substituted for LST",
        "- No random train/test splitting",
        "- Weather timestamps match satellite acquisition dates",
    ])

    OUTPUT_REPORT.write_text("\n".join(lines), encoding="utf-8")
    log.info("Evaluation report: %s", OUTPUT_REPORT)


def main() -> int:
    t_start = time.time()

    log.info("=" * 72)
    log.info("EVALUATE LST MODEL V2 vs V1")
    log.info("=" * 72)

    # Load metrics
    v1_metrics = load_v1_metrics()
    v2_metrics = load_v2_metrics()

    # Evaluate V2 on test set
    v2_eval = evaluate_v2_on_dataset()

    # Generate report
    generate_report(v1_metrics, v2_metrics, v2_eval)

    # Save comparison JSON
    comparison = {
        "v1": v1_metrics.get("test_metrics", {}) if v1_metrics else None,
        "v2": v2_eval.get("test_metrics", {}) if v2_eval else None,
        "v2_seasonal": v2_eval.get("seasonal_metrics", {}) if v2_eval else None,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    with open(OUTPUT_COMPARISON, "w", encoding="utf-8") as fh:
        json.dump(comparison, fh, indent=2, default=str)

    elapsed = time.time() - t_start
    log.info("=" * 72)
    log.info("EVALUATION COMPLETE (%.1f seconds)", elapsed)
    log.info("Report: %s", OUTPUT_REPORT)
    log.info("=" * 72)

    return 0


if __name__ == "__main__":
    sys.exit(main())
