#!/usr/bin/env python3
"""
Urban Heat Island AI Engine - master entry point
================================================
Predicts Urban Heat Island intensity (Target_LST) for every 100 m grid
cell of the Bhubaneswar urban digital twin.

Run::

    cd ai-engine
    python main.py

Pipeline (11 steps):
  1. Load dataset + auto-identify column roles
  2. Remove leakage features  -> outputs/reports/leakage_report.json
  3. Train/test split (80/20, seed 42)
  4. 5-fold cross-validation (RMSE, MAE, R2, MAPE)
  5. Model comparison (6 models) -> outputs/leaderboard.csv
  6. Optuna hyper-parameter optimisation (100 trials)
  7. Train final model -> models/best_model.pkl + best_model.onnx
  8. SHAP explainability -> outputs/plots/SHAP/
  9. Sensitivity analysis (green/building/tree/park/water)
 10. Full-grid prediction -> predictions.csv, Predicted_LST.{geojson,tif,png}
 11. Evaluation -> metrics.json, confusion, residual, spatial error maps
"""

from __future__ import annotations

import json
import logging
import sys
import time
import traceback
from pathlib import Path

import pandas as pd
from tqdm import tqdm

# allow running from any working directory (python ai-engine/main.py or cd ai-engine)
sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import Config  # noqa: E402
from data_loader import DataLoader  # noqa: E402
from feature_selection import FeatureSelector  # noqa: E402
from preprocessing import Preprocessor  # noqa: E402
from model_training import ModelFactory, ModelTrainer, compute_metrics  # noqa: E402
from hyperparameter import HyperparameterOptimizer  # noqa: E402
from export import ModelExporter  # noqa: E402
from explainability import SHAPExplainer  # noqa: E402
from scenario_simulator import ScenarioSimulator  # noqa: E402
from prediction import GridPredictor  # noqa: E402
from evaluation import Evaluator  # noqa: E402

LOG_FORMAT = "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"


def setup_logging(cfg: Config) -> None:
    cfg.paths.ensure()
    logging.basicConfig(
        level=getattr(logging, cfg.log_level.upper(), logging.INFO),
        format=LOG_FORMAT,
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(cfg.log_path, encoding="utf-8"),
        ],
    )


def banner(text: str) -> None:
    logging.getLogger("aie.main").info("=" * 72)
    logging.getLogger("aie.main").info(text)
    logging.getLogger("aie.main").info("=" * 72)


def main() -> int:
    t_start = time.time()
    cfg = Config.from_env()
    setup_logging(cfg)
    log = logging.getLogger("aie.main")
    log.info("Urban Heat Island AI Engine starting (seed=%d, test_size=%.0f%%)",
             cfg.split.random_state, cfg.split.test_size * 100)

    try:
        # ------------------------------------------------------------------ #
        # STEP 1 - load data
        # ------------------------------------------------------------------ #
        banner("STEP 1 - Loading dataset & identifying column roles")
        loader = DataLoader(cfg)
        df = loader.load()
        schema = loader.report()
        log.info("Schema summary: %s", {k: len(v) if isinstance(v, list) else v
                                        for k, v in schema.items()})
        target = cfg.data.target

        # ------------------------------------------------------------------ #
        # STEP 2 - remove leakage features
        # ------------------------------------------------------------------ #
        banner("STEP 2 - Removing leakage features")
        selector = FeatureSelector(cfg, schema)
        df_clean, features = selector.run(df)
        selector.save_report(cfg.paths.reports_dir / "leakage_report.json")

        # ------------------------------------------------------------------ #
        # STEP 3 - preprocess + split
        # ------------------------------------------------------------------ #
        banner("STEP 3 - Preprocessing & 80/20 split (seed 42)")
        pre = Preprocessor(cfg)
        X = pre.fit_transform(df_clean[features], schema["categorical_columns"])
        y = df[target]
        X_train, X_test, y_train, y_test = pre.split(X, y)

        factory = ModelFactory(cfg)
        trainer = ModelTrainer(cfg, factory)

        # ------------------------------------------------------------------ #
        # STEP 4 - 5-fold cross-validation (reference: default XGBoost)
        # ------------------------------------------------------------------ #
        banner("STEP 4 - 5-fold cross-validation (reference XGBoost)")
        with tqdm(total=cfg.split.cv_folds, desc="5-fold CV", ncols=100) as pbar:
            cv_folds = trainer.cross_validate(X_train, y_train, "XGBoost",
                                              progress=pbar)
        cv_summary = trainer.summarize_cv(cv_folds)
        pd.DataFrame(cv_folds).T.to_csv(cfg.paths.reports_dir / "cv_5fold_results.csv")
        log.info("5-fold CV (XGBoost): %s",
                 {k: round(v, 4) for k, v in cv_summary.items()})

        # ------------------------------------------------------------------ #
        # STEP 5 - model comparison + leaderboard
        # ------------------------------------------------------------------ #
        banner("STEP 5 - Model comparison (6 models)")
        leaderboard = trainer.compare_models(X_train, y_train, X_test, y_test, features)
        trainer.save_leaderboard(cfg.paths.leaderboard_csv)
        best_name = trainer.best_model_name
        log.info("Best model from leaderboard: %s (test RMSE=%.4f)",
                 best_name, trainer.best_metrics["RMSE"])

        # ------------------------------------------------------------------ #
        # STEP 6 - Optuna hyper-parameter optimisation
        # ------------------------------------------------------------------ #
        banner("STEP 6 - Optuna hyper-parameter optimisation (100 trials)")
        optimizer = HyperparameterOptimizer(cfg, factory)
        best_params, best_rmse = optimizer.optimize(X_train, y_train)
        # reduce risk of overfitting val split: keep a robust n_estimators cap
        best_params["n_estimators"] = 3000

        # ------------------------------------------------------------------ #
        # STEP 7 - train final model + export
        # ------------------------------------------------------------------ #
        banner("STEP 7 - Training final model & exporting artifacts")
        # Optuna tuned the XGBoost space; only apply those params to XGBoost.
        final_params = best_params if best_name == "XGBoost" else None
        final_model, final_test_metrics = trainer.train_final(
            best_name, X_train, y_train, X_test, y_test, params=final_params
        )
        exporter = ModelExporter(cfg)
        exporter.save_pkl(final_model, cfg.paths.best_model_pkl)
        onnx_path = exporter.export_onnx(final_model, features, cfg.paths.best_model_onnx)

        # 5-fold CV of the *final* tuned model (same protocol as STEP 4)
        log.info("Running 5-fold CV on the tuned final model ...")
        with tqdm(total=cfg.split.cv_folds, desc="Final CV", ncols=100) as pbar:
            final_cv_folds = trainer.cross_validate(X_train, y_train, best_name,
                                                    params=best_params,
                                                    progress=pbar)
        final_cv_summary = trainer.summarize_cv(final_cv_folds)
        log.info("Final tuned model 5-fold CV: %s",
                 {k: round(v, 4) for k, v in final_cv_summary.items()})

        # ------------------------------------------------------------------ #
        # STEP 8 - SHAP explainability
        # ------------------------------------------------------------------ #
        banner("STEP 8 - SHAP explainability")
        shap_explainer = SHAPExplainer(cfg)
        sample_idx = X_test.sample(
            n=min(cfg.explainability.global_sample, len(X_test)),
            random_state=cfg.split.random_state
        ).index
        X_sample = X_test.loc[sample_idx]
        y_sample = y_test.loc[sample_idx]
        shap_result = shap_explainer.run_all(final_model, X_sample, y_sample, features)

        # ------------------------------------------------------------------ #
        # STEP 9 - sensitivity analysis
        # ------------------------------------------------------------------ #
        # Run on the full grid (all 53,802 cells) so the stored aggregate
        # results agree with the live API runs and the cell-level scenario
        # outputs (previously computed on the 20% test set, which produced
        # slightly different means).
        banner("STEP 9 - Sensitivity analysis (green / building / tree / park / water)")
        simulator = ScenarioSimulator(cfg)
        X_all = pre.transform(df_clean[features])
        sensitivity = simulator.run(final_model, X_all, df[target])
        sensitivity_summary = sensitivity[["scenario", "mean_delta_lst"]].to_dict("records")

        # ------------------------------------------------------------------ #
        # STEP 10 - full-grid prediction + rasters
        # ------------------------------------------------------------------ #
        banner("STEP 10 - Full-grid prediction (every 100 m cell) & raster export")
        predictor = GridPredictor(cfg)
        grid_ids = df["Grid_ID"]
        all_pred = predictor.predict_all(final_model, X_all, features, ids=grid_ids)

        test_ids = df.loc[X_test.index, "Grid_ID"]
        predictor.save_predictions_csv(all_pred.loc[X_test.index], y_test, ids=test_ids)

        geojson_path = predictor.export_geojson(all_pred, grid_ids)
        tif_path = predictor.export_tif_png(all_pred, grid_ids)

        # ------------------------------------------------------------------ #
        # STEP 11 - evaluation
        # ------------------------------------------------------------------ #
        banner("STEP 11 - Evaluation")
        evaluator = Evaluator(cfg)

        test_pred = final_model.predict(X_test)
        y_true = y_test.values

        confusion = evaluator.confusion_analysis(y_true, test_pred)
        residual_paths = evaluator.residual_plots(y_true, test_pred)

        test_resid = pd.Series(test_pred - y_true, index=X_test.index)
        eval_spatial = evaluator.spatial_error_map(
            test_resid, df.loc[X_test.index, "Grid_ID"]
        )

        final_metrics = evaluator.build_metrics(
            test_metrics=final_test_metrics,
            cv_summary=final_cv_summary,
            leaderboard=leaderboard,
            extra={
                "n_samples": len(df),
                "n_features": len(features),
                "n_dropped": len(selector.leakage_report["removed"]),
                "best_model": best_name,
                "best_hyperparameters": best_params,
                "optuna_best_rmse": best_rmse,
                "explainability": {
                    "n_samples": shap_result["n_samples"],
                    "expected_value": shap_result["expected_value"],
                    "top10_features": [r["feature"] for r in
                                       shap_result["top_features"][:10]],
                },
                "sensitivity": sensitivity_summary,
                "confusion": {
                    "bins": confusion["bins"],
                    "labels": confusion["labels"],
                    "class_accuracy": confusion["class_accuracy"],
                    "cohen_kappa": confusion["cohen_kappa"],
                },
            },
        )

        # ------------------------------------------------------------------ #
        # Final report
        # ------------------------------------------------------------------ #
        write_final_report(cfg, final_test_metrics, final_cv_summary, leaderboard,
                           best_name, best_params, shap_result, sensitivity,
                           onnx_path is not None)

        elapsed = time.time() - t_start
        log.info("=" * 72)
        log.info("PIPELINE COMPLETE in %.1f minutes", elapsed / 60.0)
        log.info("Outputs: %s", cfg.paths.output_root)
        log.info("=" * 72)
        print_summary(cfg, final_test_metrics, final_cv_summary, best_name,
                      shap_result, sensitivity, elapsed)
        return 0

    except Exception as exc:  # noqa: BLE001
        log.error("Pipeline failed: %s", exc)
        log.error(traceback.format_exc())
        return 1


# ---------------------------------------------------------------------- #
# Reporting helpers
# ---------------------------------------------------------------------- #
def write_final_report(cfg: Config, test_metrics: dict, cv_summary: dict,
                       leaderboard, best_name: str, best_params: dict,
                       shap_result: dict, sensitivity, onnx_ok: bool) -> None:
    """Write outputs/reports/final_report.md with the full explanation."""
    import pandas as pd

    lb = leaderboard.copy()
    lines = []
    lines.append("# Urban Heat Island AI Engine - Final Report\n")
    lines.append(f"Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
    lines.append("## 1. Best model\n")
    lines.append(f"- **Model**: {best_name}")
    lines.append(f"- Test RMSE: **{test_metrics['RMSE']:.4f} °C** | "
                 f"MAE: {test_metrics['MAE']:.4f} °C | "
                 f"R²: {test_metrics['R2']:.4f} | "
                 f"MAPE: {test_metrics['MAPE']:.2f}%")
    lines.append(f"- 5-fold CV (final model): RMSE {cv_summary['RMSE']:.4f} ± "
                 f"{cv_summary.get('RMSE_std', 0):.4f} °C\n")
    lines.append("## 2. Leaderboard\n")
    lines.append("```")
    lines.append(lb[["rank", "model", "RMSE", "MAE", "R2", "MAPE"]]
                 .to_string(index=False))
    lines.append("```\n")
    lines.append("## 3. Best hyper-parameters (Optuna)\n")
    lines.append("```json")
    lines.append(json.dumps(best_params, indent=2))
    lines.append("```\n")
    lines.append("## 4. SHAP - top 10 features\n")
    for i, r in enumerate(shap_result["top_features"][:10], start=1):
        lines.append(f"{i}. {r['feature']}: mean|SHAP| = {r['mean_abs_shap']:.4f} °C "
                     f"({r['pct_importance']:.1f}% of total)")
    lines.append("")
    lines.append("## 5. Sensitivity analysis\n")
    lines.append("| Scenario | Δ LST (°C) |")
    lines.append("|---|---|")
    for r in sensitivity.to_dict("records"):
        lines.append(f"| {r['scenario']} | {r['mean_delta_lst']:+.3f} |")
    lines.append("")
    lines.append(f"## 6. ONNX export\n")
    lines.append(f"- best_model.onnx: {'OK (verified with onnxruntime)' if onnx_ok else 'skipped (see log)'}")

    report_path = cfg.paths.reports_dir / "final_report.md"
    report_path.write_text("\n".join(lines), encoding="utf-8")
    logging.getLogger("aie.main").info("Final report written: %s", report_path)


def print_summary(cfg, test_metrics, cv_summary, best_name, shap_result,
                  sensitivity, elapsed) -> None:
    """Human-readable console summary at the end of the run."""
    print("\n" + "=" * 72)
    print("UHI AI ENGINE - SUMMARY")
    print("=" * 72)
    print(f"Best model        : {best_name}")
    print(f"Test RMSE         : {test_metrics['RMSE']:.4f} °C")
    print(f"Test MAE          : {test_metrics['MAE']:.4f} °C")
    print(f"Test R²           : {test_metrics['R2']:.4f}")
    print(f"Test MAPE         : {test_metrics['MAPE']:.2f}%")
    print(f"5-fold CV RMSE    : {cv_summary['RMSE']:.4f} ± {cv_summary.get('RMSE_std', 0):.4f} °C")
    print("Top SHAP features : " + ", ".join(
        r["feature"] for r in shap_result["top_features"][:6]))
    print("Sensitivity (Δ°C) : " + ", ".join(
        f"{r['scenario']}={r['mean_delta_lst']:+.2f}" for r in
        sensitivity.to_dict("records")[:4]))
    print(f"Runtime           : {elapsed/60:.1f} min")
    print(f"Outputs           : {cfg.paths.output_root}")
    print("=" * 72)


if __name__ == "__main__":
    sys.exit(main())
