"""Tests for rate limiting (Phase 25) and request IDs (Phase 27)."""

from __future__ import annotations

import pytest


@pytest.fixture()
def limited_client():
    """App with a tiny simulation limit so 429 is deterministic."""
    from fastapi.testclient import TestClient

    from backend.config.settings import Settings
    from backend.main import create_app

    settings = Settings(
        enable_live_probes=False,
        rate_limit_enabled=True,
        rate_limit_ai_per_minute=2,
        rate_limit_sim_per_minute=2,
    )
    with TestClient(create_app(settings)) as c:
        yield c


def test_request_id_header_present(client):
    """Every response carries a traceable X-Request-Id."""
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.headers.get("X-Request-Id")


def test_request_id_preserves_incoming(client):
    """An incoming x-request-id is preserved (Phase 27)."""
    r = client.get("/api/health", headers={"X-Request-Id": "trace-abc-123"})
    assert r.headers.get("X-Request-Id") == "trace-abc-123"


def test_simulation_run_rate_limited(limited_client):
    """POST /api/simulation/run returns 429 after the per-minute budget."""
    payload = {"scenario": "increase_trees"}
    statuses = []
    for _ in range(4):
        r = limited_client.post("/api/simulation/run", json=payload)
        statuses.append(r.status_code)
    # first two allowed (budget 2/min), the rest limited
    assert statuses[:2] == [200, 200], statuses
    assert all(s == 429 for s in statuses[2:]), statuses
    body = limited_client.post("/api/simulation/run", json=payload).json()
    assert body["status"] == "rate_limit"


def test_ai_ask_rate_limited(limited_client):
    payload = {"question": "Why is this area hot?"}
    statuses = []
    for _ in range(4):
        r = limited_client.post("/api/ai/ask", json=payload)
        statuses.append(r.status_code)
    assert statuses[:2] == [200, 200], statuses
    assert all(s == 429 for s in statuses[2:]), statuses


def test_rate_limit_not_applied_to_health(client):
    """Health endpoints are never rate limited."""
    for _ in range(30):
        assert client.get("/api/health").status_code == 200


def test_rate_limit_cleared_by_settings_disable():
    """UDT_RATE_LIMIT_ENABLED=false disables the limiter entirely."""
    from fastapi.testclient import TestClient

    from backend.config.settings import Settings
    from backend.main import create_app

    settings = Settings(enable_live_probes=False, rate_limit_enabled=False,
                        rate_limit_sim_per_minute=1)
    with TestClient(create_app(settings)) as c:
        for _ in range(5):
            r = c.post("/api/simulation/run", json={"scenario": "increase_trees"})
            assert r.status_code in (200, 503)  # never 429
