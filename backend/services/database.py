"""
Database service (SQLite / PostgreSQL / PostGIS)
=================================================
Provides database-backed storage and fast indexed access for the 53,802 grid
cells, predictions, and simulation results.

Automatically activates SQLite database (``data/urban_digital_twin.db``) when
present, or connects to PostgreSQL/PostGIS when ``UDT_DATABASE_URL`` is set.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from backend.config.settings import Settings

log = logging.getLogger("backend.database")


class DatabaseService:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._engine = None
        self._unavailable_reason: str | None = None

    @property
    def database_url(self) -> str | None:
        if self.settings.database_url:
            return self.settings.database_url
        sqlite_file = self.settings.data_dir / "urban_digital_twin.db"
        if sqlite_file.exists():
            return f"sqlite:///{sqlite_file}"
        return None

    @property
    def enabled(self) -> bool:
        return bool(self.database_url)

    def _get_engine(self):
        if not self.enabled:
            return None
        if self._engine is None:
            try:
                from sqlalchemy import create_engine
                url = self.database_url
                connect_args = {"check_same_thread": False} if "sqlite" in url.lower() else {}
                self._engine = create_engine(url, pool_pre_ping=True, connect_args=connect_args)
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
            url = self.database_url or ""
            is_sqlite = "sqlite" in url.lower()
            engine_name = "SQLite" if is_sqlite else "PostgreSQL/PostGIS"
            with engine.connect() as conn:
                result = conn.execute(text("SELECT count(*) FROM grid_cells"))
                count = result.scalar()
            return {
                "enabled": True,
                "status": "connected",
                "engine": engine_name,
                "grid_cells": int(count),
            }
        except Exception as exc:
            log.debug("Database probe failed: %s", exc)
            return {"enabled": False, "error": str(exc)}

    def grid_cells(self, bbox: list[float] | None = None,
                   limit: int = 1000) -> list[dict]:
        """Return grid cells (with geometry) as GeoJSON features."""
        engine = self._get_engine()
        if not engine:
            raise RuntimeError("Database not configured (set UDT_DATABASE_URL or create data/urban_digital_twin.db)")
        if not (1 <= limit <= 5000):
            limit = 1000

        url = self.database_url or ""
        is_sqlite = "sqlite" in url.lower()

        if is_sqlite:
            from sqlalchemy import text
            sql = "SELECT cell_id, geometry, properties FROM grid_cells"
            params: dict = {}
            if bbox:
                sql += " WHERE minx >= :xmin AND miny >= :ymin AND maxx <= :xmax AND maxy <= :ymax"
                params = {"xmin": bbox[0], "ymin": bbox[1], "xmax": bbox[2], "ymax": bbox[3]}
            sql += f" LIMIT {limit}"
            features = []
            with engine.connect() as conn:
                for row in conn.execute(text(sql), params):
                    geom = json.loads(row[1]) if isinstance(row[1], str) else row[1]
                    props = json.loads(row[2]) if isinstance(row[2], str) else row[2]
                    features.append({
                        "type": "Feature",
                        "properties": props if isinstance(props, dict) else {"cell_id": row[0]},
                        "geometry": geom,
                    })
            return {"type": "FeatureCollection", "features": features}

        # PostgreSQL / PostGIS path
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
