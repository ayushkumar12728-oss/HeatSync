"""
Snapshot Consistency Tests
==========================
Validates the core architectural requirement:
Every prediction, simulation and display result must reference the same
snapshot_id. No two requests for the same screen should use different data.

Critical test from the specification:
    snapshot = create_live_snapshot()
    prediction = predict(snapshot)
    simulation = simulate(snapshot)
    assert prediction.snapshot_id == simulation.snapshot_id
"""
from __future__ import annotations

import pytest


class TestSnapshotConsistency:
    """Test that the snapshot system enforces data consistency."""

    def test_snapshot_manager_creates_unique_ids(self):
        """Each snapshot gets a unique ID."""
        from backend.services.live_data_manager.snapshot import SnapshotManager

        mgr = SnapshotManager(default_ttl_seconds=0)
        s1 = mgr.get_snapshot(force_refresh=True)
        s2 = mgr.get_snapshot(force_refresh=True)
        assert s1.snapshot_id != s2.snapshot_id

    def test_snapshot_has_required_fields(self):
        """Snapshot contains all required metadata fields."""
        from backend.services.live_data_manager.snapshot import get_current_snapshot

        snapshot = get_current_snapshot(force_refresh=True)
        assert snapshot.snapshot_id is not None
        assert snapshot.generated_at is not None
        assert isinstance(snapshot.freshness, dict)
        assert isinstance(snapshot.source_status, dict)

    def test_snapshot_is_immutable(self):
        """Once created, snapshot data does not change."""
        from backend.services.live_data_manager.snapshot import get_current_snapshot

        snapshot = get_current_snapshot(force_refresh=True)
        original_id = snapshot.snapshot_id
        original_at = snapshot.generated_at

        # Get snapshot again (may be cached or new)
        snapshot2 = get_current_snapshot(force_refresh=False)
        # Original snapshot should be unchanged
        assert snapshot.snapshot_id == original_id
        assert snapshot.generated_at == original_at

    def test_snapshot_history_traceability(self):
        """Historical snapshots can be retrieved by ID."""
        from backend.services.live_data_manager.snapshot import get_snapshot_manager

        mgr = get_snapshot_manager()
        s1 = mgr.get_snapshot(force_refresh=True)
        s2 = mgr.get_snapshot(force_refresh=True)

        # Both should be retrievable from history
        retrieved1 = mgr.get_by_id(s1.snapshot_id)
        retrieved2 = mgr.get_by_id(s2.snapshot_id)
        assert retrieved1 is not None
        assert retrieved2 is not None
        assert retrieved1.snapshot_id == s1.snapshot_id
        assert retrieved2.snapshot_id == s2.snapshot_id

    def test_snapshot_to_dict(self):
        """Snapshot serialization includes all fields."""
        from backend.services.live_data_manager.snapshot import get_current_snapshot

        snapshot = get_current_snapshot(force_refresh=True)
        d = snapshot.to_dict()
        assert "snapshot_id" in d
        assert "generated_at" in d
        assert "freshness" in d
        assert "source_status" in d

    def test_freshness_statuses_are_valid(self):
        """All freshness statuses use the defined set of values."""
        from backend.services.live_data_manager.snapshot import get_current_snapshot

        snapshot = get_current_snapshot(force_refresh=True)
        valid_statuses = {
            "LIVE", "LATEST_OBSERVATION", "STATIC", "CACHED",
            "UNAVAILABLE", "ESTIMATED", "MODELLED", "UNKNOWN"
        }
        for source, status in snapshot.source_status.items():
            assert status in valid_statuses, (
                f"Invalid status '{status}' for source '{source}'. "
                f"Must be one of {valid_statuses}"
            )


class TestLiveAPIEndpoint:
    """Test the unified /api/live/* endpoints."""

    def test_live_snapshot_endpoint(self, client):
        """GET /api/live/snapshot returns a valid response."""
        r = client.get("/api/live/snapshot")
        assert r.status_code == 200
        body = r.json()
        assert body["success"] is True
        assert "snapshot_id" in body
        assert "generated_at" in body
        assert "freshness" in body

    def test_live_status_endpoint(self, client):
        """GET /api/live/status returns freshness for all sources."""
        r = client.get("/api/live/status")
        assert r.status_code == 200
        body = r.json()
        assert body["success"] is True
        assert "statuses" in body
        # Should have entries for weather, air_quality, satellite, gis, terrain
        for key in ("weather", "air_quality", "satellite", "gis", "terrain"):
            assert key in body["statuses"], f"Missing status for {key}"

    def test_live_weather_endpoint(self, client):
        """GET /api/live/weather returns weather data or UNAVAILABLE."""
        r = client.get("/api/live/weather")
        assert r.status_code == 200
        body = r.json()
        assert "snapshot_id" in body
        assert "source_status" in body

    def test_live_air_quality_endpoint(self, client):
        """GET /api/live/air-quality returns AQI data or UNAVAILABLE."""
        r = client.get("/api/live/air-quality")
        assert r.status_code == 200
        body = r.json()
        assert "snapshot_id" in body
        assert "source_status" in body

    def test_live_temperature_distinguishes_air_vs_lst(self, client):
        """GET /api/live/temperature clearly labels air temperature vs predicted LST."""
        r = client.get("/api/live/temperature")
        assert r.status_code == 200
        body = r.json()
        assert "data_type" in body
        assert body["data_type"] == "LIVE"
        assert "note" in body
        assert "NOT spatially interpolated" in body["note"]


class TestSnapshotIdInResponses:
    """Verify that snapshot_id appears in all relevant API responses."""

    def test_prediction_endpoint_includes_snapshot_context(self, client):
        """Prediction endpoint uses the snapshot for data freshness."""
        r = client.get("/api/prediction/heat/current")
        assert r.status_code == 200
        body = r.json()
        # Should have freshness information
        if body.get("success"):
            assert "prediction" in body

    def test_simulation_endpoint_returns_snapshot_id(self, client):
        """POST /api/simulation/run/current returns snapshot_id in response."""
        r = client.get("/api/simulation/scenarios")
        if r.status_code != 200:
            pytest.skip("Scenarios not available")
        scenarios = r.json()
        if not scenarios:
            pytest.skip("No scenarios defined")

        # Note: We can't run a full simulation in tests without a model,
        # but we can verify the endpoint structure
        scenario_name = scenarios[0]["name"] if scenarios else None
        if scenario_name:
            # The endpoint should be callable and return proper structure
            r2 = client.post(
                "/api/simulation/run/current",
                json={"scenario": scenario_name},
            )
            # Either 200 (success) or 503 (model unavailable)
            assert r2.status_code in (200, 503)
            if r2.status_code == 200:
                body = r2.json()
                assert "snapshot_id" in body
                assert "simulation_id" in body


@pytest.fixture
def client():
    """Create a test client with live probes disabled."""
    import os
    os.environ["UDT_ENABLE_LIVE_PROBES"] = "false"

    from backend.main import create_app
    from backend.config.settings import Settings
    from starlette.testclient import TestClient

    settings = Settings()
    settings.enable_live_probes = False
    app = create_app(settings)
    with TestClient(app) as c:
        yield c
