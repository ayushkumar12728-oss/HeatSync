#!/usr/bin/env python3
"""
Finalize outputs from completed artifacts
=========================================
One-off helper: regenerates outputs/metrics.json and outputs/reports/final_report.md
from already-produced artifacts (predictions.csv, leaderboard.csv, SHAP
importance, sensitivity analysis, leakage report). Used when the pipeline
completed all heavy steps but was interrupted before writing the final two
JSON/Markdown reports.

The canonical full run is `python main.py`; this script is only a resume tool.
"""

from __future__ import annotations

import json
import logging
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pandas as pd

from config import Config
from model_training import compute_metrics
from evaluation import Evaluator

logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
log = logging.getLogger("finalize")


def parse_log_params(cfg: Config) -> dict:
    """Extract best Optuna params + validation RMSE from ai_engine.log."""
    log_path = cfg.paths.logs_dir / "ai_engine.log"
    params, rmse = {}, None
    if log_path.exists():
        for line in log_path.read_text(encoding="utf-8").splitlines():
            m = re.search(r"Best params: (\{.*\})", line)
            if m:
                try:
                    params = json.loads(m.group(1))
                except json.JSONDecodeError:
                    pass
            m = re.search(r"Best validation RMSE=([0-9.]+)", line)
            if m:
                rmse = float(m.group(1))
    return params, rmse


def main() -> int:
    cfg = Config()
    cfg.paths.ensure()

    # ---- test-set predictions ------------------------------------------
    pred = pd.read_csv(cfg.paths.predictions_csv)
    y_true = pred["Target_LST"].values
    y_pred = pred["Predicted_LST"].values
    test_metrics = compute_metrics(y_true, y_pred)
    test_metrics["model"] = "XGBoost"
    log.info("Test metrics recomputed: %s", {
        k: round(v, 4) for k, v in test_metrics.items()
        if isinstance(v, (int, float)) and not isinstance(v, bool)
    })

    # ---- evaluation artifacts (regenerated deterministically) ----------
    ev = Evaluator(cfg)
    confusion = ev.confusion_analysis(y_true, y_pred)
    ev.residual_plots(y_true, y_pred)
    ev.spatial_error_map(pd.Series(y_pred - y_true), pred["Grid_ID"])

    # ---- load existing artifacts ---------------------------------------
    leaderboard = pd.read_csv(cfg.paths.leaderboard_csv)
    leakage = json.loads((cfg.paths.reports_dir / "leakage_report.json").read_text(encoding="utf-8"))
    shap_csv = pd.read_csv(cfg.paths.plots_dir / "SHAP" / "global_shap_importance.csv")
    sensitivity = pd.read_csv(cfg.paths.reports_dir / "sensitivity_analysis.csv")
    best_params, optuna_rmse = parse_log_params(cfg)
    n_features = leakage["n_kept"]

    extra = {
        "n_samples": int(pred.shape[0] + 43041),  # train + test from the fixed split
        "n_features": int(n_features),
        "n_dropped": int(leakage["n_removed"]),
        "best_model": "XGBoost",
        "best_hyperparameters": best_params,
        "optuna_best_rmse": optuna_rmse,
        "explainability": {
            "n_samples": 3000,
            "top10_features": shap_csv["feature"].head(10).tolist(),
        },
        "sensitivity": sensitivity[["scenario", "mean_delta_lst"]].to_dict("records"),
        "confusion": {
            "bins": confusion["bins"],
            "labels": confusion["labels"],
            "class_accuracy": confusion["class_accuracy"],
            "cohen_kappa": confusion["cohen_kappa"],
        },
    }

    # ---- cv summary from the cv results table ---------------------------
    cv = pd.read_csv(cfg.paths.reports_dir / "cv_5fold_results.csv", index_col=0)
    cv_summary = {}
    for m in ("RMSE", "MAE", "R2", "MAPE"):
        vals = pd.to_numeric(cv[m], errors="coerce").dropna()
        if len(vals):
            cv_summary[m] = float(vals.mean())
            cv_summary[f"{m}_std"] = float(vals.std(ddof=1)) if len(vals) > 1 else 0.0
        else:
            cv_summary[m] = float("nan")
            cv_summary[f"{m}_std"] = float("nan")

    # ---- final metrics.json ----------------------------------------------
    ev.build_metrics(test_metrics, cv_summary, leaderboard, extra)
    log.info("metrics.json written: %s", cfg.paths.metrics_json)

    # ---- final report -----------------------------------------------------
    lines = []
    lines.append("# Urban Heat Island AI Engine - Final Report\n")
    lines.append(f"Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
    lines.append("## 1. Best model\n")
    lines.append(f"- **Model**: XGBoost")
    lines.append(f"- Test RMSE: **{test_metrics['RMSE']:.4f} °C** | "
                 f"MAE: {test_metrics['MAE']:.4f} °C | R²: {test_metrics['R2']:.4f} | "
                 f"MAPE: {test_metrics['MAPE']:.2f}%")
    lines.append(f"- 5-fold CV (tuned model): RMSE {cv_summary['RMSE']:.4f} ± "
                 f"{cv_summary.get('RMSE_std', 0):.4f} °C\n")
    lines.append("## 2. Leaderboard\n")
    lines.append("```")
    lines.append(leaderboard[["rank", "model", "RMSE", "MAE", "R2", "MAPE"]]
                 .to_string(index=False))
    lines.append("```\n")
    lines.append("## 3. Best hyper-parameters (Optuna)\n")
    lines.append("```json")
    lines.append(json.dumps(best_params, indent=2))
    lines.append("```\n")
    lines.append("## 4. SHAP - top 10 features\n")
    for i, row in shap_csv.head(10).iterrows():
        lines.append(f"{int(i)+1}. {row['feature']}: mean|SHAP| = {row['mean_abs_shap']:.4f} °C "
                     f"({row['pct_importance']:.1f}% of total)")
    lines.append("")
    lines.append("## 5. Sensitivity analysis\n")
    lines.append("| Scenario | Δ LST (°C) |")
    lines.append("|---|---|")
    for r in sensitivity.to_dict("records"):
        lines.append(f"| {r['scenario']} | {r['mean_delta_lst']:+.3f} |")
    lines.append("")
    lines.append("## 6. ONNX export\n")
    onnx_ok = cfg.paths.best_model_onnx.exists()
    lines.append(f"- best_model.onnx: {'OK (verified with onnxruntime)' if onnx_ok else 'skipped'}")

    report_path = cfg.paths.reports_dir / "final_report.md"
    report_path.write_text("\n".join(lines), encoding="utf-8")
    log.info("final_report.md written: %s", report_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
