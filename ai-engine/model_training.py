"""
Model training, cross-validation & comparison
=============================================
STEP 4 - 5-fold cross-validation reporting RMSE / MAE / R2 / MAPE.
STEP 5 - Train six models (RandomForest, XGBoost, LightGBM, CatBoost,
         HistGradientBoosting, ExtraTrees), compare them on the held-out
         test set, write leaderboard.csv and pick the best model.

GPU: XGBoost uses CUDA automatically when available (config.model.use_gpu).
"""

from __future__ import annotations

import logging
import time
import warnings
from typing import Dict, List, Optional, Tuple

warnings.filterwarnings("ignore", category=DeprecationWarning, module="lightgbm")

import numpy as np
import pandas as pd
from sklearn.ensemble import (ExtraTreesRegressor, HistGradientBoostingRegressor,
                              RandomForestRegressor)
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.model_selection import KFold
from tqdm import tqdm

log = logging.getLogger("aie.model_training")


# ---------------------------------------------------------------------- #
# Metrics
# ---------------------------------------------------------------------- #
def compute_metrics(y_true: np.ndarray, y_pred: np.ndarray) -> Dict[str, float]:
    """RMSE, MAE, R2, MAPE (%)."""
    y_true = np.asarray(y_true, dtype=float)
    y_pred = np.asarray(y_pred, dtype=float)
    mape = float(np.mean(np.abs((y_true - y_pred) / np.maximum(np.abs(y_true), 1e-9))) * 100.0)
    return {
        "RMSE": float(np.sqrt(mean_squared_error(y_true, y_pred))),
        "MAE": float(mean_absolute_error(y_true, y_pred)),
        "R2": float(r2_score(y_true, y_pred)),
        "MAPE": mape,
    }


def _is_cuda_available() -> bool:
    try:
        import xgboost as xgb
        info = xgb.build_info()
        return bool(info.get("USE_CUDA"))
    except Exception:
        return False


def _resolve_device(cfg) -> str:
    """'cuda' when enabled and the build supports it, else 'cpu'."""
    if cfg.model.use_gpu and _is_cuda_available():
        try:
            import xgboost as xgb
            import numpy as np
            # smoke test: does a CUDA device actually respond?
            m = xgb.XGBRegressor(n_estimators=2, max_depth=2, tree_method="hist",
                                 device="cuda", verbosity=0)
            X = np.random.rand(64, 4)
            m.fit(X, np.random.rand(64))
            return "cuda"
        except Exception as exc:  # noqa: BLE001
            log.warning("CUDA requested but unusable (%s) - falling back to CPU.", exc)
    return "cpu"


# ---------------------------------------------------------------------- #
# Model factory
# ---------------------------------------------------------------------- #
class ModelFactory:
    """Builds the six competing regressors with consistent, tuned defaults."""

    def __init__(self, cfg):
        self.cfg = cfg
        self.device = _resolve_device(cfg)
        log.info("XGBoost device resolved: %s", self.device)
        self._xgb = None
        self._lgb = None
        self._cat = None

    # --- lazy imports so a missing optional library only kills its model ---
    def _get_xgb(self):
        if self._xgb is None:
            from xgboost import XGBRegressor
            self._xgb = XGBRegressor
        return self._xgb

    def _get_lgb(self):
        if self._lgb is None:
            from lightgbm import LGBMRegressor
            self._lgb = LGBMRegressor
        return self._lgb

    def _get_cat(self):
        if self._cat is None:
            from catboost import CatBoostRegressor
            self._cat = CatBoostRegressor
        return self._cat

    # ------------------------------------------------------------------ #
    def build(self, name: str, params: Optional[Dict] = None) -> Tuple[object, Dict]:
        """Return (model, fit_kwargs). fit_kwargs holds per-model extras."""
        mcfg = self.cfg.model
        p = params or {}
        if name == "RandomForest":
            kw = {**mcfg.rf, **p}
            return RandomForestRegressor(**kw), {}
        if name == "ExtraTrees":
            kw = {**mcfg.extratrees, **p}
            return ExtraTreesRegressor(**kw), {}
        if name == "HistGradientBoosting":
            kw = {**mcfg.hgb, **p}
            return HistGradientBoostingRegressor(**kw), {}
        if name == "XGBoost":
            kw = {**mcfg.xgb, **p}
            kw["device"] = self.device
            kw["random_state"] = mcfg.random_state
            kw["eval_metric"] = "rmse"   # constructor-only in XGBoost 3.x
            if self.device == "cuda":
                kw["tree_method"] = "hist"
            return self._get_xgb()(**kw), {}
        if name == "LightGBM":
            kw = {**mcfg.lgb, **p}
            kw["random_state"] = mcfg.random_state
            kw["n_jobs"] = mcfg.n_jobs
            return self._get_lgb()(**kw), {"eval_metric": "rmse"}
        if name == "CatBoost":
            kw = {**mcfg.cat, **p}
            kw["thread_count"] = mcfg.n_jobs
            kw["allow_writing_files"] = False
            kw["eval_metric"] = "RMSE"   # constructor-only in CatBoost 1.2+
            return self._get_cat()(**kw), {}
        raise ValueError(f"Unknown model: {name}")

    # ------------------------------------------------------------------ #
    def fit_with_early_stopping(self, name: str, model, fit_kwargs: Dict,
                                X_tr: pd.DataFrame, y_tr: pd.Series,
                                X_va: pd.DataFrame, y_va: pd.Series) -> object:
        """Fit with an internal validation split for early stopping."""
        if name == "RandomForest" or name == "ExtraTrees":
            model.fit(X_tr, y_tr)
            return model
        if name == "HistGradientBoosting":
            # early_stopping handled inside the estimator
            model.fit(X_tr, y_tr)
            return model
        if name == "XGBoost":
            model.fit(X_tr, y_tr, eval_set=[(X_va, y_va)], verbose=False, **fit_kwargs)
            return model
        if name == "LightGBM":
            model.fit(X_tr, y_tr, eval_set=[(X_va, y_va)], **fit_kwargs)
            return model
        if name == "CatBoost":
            # LandCoverClass / VegDensityClass are ordinal float codes, so they
            # are passed as numeric features (CatBoost rejects float-typed
            # cat_features); ordinal coding is fully appropriate here.
            model.fit(X_tr, y_tr, eval_set=(X_va, y_va),
                      use_best_model=True, **fit_kwargs)
            return model
        raise ValueError(f"Unknown model: {name}")

    # ------------------------------------------------------------------ #
    def model_names(self) -> List[str]:
        return ["RandomForest", "ExtraTrees", "HistGradientBoosting",
                "XGBoost", "LightGBM", "CatBoost"]


# ---------------------------------------------------------------------- #
# Training logic
# ---------------------------------------------------------------------- #
class ModelTrainer:
    """Cross-validation + model comparison + leaderboard."""

    MODELS = ["RandomForest", "ExtraTrees", "HistGradientBoosting",
              "XGBoost", "LightGBM", "CatBoost"]

    def __init__(self, cfg, factory: ModelFactory):
        self.cfg = cfg
        self.factory = factory
        self.cv_results: Dict[str, Dict] = {}
        self.leaderboard: pd.DataFrame = pd.DataFrame()
        self.best_model_name: Optional[str] = None
        self.best_model = None
        self.best_metrics: Dict[str, float] = {}

    # ------------------------------------------------------------------ #
    def cross_validate(self, X: pd.DataFrame, y: pd.Series, name: str,
                       params: Optional[Dict] = None, n_folds: Optional[int] = None,
                       use_early_stopping: bool = True,
                       progress: Optional[tqdm] = None) -> Dict[str, Dict[str, float]]:
        """5-fold CV with per-fold early stopping. Returns {fold: metrics}."""
        n_folds = n_folds or self.cfg.split.cv_folds
        kf = KFold(n_splits=n_folds, shuffle=True, random_state=self.cfg.split.random_state)
        X = X.reset_index(drop=True)
        y = y.reset_index(drop=True)
        fold_metrics: Dict[str, Dict[str, float]] = {}
        for fold, (tr_idx, va_idx) in enumerate(kf.split(X), start=1):
            X_tr, X_va = X.iloc[tr_idx], X.iloc[va_idx]
            y_tr, y_va = y.iloc[tr_idx], y.iloc[va_idx]
            model, fit_kwargs = self.factory.build(name, params)
            try:
                if use_early_stopping:
                    # carve 10% of the fold for early stopping
                    n_es = max(500, int(len(X_tr) * 0.10))
                    X_es, X_t = X_tr.iloc[:n_es], X_tr.iloc[n_es:]
                    y_es, y_t = y_tr.iloc[:n_es], y_tr.iloc[n_es:]
                    self.factory.fit_with_early_stopping(name, model, fit_kwargs,
                                                         X_t, y_t, X_es, y_es)
                else:
                    model.fit(X_tr, y_tr)
                pred = model.predict(X_va)
            except Exception as exc:  # noqa: BLE001
                log.error("Model %s failed on fold %d: %s", name, fold, exc)
                fold_metrics[f"fold_{fold}"] = {m: float("nan") for m in
                                                ("RMSE", "MAE", "R2", "MAPE")}
                continue
            fold_metrics[f"fold_{fold}"] = compute_metrics(y_va.values, pred)
            if progress is not None:
                progress.update(1)
        return fold_metrics

    # ------------------------------------------------------------------ #
    def summarize_cv(self, fold_metrics: Dict[str, Dict[str, float]]) -> Dict[str, float]:
        """Mean +/- std across folds (nan-safe)."""
        df = pd.DataFrame(fold_metrics).T
        summary = {}
        for m in ("RMSE", "MAE", "R2", "MAPE"):
            vals = pd.to_numeric(df[m], errors="coerce").dropna()
            if len(vals):
                summary[m] = float(vals.mean())
                summary[f"{m}_std"] = float(vals.std(ddof=1)) if len(vals) > 1 else 0.0
            else:
                summary[m] = float("nan")
                summary[f"{m}_std"] = float("nan")
        return summary

    # ------------------------------------------------------------------ #
    def compare_models(self, X_train, y_train, X_test, y_test,
                       feature_cols: List[str]) -> pd.DataFrame:
        """STEP 5 - train all six models, evaluate on the test set, rank them."""
        rows = []
        log.info("=" * 72)
        log.info("STEP 5 - Model comparison (%d models)", len(self.MODELS))
        log.info("=" * 72)
        with tqdm(total=len(self.MODELS), desc="Model comparison", ncols=100) as pbar:
            for name in self.MODELS:
                t0 = time.time()
                try:
                    model, fit_kwargs = self.factory.build(name)
                    if name in ("XGBoost", "LightGBM", "CatBoost", "HistGradientBoosting"):
                        # early stopping split inside the training set
                        n_es = max(500, int(len(X_train) * 0.10))
                        X_es, X_t = X_train.iloc[:n_es], X_train.iloc[n_es:]
                        y_es, y_t = y_train.iloc[:n_es], y_train.iloc[n_es:]
                        self.factory.fit_with_early_stopping(name, model, fit_kwargs,
                                                             X_t, y_t, X_es, y_es)
                    else:
                        model.fit(X_train, y_train)
                    pred = model.predict(X_test)
                    met = compute_metrics(y_test.values, pred)
                    met["model"] = name
                    met["train_time_s"] = round(time.time() - t0, 2)
                    met["n_estimators_fitted"] = (
                        getattr(model, "n_estimators_", None)
                        or getattr(model, "best_iteration_", None)
                        or getattr(model, "best_iteration", None)
                        or getattr(model, "tree_count_", None)
                    )
                    rows.append(met)
                    log.info("  %-22s RMSE=%.4f  MAE=%.4f  R2=%.4f  MAPE=%.2f%%  (%.1fs)",
                             name, met["RMSE"], met["MAE"], met["R2"], met["MAPE"],
                             met["train_time_s"])
                except Exception as exc:  # noqa: BLE001
                    log.error("Model %s failed during comparison: %s", name, exc)
                    rows.append({"model": name, "RMSE": float("nan"), "MAE": float("nan"),
                                 "R2": float("nan"), "MAPE": float("nan"),
                                 "train_time_s": round(time.time() - t0, 2),
                                 "n_estimators_fitted": None, "error": str(exc)})
                pbar.update(1)

        leaderboard = pd.DataFrame(rows).sort_values("RMSE").reset_index(drop=True)
        leaderboard.insert(0, "rank", np.arange(1, len(leaderboard) + 1))
        self.leaderboard = leaderboard

        best_row = leaderboard.dropna(subset=["RMSE"]).iloc[0]
        self.best_model_name = str(best_row["model"])
        self.best_metrics = {
            "RMSE": float(best_row["RMSE"]), "MAE": float(best_row["MAE"]),
            "R2": float(best_row["R2"]), "MAPE": float(best_row["MAPE"]),
        }
        log.info("Leaderboard (best = %s):", self.best_model_name)
        log.info("\n%s", leaderboard[["rank", "model", "RMSE", "MAE", "R2", "MAPE",
                                      "train_time_s"]].to_string(index=False))
        return leaderboard

    # ------------------------------------------------------------------ #
    def save_leaderboard(self, path) -> None:
        if self.leaderboard is not None and len(self.leaderboard):
            self.leaderboard.to_csv(path, index=False)
            log.info("Leaderboard written: %s", path)

    # ------------------------------------------------------------------ #
    def train_final(self, name: str, X_train, y_train, X_test, y_test,
                    params: Optional[Dict] = None) -> Tuple[object, Dict[str, float]]:
        """Train on the full training split with early-stopping split; eval on test."""
        model, fit_kwargs = self.factory.build(name, params)
        n_es = max(500, int(len(X_train) * 0.10))
        X_es, X_t = X_train.iloc[:n_es], X_train.iloc[n_es:]
        y_es, y_t = y_train.iloc[:n_es], y_train.iloc[n_es:]
        self.factory.fit_with_early_stopping(name, model, fit_kwargs, X_t, y_t, X_es, y_es)
        pred = model.predict(X_test)
        metrics = compute_metrics(y_test.values, pred)
        metrics["model"] = name
        self.best_model = model
        log.info("Final %s model -> test %s", name,
                 {k: round(v, 4) for k, v in metrics.items() if k != "model"})
        return model, metrics
