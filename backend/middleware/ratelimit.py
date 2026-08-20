"""
Lightweight rate limiting (Phase 25)
=====================================
A simple in-memory, fixed-window limiter for expensive endpoints (AI calls,
scenario runs). It exists to stop accidental frontend loops from generating
hundreds of paid/external requests — not to be a production-grade distributed
throttle. Suitable for local/demo use.

    GET /api/system/health   -> no limit (health checks are cheap)
    POST /api/ai/ask         -> limited (paid NIM calls)
    POST /api/simulation/run -> limited (expensive full-grid XGBoost runs)

Limits are configurable via environment:

    UDT_RATE_LIMIT_ENABLED=true|false   (default true)
    UDT_RATE_LIMIT_AI_PER_MINUTE=20     (default 20 asks/minute/IP)
    UDT_RATE_LIMIT_SIM_PER_MINUTE=10    (default 10 runs/minute/IP)

The limiter is applied inside the endpoint handlers (not as middleware) so it
can read the request IP and respond with a clean 429 JSON body.
"""

from __future__ import annotations

import threading
import time

from fastapi import Request
from fastapi.responses import JSONResponse

# path-prefix -> (limit per minute, label)
_LIMITS: list[tuple[str, int, str]] = [
    ("/api/ai/ask", 20, "ai"),
    ("/api/simulation/run", 10, "simulation"),
]

_ENABLED = True


def configure_rate_limits(enabled: bool | None = None,
                          ai_per_minute: int | None = None,
                          sim_per_minute: int | None = None) -> None:
    """Update limits at startup from settings (idempotent)."""
    global _ENABLED, _limits
    if enabled is not None:
        _ENABLED = enabled
    new_limits: list[tuple[str, int, str]] = []
    for prefix, _limit, label in _LIMITS:
        if label == "ai" and ai_per_minute is not None:
            new_limits.append((prefix, ai_per_minute, label))
        elif label == "simulation" and sim_per_minute is not None:
            new_limits.append((prefix, sim_per_minute, label))
        else:
            new_limits.append((prefix, _limit, label))
    _LIMITS[:] = new_limits
    # rebuild the active limiters so changed limits take effect immediately
    _limits = {
        label: _FixedWindowLimiter(limit)
        for _prefix, limit, label in _LIMITS
    }


class _FixedWindowLimiter:
    """Fixed-window counter per (prefix, ip). Thread-safe, self-cleaning."""

    def __init__(self, limit: int, window_seconds: float = 60.0):
        self.limit = limit
        self.window = window_seconds
        self._lock = threading.Lock()
        self._buckets: dict[tuple[str, str], tuple[int, float]] = {}

    def allow(self, key: tuple[str, str]) -> bool:
        now = time.monotonic()
        with self._lock:
            count, start = self._buckets.get(key, (0, now))
            if now - start >= self.window:
                count, start = 0, now
            if count >= self.limit:
                self._buckets[key] = (count, start)
                return False
            self._buckets[key] = (count + 1, start)
            # opportunistic cleanup (bounded memory)
            if len(self._buckets) > 10_000:
                cutoff = now - self.window
                self._buckets = {
                    k: v for k, v in self._buckets.items() if v[1] > cutoff
                }
            return True


_limits: dict[str, _FixedWindowLimiter] = {
    label: _FixedWindowLimiter(limit)
    for _prefix, limit, label in _LIMITS
}


def client_ip(request: Request) -> str:
    """Best-effort client IP (respects X-Forwarded-For only when proxied)."""
    if request.app.state.settings.trust_proxy:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def check_rate_limit(request: Request) -> JSONResponse | None:
    """Return a 429 response when the request exceeds its limit, else None."""
    if not _ENABLED:
        return None
    path = request.url.path
    ip = client_ip(request)
    for prefix, _limit, label in _LIMITS:
        if path.startswith(prefix):
            limiter = _limits[label]
            if not limiter.allow((ip, path)):
                return JSONResponse(
                    status_code=429,
                    content={
                        "success": False,
                        "status": "rate_limit",
                        "message": (
                            f"Too many requests to {path} — try again in a moment. "
                            f"Limit: {limiter.limit} per minute."
                        ),
                    },
                    headers={"Retry-After": str(int(limiter.window))},
                )
    return None
