"""Shared test fixtures and markers.

Model-dependent tests are skipped automatically when the trained artifacts
(trained model + training dataset) are not present, so CI on a fresh checkout
still runs the artifact-free coverage.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

# Keep system health tests deterministic and offline: live probes (OpenWeather
# weather/AQI, Nominatim search) report a clear unavailable state instead of
# making network calls. Set before any Settings instance is created.
os.environ.setdefault("UDT_ENABLE_LIVE_PROBES", "false")
# Disable the in-memory rate limiter for the general suite (it is global state
# and would 429 the multi-scenario tests); rate limiting has its own test.
os.environ.setdefault("UDT_RATE_LIMIT_ENABLED", "false")

ROOT = Path(__file__).resolve().parent.parent

MODEL_PKL = ROOT / "models" / "best_model.pkl"
DATASET_CSV = (ROOT / "data" / "feature_engineering"
               / "training_dataset.csv")

requires_artifacts = pytest.mark.skipif(
    not (MODEL_PKL.exists() and DATASET_CSV.exists()),
    reason="trained model / training dataset not present - run the pipeline first",
)


@pytest.fixture(scope="module")
def client():
    """TestClient against the real application factory."""
    from fastapi.testclient import TestClient

    from backend.main import create_app

    with TestClient(create_app()) as c:
        yield c


@pytest.fixture()
def offline_ai_client(client):
    """Force an unconfigured Nemotron client (no key) for AI tests.

    Deterministic regardless of whether a real NEMOTRON_API_KEY exists in
    .env on the developer machine: the ask endpoint returns
    ``configuration_required`` and never makes a network call.
    """
    from backend.api import ai as ai_module

    original = ai_module.get_ai_client

    def _no_key():
        from backend.services.nemotron import NemotronClient, NemotronConfig
        return NemotronClient(NemotronConfig(
            api_key=None,
            base_url="https://integrate.api.nvidia.com/v1",
            model="nvidia/nvidia-nemotron-nano-9b-v2",
            timeout_seconds=5.0,
            max_retries=0,
            max_tokens=512,
            temperature=0.2,
        ))

    client.app.dependency_overrides[ai_module.get_ai_client] = _no_key
    yield client
    client.app.dependency_overrides.pop(ai_module.get_ai_client, None)
    ai_module.get_ai_client = original
