"""
Safe loader for the ai-engine modules
=====================================
The AI engine lives in ``ai-engine/`` (a directory name containing a hyphen,
so it cannot be imported as a regular Python package). This module loads the
individual modules with :func:`importlib.util.spec_from_file_location` under
namespaced aliases (``aie_config``, ``aie_preprocessing``, ...) so the backend
can reuse the *exact same* pipeline code — data loading, column-role
identification, leakage removal, preprocessing and scenario perturbation —
without modifying or duplicating it.
"""

from __future__ import annotations

import importlib.util
import sys
from types import ModuleType

from backend.config.settings import PROJECT_ROOT

AI_ENGINE_DIR = PROJECT_ROOT / "ai-engine"

_LOADED: dict[str, ModuleType] = {}


def _load_module(name: str, relative_path: str) -> ModuleType:
    """Load ``ai-engine/<relative_path>`` once and cache it under ``name``."""
    if name in _LOADED:
        return _LOADED[name]
    path = AI_ENGINE_DIR / relative_path
    if not path.exists():
        raise FileNotFoundError(
            f"AI engine module not found: {path}. The backend requires the "
            "ai-engine source tree."
        )
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot build import spec for {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    _LOADED[name] = module
    return module


def aie_config() -> ModuleType:
    """ai-engine/config.py -> :class:`Config` bundle."""
    return _load_module("aie_config", "config.py")


def aie_data_loader() -> ModuleType:
    """ai-engine/data_loader.py -> :class:`DataLoader`."""
    return _load_module("aie_data_loader", "data_loader.py")


def aie_feature_selection() -> ModuleType:
    """ai-engine/feature_selection.py -> :class:`FeatureSelector`."""
    return _load_module("aie_feature_selection", "feature_selection.py")


def aie_preprocessing() -> ModuleType:
    """ai-engine/preprocessing.py -> :class:`Preprocessor`."""
    return _load_module("aie_preprocessing", "preprocessing.py")


def aie_scenario_simulator() -> ModuleType:
    """ai-engine/scenario_simulator.py -> :class:`ScenarioSimulator`."""
    return _load_module("aie_scenario_simulator", "scenario_simulator.py")
