"""Tests for the backend search endpoint (Phase 16)."""

from __future__ import annotations

import pytest


def test_search_requires_query(client):
    r = client.get("/api/search")
    assert r.status_code == 422


def test_search_short_query(client):
    r = client.get("/api/search", params={"q": "a"})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "unavailable"
    assert body["reason"] == "query_too_short"


def test_search_provider_neutral_response(client, monkeypatch):
    """Backend returns clean results; provider internals stay server-side."""
    class _Resp:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return [{
                "place_id": 12345,
                "display_name": "Khandagiri, Bhubaneswar, Odisha, India",
                "name": "Khandagiri",
                "lat": "20.2605",
                "lon": "85.7835",
                "type": "suburb",
                "boundingbox": ["20.25", "20.27", "85.77", "85.79"],
            }]

    import requests
    monkeypatch.setattr(requests, "get", lambda *a, **k: _Resp())
    r = client.get("/api/search", params={"q": "Khandagiri", "limit": 5})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "available"
    assert body["provider"] == "OpenStreetMap Nominatim"
    assert body["count"] == 1
    result = body["results"][0]
    assert result["name"] == "Khandagiri, Bhubaneswar, Odisha, India"
    assert result["short_name"] == "Khandagiri"
    assert result["lat"] == pytest.approx(20.2605)
    assert result["lng"] == pytest.approx(85.7835)
    assert result["type"] == "suburb"
    assert result["bounding_box"] == [[20.25, 85.77], [20.27, 85.79]]
    # no provider internals leaked to the UI
    assert "osm" not in body
    assert "display_name" not in body


def test_search_provider_failure_structured(client, monkeypatch):
    import requests

    def _fail(*a, **k):
        raise requests.exceptions.Timeout("boom")

    monkeypatch.setattr(requests, "get", _fail)
    r = client.get("/api/search", params={"q": "nowhereville"})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "unavailable"
    assert body["reason"] == "provider_unavailable"
    assert body["results"] == []
