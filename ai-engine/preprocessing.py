


"""
Preprocessing & data split
===========================
STEP 3 - After leakage removal:

    * Handle missing values (median imputation for numerics, mode for categoricals).
    * Encode categorical columns (ordinal codes; kept as-is for CatBoost which
      receives explicit categorical feature indices).
    * 80% / 20% train-test split with random seed 42.

The fitted encoder is stored so the same transform can be applied later to
scenario simulations and full-grid predictions.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split

log = logging.getLogger("aie.preprocessing")


class Preprocessor:
    """Fitted column metadata + train/test splitter."""

    def __init__(self, cfg):
        self.cfg = cfg
        self.categorical_cols: List[str] = []
        self.numeric_cols: List[str] = []
        # column -> fitted imputation value
        self.fill_values: Dict[str, float] = {}
        # column -> {original value: encoded code}
        self.encodings: Dict[str, Dict] = {}

    # ------------------------------------------------------------------ #
    def fit(self, df: pd.DataFrame, categorical_cols: List[str]) -> None:
        """Learn imputation values + label encodings from a DataFrame."""
        self.categorical_cols = sorted(set(categorical_cols) & set(df.columns))
        self.numeric_cols = [c for c in df.columns if c not in self.categorical_cols]

        for c in df.columns:
            if df[c].isna().any():
                if c in self.categorical_cols:
                    self.fill_values[c] = df[c].mode().iloc[0]
                else:
                    self.fill_values[c] = df[c].median()
        for c in self.categorical_cols:
            values = df[c].dropna().unique()
            self.encodings[c] = {v: i for i, v in enumerate(sorted(values))}

    # ------------------------------------------------------------------ #
    def transform(self, df: pd.DataFrame) -> pd.DataFrame:
        """Apply imputation + encoding. Returns a new DataFrame."""
        out = df.copy()
        for c, val in self.fill_values.items():
            out[c] = out[c].fillna(val)
        for c, mapping in self.encodings.items():
            out[c] = out[c].map(mapping).astype(float)
        return out

    # ------------------------------------------------------------------ #
    def fit_transform(self, df: pd.DataFrame, categorical_cols: List[str]) -> pd.DataFrame:
        self.fit(df, categorical_cols)
        return self.transform(df)

    # ------------------------------------------------------------------ #
    def split(self, X: pd.DataFrame, y: pd.Series) -> Tuple[pd.DataFrame, pd.DataFrame,
                                                             pd.Series, pd.Series]:
        """80/20 train-test split, random_state = 42."""
        cfg = self.cfg.split
        log.info("Train/test split: test_size=%.2f, random_state=%d",
                 cfg.test_size, cfg.random_state)
        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=cfg.test_size, random_state=cfg.random_state, shuffle=True
        )
        log.info("Split done: train=%d, test=%d", len(X_train), len(X_test))
        return X_train, X_test, y_train, y_test
