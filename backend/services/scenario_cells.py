"""
Cell-level scenario results
===========================
Computes per-grid-cell XGBoost predictions for every predefined scenario on
the **full 53,802-cell grid** (the same grid used by the live ``POST
/api/simulation/run``) and exports them as:

* compact per-cell JSON (``GET /api/simulation/results/{scenario}/cells``)
* a MapLibre-ready GeoJSON FeatureCollection in WGS84
  (``GET /api/simulation/results/{scenario}/geojson``)

Everything is derived from the real artifacts — the trained model, the 58
model features, ``training_dataset.csv`` and ``training_dataset.geojson`` —
through the unchanged ``ai-engine`` ``ScenarioSimulator._perturb`` code path,
so the cell-level aggregates agree with the live run / stored results to
floating-point precision.

Caching
-------
Results are cached under ``data/outputs/scenarios/``:

* ``{scenario}.json``    — the compact ``/cells`` response body
* ``{scenario}.geojson`` — the WGS84 FeatureCollection
* ``_grid_wgs84.json``   — shared UTM→WGS84 grid geometry (built once)
* ``manifest.json``      — fingerprint of model/dataset/grid so caches are
  invalidated automatically when the underlying artifacts change

``?refresh=true`` forces regeneration.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from pyproj import Transformer

from backend.config.settings import Settings
from backend.services.serving import ServingContext
from backend.utils import aie

log = logging.getLogger("backend.scenario_cells")

# Grid coordinates: cells are 100 m; 6 decimals is ~0.1 m — plenty for the map.
COORD_DECIMALS = 6
# Geometry is stored as a single exterior ring per cell.
GEOMETRY_KEY = "geometries"
CENTROID_KEY = "centroids"

WGS84_CRS = {"type": "name", "properties": {"name": "urn:ogc:def:crs:OGC:1.3:CRS84"}}


def _grid_crs_name(geojson: dict) -> str:
    """Extract the source CRS from a GeoJSON ``crs`` member (best effort)."""
    crs = (geojson.get("crs") or {}).get("properties", {}).get("name", "")
    if "EPSG::" in crs:
        return f"EPSG:{crs.rsplit('EPSG::', 1)[1]}"
    if crs.startswith("EPSG:"):
        return crs
    return "EPSG:32645"  # ai-engine PredictionConfig default (UTM 45N)


class ScenarioCellsService:
    """Full-grid per-cell scenario predictions with a disk cache."""

    def __init__(self, settings: Settings, serving: ServingContext):
        self.settings = settings
        self.serving = serving
        self._cfg = aie.aie_config().Config()
        self._lock = threading.RLock()
        self._grid: dict[str, Any] | None = None
        self._mem: dict[str, dict] = {}  # scenario -> parsed /cells response
        self._cache_dir: Path = settings.scenario_cells_dir

    # ------------------------------------------------------------------ #
    # Scenario definitions (single source of truth: ai-engine config)
    # ------------------------------------------------------------------ #
    def _perturbations(self, name: str) -> dict[str, tuple]:
        """Validated perturbation set for a named scenario."""
        for sc in self._cfg.scenarios.scenarios:
            if sc.name == name:
                return dict(sc.perturbations)
        known = ", ".join(sc.name for sc in self._cfg.scenarios.scenarios)
        raise ValueError(f"Unknown scenario '{name}'. Available: {known}")

    def _simulator(self):
        return aie.aie_scenario_simulator().ScenarioSimulator(self._cfg)

    # ------------------------------------------------------------------ #
    # Fingerprint / cache validity
    # ------------------------------------------------------------------ #
    def _fingerprint(self) -> str:
        parts: list[str] = []
        for label, path in (
            ("model", self.settings.model_pkl),
            ("dataset", self.settings.dataset_csv),
            ("grid_source", self.settings.dataset_geojson),
        ):
            try:
                st = path.stat()
                parts.append(f"{label}:{st.st_size}:{st.st_mtime_ns}")
            except OSError:
                parts.append(f"{label}:missing")
        feat_hash = hashlib.sha256(
            "|".join(self.serving.features).encode("utf-8")
        ).hexdigest()[:12]
        parts.append(f"features:{feat_hash}")
        # Include live-data timestamps so caches invalidate when weather/AQI/
        # satellite change (TASK 8).
        try:
            from backend.services.live_feature_pipeline import get_pipeline
            pipeline = get_pipeline(self.settings)
            result = pipeline.refresh()
            age = result.get("feature_age", {})
            parts.append(f"weather_ts:{age.get('weather', 'none')}")
            parts.append(f"aqi_ts:{age.get('aqi', 'none')}")
            parts.append(f"sat_ts:{age.get('satellite', 'none')}")
        except Exception:
            parts.append("live_data:unavailable")
        return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:16]

    def _manifest(self) -> dict:
        path = self._cache_dir / "manifest.json"
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                log.warning("Unreadable scenario manifest - rebuilding.")
        return {"fingerprint": None, "scenarios": {}}

    def _write_manifest(self, manifest: dict) -> None:
        try:
            self._cache_dir.mkdir(parents=True, exist_ok=True)
            _atomic_write(
                self._cache_dir / "manifest.json",
                json.dumps(manifest, indent=2),
            )
        except OSError as exc:
            log.warning("Scenario manifest not persisted (%s).", exc)

    def _is_fresh(self, name: str) -> bool:
        """True when cached files exist for the current model/dataset state."""
        manifest = self._manifest()
        if manifest.get("fingerprint") != self._fingerprint():
            return False
        meta = manifest.get("scenarios", {}).get(name)
        if meta is None:
            return False
        return all((self._cache_dir / f"{name}{ext}").exists()
                   for ext in (".json", ".geojson"))

    # ------------------------------------------------------------------ #
    # Grid geometry (shared, converted UTM 45N -> WGS84 once)
    # ------------------------------------------------------------------ #
    def _grid_cache_path(self) -> Path:
        return self._cache_dir / "_grid_wgs84.json"

    def _load_grid(self) -> dict[str, Any]:
        with self._lock:
            if self._grid is not None:
                return self._grid
            cache = self._grid_cache_path()
            data = None
            if cache.exists():
                try:
                    with open(cache, encoding="utf-8") as fh:
                        data = json.load(fh)
                except (OSError, json.JSONDecodeError) as exc:
                    log.warning("Unreadable grid cache (%s) - rebuilding.", exc)
                    data = None
            if data is None:
                data = self._build_grid_data()
                try:
                    self._cache_dir.mkdir(parents=True, exist_ok=True)
                    _atomic_write(cache, json.dumps(data, separators=(",", ":")))
                    log.info("Grid cache written: %s (%d polygons).",
                             cache, data["count"])
                except OSError as exc:
                    log.warning(
                        "Grid cache not persisted (%s) - using in-memory geometry.", exc
                    )
            self._grid = {
                GEOMETRY_KEY: data[GEOMETRY_KEY],
                CENTROID_KEY: {k: tuple(v) for k, v in data[CENTROID_KEY].items()},
                "source_crs": data.get("source_crs"),
            }
            log.info("Grid geometry ready (%d cells).", len(self._grid[GEOMETRY_KEY]))
            return self._grid

    def _build_grid_data(self) -> dict:
        """Extract Grid_ID + geometry from the source GeoJSON and reproject to
        WGS84 (shared by all scenarios; persisted best-effort).
        """
        source = self.settings.dataset_geojson
        if not source.exists():
            raise FileNotFoundError(
                f"Grid geometry not found: {source}. Required for cell-level results."
            )
        log.info("Building WGS84 grid geometry from %s ...", source)
        with open(source, encoding="utf-8") as fh:
            geojson = json.load(fh)
        crs_name = _grid_crs_name(geojson)
        transformer = Transformer.from_crs(crs_name, "EPSG:4326", always_xy=True)

        from shapely.geometry import Polygon

        geometries: dict[str, list] = {}
        centroids: dict[str, list] = {}
        n_polygon = 0
        n_skipped = 0
        for feature in geojson.get("features", []):
            gid = str(feature.get("properties", {}).get("Grid_ID"))
            geom = feature.get("geometry")
            if not gid or geom is None:
                continue
            if geom.get("type") != "Polygon":
                n_skipped += 1
                continue
            ring = geom["coordinates"][0]
            xs = [p[0] for p in ring]
            ys = [p[1] for p in ring]
            lons, lats = transformer.transform(xs, ys)
            geometries[gid] = [
                [round(float(lon), COORD_DECIMALS), round(float(lat), COORD_DECIMALS)]
                for lon, lat in zip(lons, lats, strict=True)
            ]
            centroid = Polygon([(float(p[0]), float(p[1])) for p in ring]).centroid
            clon, clat = transformer.transform(centroid.x, centroid.y)
            centroids[gid] = [round(float(clon), COORD_DECIMALS),
                              round(float(clat), COORD_DECIMALS)]
            n_polygon += 1
        log.info("Grid geometry built: %d polygons, %d skipped", n_polygon, n_skipped)
        return {
            "source_crs": crs_name,
            "count": n_polygon,
            GEOMETRY_KEY: geometries,
            CENTROID_KEY: centroids,
        }

    # ------------------------------------------------------------------ #
    # Prediction core (batch, full grid)
    # ------------------------------------------------------------------ #
    def _predict(self, name: str) -> dict[str, Any]:
        """Baseline + perturbed predictions for the full grid (no geometry)."""
        perturbations = self._perturbations(name)
        X = self.serving.x_all
        baseline = np.asarray(self.serving.model.predict(X)).ravel()
        X_pert = self._simulator()._perturb(X, perturbations)
        scenario = np.asarray(self.serving.model.predict(X_pert)).ravel()
        delta = scenario - baseline

        grid_ids = list(self.serving.grid_ids)
        cells = [
            {
                "grid_id": _as_id(gid),
                "baseline_lst": float(baseline[i]),
                "scenario_lst": float(scenario[i]),
                "delta_lst": float(delta[i]),
            }
            for i, gid in enumerate(grid_ids)
        ]
        return {
            "scenario": name,
            "count": len(cells),
            "cells": cells,
            "baseline_lst": float(np.mean(baseline)),
            "mean_predicted_lst": float(np.mean(scenario)),
            "mean_delta_lst": float(np.mean(delta)),
            "min_delta": float(np.min(delta)),
            "max_delta": float(np.max(delta)),
            "pct_cells_cooler": float(np.mean(delta < 0) * 100.0),
        }

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
    def cells(self, name: str, refresh: bool = False) -> dict:
        """Per-cell results for a scenario (cached on disk + in memory)."""
        with self._lock:
            if not refresh and name in self._mem:
                return dict(self._mem[name], cached=True)
            if not refresh and self._is_fresh(name):
                data = self._read_cached(name)
            else:
                data = self._compute_and_cache(name)
            self._mem[name] = data
            return dict(data, cached=True)

    def geojson(self, name: str, refresh: bool = False) -> dict:
        """MapLibre-ready FeatureCollection (WGS84) for a scenario."""
        with self._lock:
            if not refresh and self._is_fresh(name):
                path = self._cache_dir / f"{name}.geojson"
                with open(path, encoding="utf-8") as fh:
                    return json.load(fh)
            data = self._compute_and_cache(name)
            return self._read_geojson(name, data)

    def regenerate_sensitivity_csv(self) -> Path:
        """Recompute the aggregate sensitivity analysis on the full grid.

        The offline pipeline historically ran STEP 9 on the 20% held-out test
        set, which disagreed with the live API's full-grid runs. Recomputing on
        the full grid makes ``GET /api/simulation/results``, ``POST
        /api/simulation/run`` and the cell-level endpoints agree exactly.
        """
        rows = []
        for sc in self._cfg.scenarios.scenarios:
            data = self._predict(sc.name)
            rows.append({
                "scenario": sc.name,
                "description": sc.description,
                "mean_predicted_lst": data["mean_predicted_lst"],
                "baseline_lst": data["baseline_lst"],
                "mean_delta_lst": data["mean_delta_lst"],
                "min_delta": data["min_delta"],
                "max_delta": data["max_delta"],
                "pct_cells_cooler": data["pct_cells_cooler"],
            })
        df = pd.DataFrame(rows).sort_values("mean_delta_lst").reset_index(drop=True)
        df.to_csv(self.settings.sensitivity_csv, index=False)
        log.info("Sensitivity CSV regenerated on the full grid: %s",
                 self.settings.sensitivity_csv)
        return self.settings.sensitivity_csv

    # ------------------------------------------------------------------ #
    # Internals
    # ------------------------------------------------------------------ #
    def _compute_and_cache(self, name: str) -> dict:
        t_start = time.monotonic()
        data = self._predict(name)
        grid = self._load_grid()
        geoms = grid[GEOMETRY_KEY]
        centroids = grid[CENTROID_KEY]
        missing = 0
        for cell in data["cells"]:
            gid = str(cell["grid_id"])
            centroid = centroids.get(gid)
            if centroid is None or gid not in geoms:
                missing += 1
            if centroid is None:
                cell["latitude"] = None
                cell["longitude"] = None
            else:
                cell["latitude"] = centroid[1]
                cell["longitude"] = centroid[0]
        if missing:
            log.warning("Scenario %s: %d cell(s) without grid geometry.", name, missing)

        features = []
        for cell in data["cells"]:
            ring = geoms.get(str(cell["grid_id"]))
            if ring is None:
                continue
            features.append({
                "type": "Feature",
                "properties": {
                    "grid_id": cell["grid_id"],
                    "baseline_lst": cell["baseline_lst"],
                    "scenario_lst": cell["scenario_lst"],
                    "delta_lst": cell["delta_lst"],
                },
                "geometry": {"type": "Polygon", "coordinates": [ring]},
            })
        fc = {
            "type": "FeatureCollection",
            "crs": WGS84_CRS,
            "features": features,
        }

        generated_at = datetime.now(UTC).isoformat()
        try:
            self._cache_dir.mkdir(parents=True, exist_ok=True)
            _atomic_write(self._cache_dir / f"{name}.json", json.dumps({
                **data, "generated_at": generated_at,
            }, separators=(",", ":")))
            _atomic_write(self._cache_dir / f"{name}.geojson",
                          json.dumps(fc, separators=(",", ":")))
            manifest = self._manifest()
            manifest["fingerprint"] = self._fingerprint()
            manifest.setdefault("scenarios", {})[name] = {
                "generated_at": generated_at,
                "count": data["count"],
            }
            self._write_manifest(manifest)
        except OSError as exc:
            log.warning(
                "Scenario cache not persisted (%s) - serving from memory.", exc
            )

        data["generated_at"] = generated_at
        data["cached"] = True
        log.info("Scenario %s: %d cells cached (%.1f s).",
                 name, data["count"], time.monotonic() - t_start)
        return data

    def _read_cached(self, name: str) -> dict:
        path = self._cache_dir / f"{name}.json"
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)

    def _read_geojson(self, name: str, data: dict | None = None) -> dict:
        path = self._cache_dir / f"{name}.geojson"
        if path.exists():
            with open(path, encoding="utf-8") as fh:
                return json.load(fh)
        # fall back to rebuilding from the freshly computed data
        grid = self._load_grid()
        geoms = grid[GEOMETRY_KEY]
        features = []
        for cell in data["cells"]:
            ring = geoms.get(str(cell["grid_id"]))
            if ring is None:
                continue
            features.append({
                "type": "Feature",
                "properties": {
                    "grid_id": cell["grid_id"],
                    "baseline_lst": cell["baseline_lst"],
                    "scenario_lst": cell["scenario_lst"],
                    "delta_lst": cell["delta_lst"],
                },
                "geometry": {"type": "Polygon", "coordinates": [ring]},
            })
        return {"type": "FeatureCollection", "crs": WGS84_CRS, "features": features}


def _as_id(value: Any) -> Any:
    """Grid_ID is an integer in the dataset; keep it as an int when possible."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return value


def _atomic_write(path: Path, text: str) -> None:
    """Write a file atomically (tmp + rename) so readers never see partial data."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(text)
    os.replace(tmp, path)
