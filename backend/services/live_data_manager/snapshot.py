"""
Authoritative Live Data Snapshot
================================

The single source of truth for all live data at any point in time.

Every prediction, simulation, heatmap and dashboard result references a
unique snapshot_id. This prevents the "request A uses data version A,
request B uses data version B" problem.

Architecture:

    LiveDataManager.get_snapshot()
          ↓
    LiveSnapshot (immutable)
          ↓
    Feature Engineering
          ↓
    Model Prediction
          ↓
    Simulation
          ↓
    UI

Every component consumes the same snapshot/version.
"""
from __future__ import annotations

import hashlib
import logging
import threading
import time
from datetime import UTC, datetime
from typing import Any

log = logging.getLogger("backend.live_data.snapshot")


class LiveSnapshot:
    """An immutable snapshot of all live data at a point in time.

    Once created, a snapshot never changes. Every consumer of the snapshot
    sees the exact same data. This is the fundamental building block for
    snapshot consistency across predictions, simulations and the UI.
    """

    def __init__(
        self,
        snapshot_id: str,
        generated_at: str,
        weather: dict | None = None,
        air_quality: dict | None = None,
        satellite: dict | None = None,
        gis: dict | None = None,
        terrain: dict | None = None,
        sensors: dict | None = None,
        freshness: dict | None = None,
        source_status: dict | None = None,
    ):
        self.snapshot_id = snapshot_id
        self.generated_at = generated_at
        self.weather = weather or {}
        self.air_quality = air_quality or {}
        self.satellite = satellite or {}
        self.gis = gis or {}
        self.terrain = terrain or {}
        self.sensors = sensors or {}
        self.freshness = freshness or {}
        self.source_status = source_status or {}

    def to_dict(self) -> dict:
        return {
            "snapshot_id": self.snapshot_id,
            "generated_at": self.generated_at,
            "weather": self.weather,
            "air_quality": self.air_quality,
            "satellite": self.satellite,
            "gis": self.gis,
            "terrain": self.terrain,
            "sensors": self.sensors,
            "freshness": self.freshness,
            "source_status": self.source_status,
        }

    def __repr__(self) -> str:
        return f"LiveSnapshot(id={self.snapshot_id}, generated={self.generated_at})"


class SnapshotManager:
    """Manages the lifecycle of authoritative live data snapshots.

    The manager controls:
    1. When new snapshots are created
    2. How long snapshots are valid (TTL)
    3. Which components can access the current snapshot
    4. Snapshot history for simulation traceability

    Thread-safe: can be accessed from multiple request handlers simultaneously.
    """

    def __init__(self, default_ttl_seconds: int = 300):
        """
        Args:
            default_ttl_seconds: How long a snapshot is considered fresh.
                After this, get_snapshot() will trigger a refresh.
        """
        self._lock = threading.RLock()
        self._current: LiveSnapshot | None = None
        self._last_refresh: float = 0.0
        self._default_ttl = default_ttl_seconds
        self._history: dict[str, LiveSnapshot] = {}  # snapshot_id -> snapshot
        self._max_history = 100  # keep last N snapshots for traceability

    @property
    def current(self) -> LiveSnapshot | None:
        """Get the current snapshot without triggering a refresh."""
        with self._lock:
            return self._current

    def get_snapshot(self, force_refresh: bool = False) -> LiveSnapshot:
        """Get the current authoritative snapshot.

        If no snapshot exists or it's stale, creates a new one.
        Use force_refresh=True to bypass TTL (e.g., explicit user refresh).

        Returns:
            The current LiveSnapshot (never None after first call).
        """
        with self._lock:
            now = time.monotonic()
            age = now - self._last_refresh if self._last_refresh > 0 else float("inf")

            if (
                self._current is not None
                and not force_refresh
                and age < self._default_ttl
            ):
                return self._current

        # Create new snapshot (outside lock to avoid blocking readers)
        snapshot = self._create_snapshot()

        with self._lock:
            self._current = snapshot
            self._last_refresh = time.monotonic()
            # Store in history
            self._history[snapshot.snapshot_id] = snapshot
            # Prune old history
            if len(self._history) > self._max_history:
                oldest = sorted(self._history.keys())[: len(self._history) - self._max_history]
                for sid in oldest:
                    self._history.pop(sid, None)

        return snapshot

    def get_by_id(self, snapshot_id: str) -> LiveSnapshot | None:
        """Retrieve a historical snapshot by ID (for simulation traceability)."""
        with self._lock:
            return self._history.get(snapshot_id)

    def _create_snapshot(self) -> LiveSnapshot:
        """Create a new snapshot from all live data sources.

        This is the ONLY place where live data is collected. All downstream
        consumers read from the resulting snapshot.
        """
        from datetime import timezone
        now = datetime.now(timezone.utc)
        ts = now.isoformat()

        # Generate deterministic snapshot ID
        raw_id = f"snap_{now.strftime('%Y_%m_%d_%H%M%S')}_{now.microsecond // 1000:03d}"
        snapshot_id = raw_id

        # Collect data from all sources
        weather = {}
        air_quality = {}
        satellite = {}
        freshness = {}
        source_status = {}

        # Weather
        try:
            from backend.services.live_data import probe_weather, get_weather
            from backend.config.settings import get_settings
            settings = get_settings()
            weather_result = get_weather(settings)
            if weather_result.get("available"):
                weather = weather_result
                freshness["weather"] = {
                    "status": "LIVE",
                    "observed_at": weather_result.get("observed_at"),
                    "retrieved_at": weather_result.get("retrieved_at"),
                    "source": weather_result.get("source", "OpenWeather"),
                }
                source_status["weather"] = "LIVE"
            else:
                freshness["weather"] = {
                    "status": "UNAVAILABLE",
                    "reason": weather_result.get("reason", "unknown"),
                }
                source_status["weather"] = "UNAVAILABLE"
        except Exception as exc:
            log.warning("Weather data collection failed: %s", exc)
            freshness["weather"] = {"status": "UNAVAILABLE", "reason": str(exc)}
            source_status["weather"] = "UNAVAILABLE"

        # Air Quality
        try:
            from backend.services.live_data import get_air_quality
            from backend.config.settings import get_settings
            settings = get_settings()
            aqi_result = get_air_quality(settings)
            if aqi_result.get("available"):
                air_quality = aqi_result
                freshness["air_quality"] = {
                    "status": "LIVE",
                    "observed_at": aqi_result.get("observed_at"),
                    "retrieved_at": aqi_result.get("retrieved_at"),
                    "source": aqi_result.get("source", "OpenWeather"),
                }
                source_status["air_quality"] = "LIVE"
            else:
                freshness["air_quality"] = {
                    "status": "UNAVAILABLE",
                    "reason": aqi_result.get("reason", "unknown"),
                }
                source_status["air_quality"] = "UNAVAILABLE"
        except Exception as exc:
            log.warning("AQI data collection failed: %s", exc)
            freshness["air_quality"] = {"status": "UNAVAILABLE", "reason": str(exc)}
            source_status["air_quality"] = "UNAVAILABLE"

        # Satellite (latest available observation, NOT real-time)
        try:
            from backend.config.settings import get_settings
            settings = get_settings()
            geojson_path = settings.dataset_geojson
            if geojson_path.exists():
                import json as _json
                with open(geojson_path, encoding="utf-8") as fh:
                    gj = _json.load(fh)
                features = gj.get("features", [])
                if features:
                    acquisition = gj.get("crs", {}).get("properties", {}).get("name", "")
                    if not acquisition:
                        acquisition = gj.get("name", "unknown")
                    satellite = {
                        "acquisition_date": acquisition,
                        "cell_count": len(features),
                        "has_ndvi": "MeanNDVI" in features[0].get("properties", {}),
                    }
                    freshness["satellite"] = {
                        "status": "LATEST_OBSERVATION",
                        "acquired": acquisition,
                        "source": "Sentinel-2",
                    }
                    source_status["satellite"] = "LATEST_OBSERVATION"
                else:
                    freshness["satellite"] = {"status": "UNAVAILABLE", "reason": "empty grid"}
                    source_status["satellite"] = "UNAVAILABLE"
            else:
                freshness["satellite"] = {"status": "UNAVAILABLE", "reason": "GeoJSON not found"}
                source_status["satellite"] = "UNAVAILABLE"
        except Exception as exc:
            log.warning("Satellite data collection failed: %s", exc)
            freshness["satellite"] = {"status": "UNAVAILABLE", "reason": str(exc)}
            source_status["satellite"] = "UNAVAILABLE"

        # GIS (static, always available from training dataset)
        try:
            from backend.config.settings import get_settings
            settings = get_settings()
            csv_path = settings.dataset_csv
            if csv_path.exists():
                import pandas as pd
                df = pd.read_csv(csv_path, nrows=0)  # just read header
                freshness["gis"] = {
                    "status": "STATIC",
                    "last_updated": "training dataset",
                    "columns": len(df.columns),
                }
                source_status["gis"] = "STATIC"
            else:
                freshness["gis"] = {"status": "UNAVAILABLE", "reason": "training dataset not found"}
                source_status["gis"] = "UNAVAILABLE"
        except Exception as exc:
            log.warning("GIS data collection failed: %s", exc)
            freshness["gis"] = {"status": "UNAVAILABLE", "reason": str(exc)}
            source_status["gis"] = "UNAVAILABLE"

        # Terrain (static DEM, always available)
        freshness["terrain"] = {"status": "STATIC", "source": "Copernicus DEM GLO-30"}
        source_status["terrain"] = "STATIC"

        log.info(
            "Created snapshot %s — weather=%s, AQI=%s, satellite=%s",
            snapshot_id,
            source_status.get("weather", "?"),
            source_status.get("air_quality", "?"),
            source_status.get("satellite", "?"),
        )

        return LiveSnapshot(
            snapshot_id=snapshot_id,
            generated_at=ts,
            weather=weather,
            air_quality=air_quality,
            satellite=satellite,
            freshness=freshness,
            source_status=source_status,
        )


# Module-level singleton
_snapshot_manager: SnapshotManager | None = None
_snapshot_lock = threading.Lock()


def get_snapshot_manager(default_ttl_seconds: int = 300) -> SnapshotManager:
    """Get or create the module-level snapshot manager."""
    global _snapshot_manager
    if _snapshot_manager is None:
        with _snapshot_lock:
            if _snapshot_manager is None:
                _snapshot_manager = SnapshotManager(default_ttl_seconds)
    return _snapshot_manager


def get_current_snapshot(force_refresh: bool = False) -> LiveSnapshot:
    """Convenience: get the current authoritative snapshot."""
    return get_snapshot_manager().get_snapshot(force_refresh=force_refresh)
