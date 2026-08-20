"""
Request logging middleware
==========================
Logs one line per request (request_id, method, path, status, duration).
Health checks are logged at DEBUG so they do not spam the access log.

Request IDs (Phase 27)
----------------------
* An incoming ``x-request-id`` header is preserved when present (useful for
  correlating with an upstream gateway / load balancer).
* Otherwise a short UUID is generated.
* The final ID is echoed back in the ``X-Request-Id`` response header so every
  API response is traceable.
"""

from __future__ import annotations

import logging
import time
from uuid import uuid4

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

log = logging.getLogger("backend.access")


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("x-request-id") or uuid4().hex[:12]
        request.state.request_id = request_id
        start = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            log.exception("request_id=%s %s %s failed",
                          request_id, request.method, request.url.path)
            raise
        duration_ms = (time.perf_counter() - start) * 1000
        level = log.debug if request.url.path.startswith("/api/health") else log.info
        level(
            "request_id=%s method=%s path=%s status=%s duration_ms=%.1f",
            request_id, request.method, request.url.path,
            response.status_code, duration_ms,
        )
        response.headers["X-Request-Id"] = request_id
        return response
