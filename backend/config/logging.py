"""
Structured logging setup for the API
====================================
A single ``get_logger`` entry point that formats logs consistently and, when
``UDT_LOG_FILE`` is set, also writes to a rotating file (never fails the app
if the file cannot be opened).
"""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler

FORMAT = "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def setup_logging(level: str = "INFO", log_file: str | None = None) -> None:
    """Configure the root logger once (idempotent)."""
    root = logging.getLogger()
    if getattr(root, "_udt_configured", False):
        return
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    fmt = logging.Formatter(FORMAT, datefmt=DATE_FORMAT)

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(fmt)
    root.addHandler(console)

    if log_file:
        try:
            # the log directory may not exist yet (e.g. backend/logs/ is
            # git-ignored) - create it so file logging actually works
            from pathlib import Path
            Path(log_file).parent.mkdir(parents=True, exist_ok=True)
            fh = RotatingFileHandler(
                log_file, maxBytes=5 << 20, backupCount=2, encoding="utf-8"
            )
            fh.setFormatter(fmt)
            root.addHandler(fh)
        except OSError:
            # logging must never take the API down
            logging.getLogger("backend.config.logging").warning(
                "Could not open log file %s - console only.", log_file
            )

    root._udt_configured = True  # type: ignore[attr-defined]
    # silence noisy third-party loggers
    for noisy in ("uvicorn.access", "watchfiles"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
