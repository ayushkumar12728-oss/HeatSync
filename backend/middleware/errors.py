"""
Centralised exception handling
==============================
Converts expected failures (missing artefacts, bad requests) into clean JSON
responses and hides stack traces from clients unless debug mode is on.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

log = logging.getLogger("backend.errors")


def register_exception_handlers(app: FastAPI, debug: bool = False) -> None:
    @app.exception_handler(FileNotFoundError)
    async def _missing_artifact(_: Request, exc: FileNotFoundError):
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"detail": str(exc), "code": "artifact_missing"},
        )

    @app.exception_handler(ValueError)
    async def _bad_request(_: Request, exc: ValueError):
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"detail": str(exc), "code": "invalid_request"},
        )

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError):
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={"detail": exc.errors(), "code": "validation_error"},
        )

    @app.exception_handler(Exception)
    async def _unexpected(request: Request, exc: Exception):
        log.exception("Unhandled error on %s %s",
                      request.method, request.url.path)
        if debug:
            return JSONResponse(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                content={"detail": str(exc), "code": "internal_error"},
            )
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"detail": "Internal server error", "code": "internal_error"},
        )
