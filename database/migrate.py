#!/usr/bin/env python3
"""
Lightweight SQL migration runner
================================
Applies ``database/migrations/*.sql`` in filename order against a PostgreSQL
database, tracking applied migrations in a ``schema_migrations`` table.

Usage::

    python database/migrate.py --url postgresql://admin:password@localhost:5432/urban_digital_twin

``DATABASE_URL`` is used when ``--url`` is not given.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
log = logging.getLogger("migrate")

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--url", default=None, help="SQLAlchemy database URL "
                   "(default: $DATABASE_URL)")
    args = p.parse_args()

    url = args.url or __import__("os").environ.get("DATABASE_URL")
    if not url:
        print("ERROR: provide --url or set DATABASE_URL")
        return 1

    try:
        from sqlalchemy import create_engine, text
    except ImportError:
        print("ERROR: sqlalchemy is required (pip install -r requirements.txt)")
        return 1

    engine = create_engine(url, pool_pre_ping=True)
    migrations = sorted(MIGRATIONS_DIR.glob("*.sql"))
    if not migrations:
        print(f"No migrations found in {MIGRATIONS_DIR}")
        return 1

    with engine.begin() as conn:
        conn.execute(text(
            "CREATE TABLE IF NOT EXISTS schema_migrations "
            "(filename TEXT PRIMARY KEY, applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
        ))
        applied = {row[0] for row in conn.execute(text("SELECT filename FROM schema_migrations"))}

    for path in migrations:
        if path.name in applied:
            log.info("[skip] %s (already applied)", path.name)
            continue
        log.info("[apply] %s", path.name)
        with engine.begin() as conn:
            conn.execute(text(path.read_text(encoding="utf-8")))
            conn.execute(text("INSERT INTO schema_migrations (filename) VALUES (:f)"),
                         {"f": path.name})
    log.info("Migrations complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
