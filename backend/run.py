"""Convenience entry point: ``python -m backend.run``."""

from __future__ import annotations

import uvicorn

from backend.config.settings import get_settings


def main() -> None:
    settings = get_settings()
    uvicorn.run(
        "backend.main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.debug,
        log_level=settings.log_level.lower(),
    )


if __name__ == "__main__":
    main()
