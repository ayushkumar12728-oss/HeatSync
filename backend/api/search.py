"""
City search endpoint (Phase 16)
===============================
A clean backend abstraction over geocoding so the frontend never talks to the
provider directly. The backend proxies OpenStreetMap Nominatim with a bounded
timeout and result limit, then returns provider-neutral results:

    GET /api/search?q=Khandagiri&limit=6

    {
      "status": "available",
      "provider": "OpenStreetMap Nominatim",
      "count": 6,
      "results": [
        {
          "id": "1212",
          "name": "Khandagiri, Bhubaneswar, ...",
          "short_name": "Khandagiri",
          "lat": 20.26, "lng": 85.78,
          "type": "suburb",
          "bounding_box": [[20.0, 85.7], [20.4, 85.9]]
        }
      ]
    }

Failures are structured (``unavailable`` + a stable reason) and never expose
provider internals beyond the provider name. Errors are cached briefly to
avoid hammering Nominatim with a broken query.
"""

from __future__ import annotations

import logging
import threading
import time

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse

from backend.config.settings import Settings, get_settings

log = logging.getLogger("backend.search")

router = APIRouter(prefix="/api/search", tags=["search"])

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
# Bias results to the Bhubaneswar study area.
VIEWBOX = "85.70,20.08,85.95,20.45"
MAX_LIMIT = 10

# short negative cache so a broken query does not retry every keystroke
_neg_cache: dict[str, tuple[float, dict]] = {}
_NEG_CACHE_TTL = 10.0
_neg_lock = threading.Lock()


def _parse_result(r: dict, i: int, query: str) -> dict:
    bb = r.get("boundingbox")
    return {
        "id": str(r.get("place_id") or f"{query}-{i}"),
        "name": r.get("display_name") or r.get("name") or query,
        "short_name": r.get("name") or (r.get("display_name") or query).split(",")[0],
        "lat": float(r.get("lat")),
        "lng": float(r.get("lon")),
        "type": r.get("type") or "place",
        "bounding_box": (
            [[float(bb[0]), float(bb[2])], [float(bb[1]), float(bb[3])]]
            if bb and len(bb) == 4 else None
        ),
    }


def _cached_unavailable(reason: str) -> dict:
    now = time.monotonic()
    with _neg_lock:
        for key in list(_neg_cache):
            if now - _neg_cache[key][0] > _NEG_CACHE_TTL:
                del _neg_cache[key]


def search_places(query: str, limit: int, settings: Settings) -> dict:
    """Real Nominatim search (server-side), returning clean results."""
    params = {
        "q": query,
        "format": "jsonv2",
        "limit": min(limit, MAX_LIMIT),
        "addressdetails": "1",
        "bounded": "1",
        "viewbox": VIEWBOX,
        "viewboxlbrt": VIEWBOX,
        "accept-language": "en",
    }
    try:
        import requests
        response = requests.get(
            NOMINATIM_URL, params=params,
            timeout=settings.live_probe_timeout_seconds,
            headers={"Accept-Language": "en", "User-Agent": "heatsync-urban-digital-twin/1.0"},
        )
        if response.status_code == 429:
            return {"status": "unavailable", "reason": "rate_limit",
                    "provider": "OpenStreetMap Nominatim", "count": 0, "results": []}
        if response.status_code in (401, 403):
            return {"status": "unavailable", "reason": "auth_error",
                    "provider": "OpenStreetMap Nominatim", "count": 0, "results": []}
        response.raise_for_status()
        results = response.json()
    except Exception as exc:  # timeout / DNS / connection / invalid JSON
        log.warning("Nominatim search failed for %r: %s", query[:60], exc)
        return {"status": "unavailable", "reason": "provider_unavailable",
                "provider": "OpenStreetMap Nominatim", "count": 0, "results": []}

    parsed = [_parse_result(r, i, query) for i, r in enumerate(results or [])]
    return {
        "status": "available",
        "provider": "OpenStreetMap Nominatim",
        "count": len(parsed),
        "results": parsed,
    }


@router.get("")
def search(
    q: str = Query(..., min_length=1, max_length=200),
    limit: int = Query(6, ge=1, le=MAX_LIMIT),
    settings: Settings = Depends(get_settings),
) -> JSONResponse:
    """Search places in the study area (provider-neutral response)."""
    query = q.strip()
    if len(query) < 2:
        return JSONResponse(content={
            "status": "unavailable", "reason": "query_too_short",
            "provider": "OpenStreetMap Nominatim", "count": 0, "results": [],
        })

    with _neg_lock:
        cached = _neg_cache.get(query)
        if cached and time.monotonic() - cached[0] < _NEG_CACHE_TTL:
            return JSONResponse(content=cached[1])

    payload = search_places(query, limit, settings)
    if payload.get("status") != "available":
        with _neg_lock:
            _neg_cache[query] = (time.monotonic(), payload)
    return JSONResponse(content=payload)
