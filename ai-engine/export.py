"""
Model export (STEP 7)
=====================
Save the trained best model as:

    * best_model.pkl   - joblib dump (full sklearn-compatible object)
    * best_model.onnx  - ONNX graph, verified against onnxruntime

The ONNX conversion uses onnxmltools' XGBoost booster converter (opset 15),
which is the supported path for XGBoost 3.x sklearn models. If conversion is
not possible on the machine, the pipeline logs a warning and continues.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import List, Optional

import joblib
import numpy as np

log = logging.getLogger("aie.export")


class ModelExporter:
    """Serialises the final model to pkl + onnx."""

    def __init__(self, cfg):
        self.cfg = cfg

    # ------------------------------------------------------------------ #
    def save_pkl(self, model, path: Optional[Path] = None) -> Path:
        path = path or self.cfg.paths.best_model_pkl
        path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(model, path)
        size_mb = os.path.getsize(path) / 1e6
        log.info("Model saved (joblib): %s (%.1f MB)", path, size_mb)
        return path

    # ------------------------------------------------------------------ #
    def export_onnx(self, model, feature_cols: List[str],
                    path: Optional[Path] = None) -> Optional[Path]:
        """Convert the fitted XGBoost booster to ONNX and verify with onnxruntime."""
        path = path or self.cfg.paths.best_model_onnx
        if not hasattr(model, "get_booster"):
            log.warning("Model %s has no XGBoost booster - ONNX export skipped. "
                        "best_model.pkl remains the primary artifact.",
                        type(model).__name__)
            return None
        try:
            from onnxmltools import convert_xgboost
            from onnxmltools.convert.common.data_types import FloatTensorType

            booster = model.get_booster().copy()  # never mutate the live model
            # onnxmltools' XGBoost converter only accepts 'f%d' feature names.
            if booster.feature_names and not all(
                n.startswith("f") and n[1:].isdigit() for n in booster.feature_names
            ):
                booster.feature_names = [f"f{i}" for i in range(len(booster.feature_names))]
            initial_types = [("input", FloatTensorType([None, len(feature_cols)]))]
            onnx_model = convert_xgboost(booster, initial_types=initial_types,
                                         target_opset=15)

            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "wb") as fh:
                fh.write(onnx_model.SerializeToString())

            # ---- verify round-trip against onnxruntime -------------------
            import onnx
            import onnxruntime as ort
            onnx.checker.check_model(onnx_model)
            rng = np.random.default_rng(0)
            X_sample = rng.normal(size=(8, len(feature_cols))).astype(np.float32)
            sess = ort.InferenceSession(str(path), providers=["CPUExecutionProvider"])
            onnx_pred = sess.run(None, {"input": X_sample})[0].ravel()
            sklearn_pred = model.predict(X_sample)
            max_diff = float(np.max(np.abs(onnx_pred - sklearn_pred)))
            log.info("ONNX exported: %s (max |diff| vs sklearn = %.2e)", path, max_diff)
            return path
        except Exception as exc:  # noqa: BLE001
            log.error("ONNX export failed (%s) - best_model.pkl remains the "
                      "primary artifact.", exc)
            return None
