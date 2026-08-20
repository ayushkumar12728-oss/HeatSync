"""
Hyper-parameter optimisation (Optuna)
=====================================
STEP 6 - 100 trials tuning:

    * learning rate / eta
    * max depth
    * number of estimators (via early stopping)
    * subsample (row sampling)
    * gamma (min split loss)
    * L1/L2 regularisation (alpha / lambda)

Every trial trains on a 90/10 split of the training set with early stopping
(so n_estimators is tuned implicitly) and is scored by validation RMSE.
The final model is re-evaluated later with full 5-fold CV.
"""

from __future__ import annotations

import logging
import time
from typing import Dict, Optional, Tuple

import numpy as np
import pandas as pd
import optuna
from optuna.samplers import TPESampler
from tqdm import tqdm

from model_training import compute_metrics

log = logging.getLogger("aie.hyperparameter")

optuna.logging.set_verbosity(optuna.logging.WARNING)


class HyperparameterOptimizer:
    """Optuna search over the XGBoost hyper-parameter space."""

    def __init__(self, cfg, factory):
        self.cfg = cfg
        self.factory = factory
        self.best_params: Optional[Dict] = None
        self.best_value: Optional[float] = None
        self.study: Optional[optuna.Study] = None

    # ------------------------------------------------------------------ #
    def _objective(self, trial: optuna.Trial, X_tr, y_tr) -> float:
        ocfg = self.cfg.optuna
        params = {
            "learning_rate": trial.suggest_float("learning_rate",
                                                 ocfg.min_learning_rate,
                                                 ocfg.max_learning_rate, log=True),
            "max_depth": trial.suggest_int("max_depth", 3, 14),
            "n_estimators": trial.suggest_int("n_estimators", 100, 3000, step=100),
            "subsample": trial.suggest_float("subsample", 0.5, 1.0),
            "colsample_bytree": trial.suggest_float("colsample_bytree", 0.5, 1.0),
            "gamma": trial.suggest_float("gamma", 0.0, 5.0),
            "reg_alpha": trial.suggest_float("reg_alpha", 1e-8, 10.0, log=True),
            "reg_lambda": trial.suggest_float("reg_lambda", 1e-8, 10.0, log=True),
            "min_child_weight": trial.suggest_int("min_child_weight", 1, 20),
        }
        # internal validation split (90/10) for early stopping
        n_es = max(500, int(len(X_tr) * ocfg.val_fraction))
        X_es, X_t = X_tr.iloc[:n_es], X_tr.iloc[n_es:]
        y_es, y_t = y_tr.iloc[:n_es], y_tr.iloc[n_es:]

        model, fit_kwargs = self.factory.build("XGBoost", params)
        try:
            model.fit(X_t, y_t, eval_set=[(X_es, y_es)], verbose=False, **fit_kwargs)
            pred = model.predict(X_es)
            rmse = float(np.sqrt(np.mean((y_es.values - pred) ** 2)))
            return rmse
        except Exception as exc:  # noqa: BLE001
            log.error("Trial %d failed: %s", trial.number, exc)
            return float("inf")

    # ------------------------------------------------------------------ #
    def optimize(self, X_train: pd.DataFrame, y_train: pd.Series,
                 n_trials: Optional[int] = None) -> Tuple[Dict, float]:
        """Run the Optuna study. Returns (best_params, best_rmse)."""
        ocfg = self.cfg.optuna
        n_trials = n_trials or ocfg.n_trials
        log.info("=" * 72)
        log.info("STEP 6 - Optuna optimisation (%d trials)", n_trials)
        log.info("=" * 72)
        t0 = time.time()

        sampler = TPESampler(seed=ocfg.random_state)
        self.study = optuna.create_study(
            direction="minimize", sampler=sampler,
            study_name="uhi_xgboost", storage=None, load_if_exists=False,
        )

        pbar = tqdm(total=n_trials, desc="Optuna trials", ncols=100)
        completed = [0]

        def _cb(study: optuna.Study, trial: optuna.FrozenTrial) -> None:
            pbar.update(1)
            completed[0] += 1

        self.study.optimize(
            lambda t: self._objective(t, X_train, y_train),
            n_trials=n_trials,
            timeout=ocfg.timeout_seconds,
            callbacks=[_cb],
            show_progress_bar=False,
        )
        pbar.close()

        self.best_params = self.study.best_params
        self.best_value = float(self.study.best_value)
        log.info("Optuna finished in %.1fs. Best validation RMSE=%.4f",
                 time.time() - t0, self.best_value)
        log.info("Best params: %s", self.best_params)

        # ensure n_estimators is generous; early stopping decides the count
        self.best_params.setdefault("n_estimators", 3000)
        return self.best_params, self.best_value
