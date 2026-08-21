"""
Optional PostgreSQL / PostGIS service
=====================================
The API is artifact-first: by default every endpoint reads the trained model
and pipeline outputs from disk. When ``UDT_DATABASE_URL`` is set (see
``database/seed/load_artifacts.py`` to populate the database), this
service provides PostGIS-backed read access to the grid cells.

The module imports SQLAlchemy lazily so the API runs fine without the
database driver installed.
"""

from __future__ import annotations

import logging

from backend.config.settings import Settings

log = logging.getLogger("backend.database")


class DatabaseService:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._engine = None
        self._unavailable_reason: str | None = None

    # ------------------------------------------------------------------ #
    @property
    def enabled(self) -> bool:
        return bool(self.settings.database_url)

    def _get_engine(self):
        if not self.enabled:
            return None
        if self._engine is None:
            url = self.settings.database_url
            # Validate URL format — only PostgreSQL dialects are supported.
            # Supabase provides both an HTTPS REST URL (which SQLAlchemy cannot
            # use) and a postgres:// connection string.  When the user sets
            # UDT_DATABASE_URL to the HTTPS URL, SQLAlchemy raises:
            #   "Can't load plugin: sqlalchemy.dialects:https"
            if not url.startswith(("postgresql://", "postgresql+psycopg", "postgres://")):
                self._unavailable_reason = (
                    f"Invalid database URL scheme: '{url.split('://', 1)[0]}://'. "
                    "Expected a postgresql:// connection string from the Supabase "
                    "dashboard (Settings → Database → Connection string → URI). "
                    "The HTTPS REST API URL is not a valid SQLAlchemy connection string."
                )
                log.warning("Database URL validation failed: %s", self._unavailable_reason)
                self._engine = False
                return None
            try:
                from sqlalchemy import create_engine
                self._engine = create_engine(url, pool_pre_ping=True)
            except Exception as exc:
                self._unavailable_reason = str(exc)
                log.error("Database unavailable: %s", exc)
                self._engine = False
        return self._engine if self._engine is not False else None

    def status(self) -> dict:
        engine = self._get_engine()
        if not engine:
            return {"enabled": False, "reason": self._unavailable_reason or "not configured"}
        try:
            from sqlalchemy import text
            with engine.connect() as conn:
                result = conn.execute(text("SELECT count(*) FROM grid_cells"))
                count = result.scalar()
            return {"enabled": True, "grid_cells": int(count)}
        except Exception as exc:
            log.debug("Database probe failed: %s", exc)
            return {"enabled": True, "error": str(exc)}

    # ------------------------------------------------------------------ #
    def grid_cells(self, bbox: list[float] | None = None,
                   limit: int = 1000) -> list[dict]:
        """Return grid cells (with geometry) as GeoJSON features."""
        engine = self._get_engine()
        if not engine:
            raise RuntimeError("PostGIS not configured (set UDT_DATABASE_URL)")
        if not (1 <= limit <= 5000):
            limit = 1000
        sql = (
            "SELECT cell_id, ST_AsGeoJSON(geometry) AS geometry, "
            "       to_jsonb(t) - 'geometry' AS properties "
            "FROM grid_cells t"
        )
        params: dict = {}
        if bbox:
            sql += (
                " WHERE ST_Intersects(geometry, "
                "ST_MakeEnvelope(:xmin, :ymin, :xmax, :ymax, 4326))"
            )
            params = {"xmin": bbox[0], "ymin": bbox[1],
                      "xmax": bbox[2], "ymax": bbox[3]}
        sql += " LIMIT :limit"
        params["limit"] = limit

        from sqlalchemy import text
        features = []
        with engine.connect() as conn:
            for row in conn.execute(text(sql), params):
                features.append({
                    "type": "Feature",
                    "properties": dict(row["properties"]),
                    "geometry": row["geometry"],
                })
        return {"type": "FeatureCollection", "features": features}
