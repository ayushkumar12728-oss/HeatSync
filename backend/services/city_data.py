"""
City-wide data service
======================
Reads the real project artifacts (100 m grid geometry, the feature-engineering
training dataset, per-cell XGBoost predictions and the cached per-cell scenario
results) and exposes city-scale analytics:

* ``point``  — nearest grid cell to any map click / search result (location
  intelligence without ever inventing values)
* ``hotspots`` — hottest spatial cells from the model predictions
* ``cooling_potential`` — per-cell intervention cooling derived from the real
  scenario deltas (labelled "model-derived", never a new scientific model)
* ``interventions`` — ranked "where should we intervene?" opportunities
* ``city_intelligence`` — compact command-centre aggregates
* ``explain`` — data-backed "why is this area hot?" factors (global SHAP
  importance + the cell's real feature values; per-cell SHAP is never faked)
* ``route`` — grid-based fastest vs lower-heat-exposure routing on the real
  100 m cell lattice

All values come from files on disk. Anything missing is reported as
unavailable rather than estimated.
"""

from __future__ import annotations

import csv
import heapq
import itertools
import json
import logging
import math
import threading

import numpy as np
import pandas as pd

from backend.config.settings import Settings

log = logging.getLogger("backend.city_data")

EARTH_RADIUS_M = 6_371_000.0

# Fixed heat-class breaks (gis-engine HeatClassConfig) — used only to label.
HEAT_CLASS_BREAKS = [("Very Cool", 20.0), ("Cool", 25.0), ("Moderate", 30.0),
                     ("Warm", 35.0), ("Hot", 40.0)]

# CPCB AQI categories (gis-engine config AQI_CATEGORIES)
AQI_CATEGORIES = [("Good", 50), ("Satisfactory", 100), ("Moderate", 200),
                  ("Poor", 300), ("Very Poor", 400)]

# Feature columns of interest -> friendly label (kept minimal on purpose).
FEATURE_MAP = {
    "MeanLST": "Land Surface Temperature",
    "MeanNDVI": "NDVI",
    "GreenCover": "Green Cover",
    "VegetationDensity": "Vegetation Density",
    "BuildingCoveragePct": "Building Coverage",
    "BuildingDensity": "Building Density",
    "TreeCount": "Tree Count",
    "TreeDensity": "Tree Density",
    "GreenSpacePct": "Green Space",
    "MeanElevation": "Elevation",
    "MeanSlope": "Slope",
    "MeanAQI": "AQI",
    "MeanPM25": "PM2.5",
    "MeanPM10": "PM10",
    "MeanNO2": "NO2",
    "MeanSO2": "SO2",
    "MeanO3": "O3",
    "MeanCO": "CO",
    "LandCoverClass": "Land Cover Class",
    "ImperviousSurfaceRatio": "Impervious Surface",
    "GreenToBuiltRatio": "Green-to-Built Ratio",
    "DistToPark": "Distance to Park",
    "DistToWater": "Distance to Water",
    "HeatVulnerabilityIndex": "Heat Vulnerability Index",
}

# Features that explain heat well and exist in the training set.
ACTIONABLE_FEATURES = [
    "ImperviousSurfaceRatio", "MeanPM25", "MeanNDVI", "GreenCover",
    "BuildingCoveragePct", "TreeDensity", "DistToPark", "MeanLST",
    "LandCoverClass", "HeatVulnerabilityIndex",
]

SCENARIO_FILES = [
    "increase_green_10", "increase_green_20", "increase_trees",
    "increase_parks", "increase_water", "decrease_buildings_10",
    "decrease_buildings_20",
]

# Walking speed used ONLY for the routing time estimate (labelled as such).
WALK_SPEED_KMH = 4.8


def _haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    a = (math.sin(math.radians(lat2 - lat1) / 2) ** 2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2))
         * math.sin(math.radians(lng2 - lng1) / 2) ** 2)
    return 2 * EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(a)))


def _vec_haversine_m(lat1, lng1, lat2, lng2) -> np.ndarray:
    """Vectorised haversine for nearest-cell lookups."""
    lat1, lng1, lat2, lng2 = map(np.asarray, (lat1, lng1, lat2, lng2))
    a = np.sin(np.radians(lat2 - lat1) / 2) ** 2 + np.cos(
        np.radians(lat1)) * np.cos(np.radians(lat2)) * np.sin(
        np.radians(lng2 - lng1) / 2) ** 2
    return 2 * EARTH_RADIUS_M * np.arcsin(np.minimum(1.0, np.sqrt(a)))


def heat_class(celsius: float | None) -> str | None:
    if celsius is None or not math.isfinite(celsius):
        return None
    for label, threshold in HEAT_CLASS_BREAKS:
        if celsius < threshold:
            return label
    return "Very Hot"


def aqi_category(aqi: float | None) -> str | None:
    if aqi is None or not math.isfinite(aqi):
        return None
    for label, threshold in AQI_CATEGORIES:
        if aqi <= threshold:
            return label
    return "Severe"


def _f(value) -> float | None:
    """Coerce a value to float, returning None for NaN/None."""
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(f):
        return None
    return f


class CityDataService:
    """Lazy, thread-safe access to the city grid + model outputs."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self._lock = threading.RLock()
        self._grid: dict[str, dict] | None = None       # gid -> ring + centroid
        self._features: pd.DataFrame | None = None       # indexed by Grid_ID
        self._predictions: pd.DataFrame | None = None
        self._shap: list[dict] | None = None
        self._scenario_deltas: dict[str, dict[str, float]] | None = None
        self._scenario_stats: list[dict] | None = None
        self._lngs: np.ndarray | None = None
        self._lats: np.ndarray | None = None
        self._gids: list[str] | None = None

    # ------------------------------------------------------------------ #
    # Loading
    # ------------------------------------------------------------------ #
    def _load_grid(self) -> dict[str, dict]:
        with self._lock:
            if self._grid is not None:
                return self._grid
            grid_path = self.settings.scenario_cells_dir / "_grid_wgs84.json"
            if not grid_path.exists():
                raise FileNotFoundError(
                    f"Grid geometry not found: {grid_path}. Run the scenario "
                    "engine (python ai-engine/main.py) first."
                )
            with open(grid_path, encoding="utf-8") as fh:
                data = json.load(fh)
            geoms = data.get("geometries", {})
            cents = data.get("centroids", {})
            grid: dict[str, dict] = {}
            for gid, ring in geoms.items():
                centroid = cents.get(gid)
                if centroid is None:
                    continue
                grid[str(gid)] = {
                    "ring": ring,
                    "centroid": (float(centroid[0]), float(centroid[1])),
                }
            if not grid:
                raise RuntimeError("Grid geometry is empty.")
            self._grid = grid
            self._gids = list(grid.keys())
            self._lngs = np.asarray([grid[g]["centroid"][0] for g in self._gids], dtype=np.float64)
            self._lats = np.asarray([grid[g]["centroid"][1] for g in self._gids], dtype=np.float64)
            log.info("City grid loaded: %d cells.", len(grid))
            return grid

    def _load_features(self) -> pd.DataFrame:
        with self._lock:
            if self._features is not None:
                return self._features
            path = self.settings.dataset_csv
            if not path.exists():
                raise FileNotFoundError(f"Training dataset not found: {path}")
            columns = [*FEATURE_MAP, "Grid_ID"]
            df = pd.read_csv(path, usecols=lambda c: c in columns)
            df["Grid_ID"] = df["Grid_ID"].astype(str)
            df = df.set_index("Grid_ID")
            self._features = df
            log.info("Feature table loaded: %d cells x %d columns.", *df.shape)
            return df

    def _load_predictions(self) -> pd.DataFrame:
        """Per-cell XGBoost predictions (20% test set from predictions.csv)."""
        with self._lock:
            if self._predictions is not None:
                return self._predictions
            path = self.settings.predictions_csv
            if not path.exists():
                raise FileNotFoundError(f"Predictions CSV not found: {path}")
            df = pd.read_csv(path)
            df["Grid_ID"] = df["Grid_ID"].astype(str)
            df = df.set_index("Grid_ID")
            self._predictions = df
            log.info("Predictions loaded: %d cells.", len(df))
            return df

    def _load_baseline(self) -> dict[str, float]:
        """Full-grid XGBoost baseline LST from the cached scenario results.

        The scenario cache stores a baseline prediction for every one of the
        53 802 cells (same model, full grid). predictions.csv only covers the
        20% held-out test set, so the scenario baseline is the authoritative
        city-wide predicted-LST source.
        """
        with self._lock:
            if getattr(self, "_baseline", None) is not None:
                return self._baseline
            baseline: dict[str, float] = {}
            for name in SCENARIO_FILES:
                path = self.settings.scenario_cells_dir / f"{name}.json"
                if not path.exists():
                    continue
                try:
                    with open(path, encoding="utf-8") as fh:
                        data = json.load(fh)
                except (OSError, json.JSONDecodeError):
                    continue
                for cell in data.get("cells") or []:
                    bl = _f(cell.get("baseline_lst"))
                    if bl is not None and str(cell.get("grid_id")) not in baseline:
                        baseline[str(cell.get("grid_id"))] = bl
                if baseline:
                    break
            # Fall back to the test-set predictions when no scenario cache exists.
            if not baseline:
                try:
                    df = self._load_predictions()
                    baseline = {gid: _f(row.get("Predicted_LST"))
                                for gid, row in df.iterrows()
                                if _f(row.get("Predicted_LST")) is not None}
                except FileNotFoundError:
                    pass
            self._baseline = baseline
            log.info("Full-grid baseline predictions loaded: %d cells.", len(baseline))
            return baseline

    def _load_shap(self) -> list[dict]:
        with self._lock:
            if self._shap is not None:
                return self._shap
            path = self.settings.shap_importance_csv
            rows: list[dict] = []
            if path.exists():
                with open(path, encoding="utf-8", newline="") as fh:
                    for row in csv.DictReader(fh):
                        try:
                            rows.append({
                                "feature": row.get("feature", ""),
                                "mean_abs_shap": float(row.get("mean_abs_shap", 0.0) or 0.0),
                            })
                        except (TypeError, ValueError):
                            continue
                rows.sort(key=lambda r: r["mean_abs_shap"], reverse=True)
            self._shap = rows
            return rows

    def _load_scenarios(self) -> tuple[dict[str, dict[str, float]], list[dict]]:
        """Per-cell deltas + aggregate stats for every cached scenario."""
        with self._lock:
            if self._scenario_deltas is not None:
                return self._scenario_deltas, self._scenario_stats  # type: ignore[return-value]
            deltas: dict[str, dict[str, float]] = {}
            stats: list[dict] = []
            for name in SCENARIO_FILES:
                path = self.settings.scenario_cells_dir / f"{name}.json"
                if not path.exists():
                    log.info("Scenario cache missing (skipped): %s", name)
                    continue
                try:
                    with open(path, encoding="utf-8") as fh:
                        data = json.load(fh)
                except (OSError, json.JSONDecodeError) as exc:
                    log.warning("Unreadable scenario cache %s (%s).", name, exc)
                    continue
                cells = data.get("cells") or []
                deltas[name] = {str(c.get("grid_id")): _f(c.get("delta_lst"))
                                for c in cells if _f(c.get("delta_lst")) is not None}
                stats.append({
                    "scenario": name,
                    "description": data.get("scenario", name),
                    "mean_delta_lst": _f(data.get("mean_delta_lst")),
                    "min_delta": _f(data.get("min_delta")),
                    "max_delta": _f(data.get("max_delta")),
                    "pct_cells_cooler": _f(data.get("pct_cells_cooler")),
                    "n_cells": len(cells),
                })
            stats.sort(key=lambda s: (s.get("mean_delta_lst") or 0.0))
            self._scenario_deltas = deltas
            self._scenario_stats = stats
            log.info("Scenario deltas loaded for %d scenario(s).", len(deltas))
            return deltas, stats

    # ------------------------------------------------------------------ #
    # Nearest cell
    # ------------------------------------------------------------------ #
    def nearest_cell(self, lat: float, lng: float,
                     max_km: float = 3.0) -> dict | None:
        """Nearest grid cell within ``max_km`` (returns None otherwise)."""
        self._load_grid()
        if self._lngs is None or self._lats is None:
            return None
        dists = _vec_haversine_m(lat, lng, self._lats, self._lngs)
        idx = int(np.argmin(dists))
        dist_m = float(dists[idx])
        if dist_m > max_km * 1000.0:
            return None
        gid = self._gids[idx]
        return {
            "grid_id": _as_id(gid),
            "distance_m": round(dist_m, 1),
            "latitude": float(self._lats[idx]),
            "longitude": float(self._lngs[idx]),
        }

    def cell_features(self, grid_id: str) -> dict:
        """Feature values for one cell (only real, available columns)."""
        features = self._load_features()
        try:
            row = features.loc[str(grid_id)]
        except KeyError:
            return {}
        out: dict[str, float | int | None] = {}
        for col in FEATURE_MAP:
            value = row.get(col)
            if col == "LandCoverClass":
                out[col] = int(value) if pd.notna(value) else None
            else:
                out[col] = _f(value)
        return out

    def predicted_lst(self, grid_id: str) -> float | None:
        """Predicted LST: full-grid scenario baseline, else test-set prediction."""
        baseline = self._load_baseline()
        value = baseline.get(str(grid_id))
        if value is not None:
            return value
        try:
            df = self._load_predictions()
            return _f(df.loc[str(grid_id), "Predicted_LST"])
        except (KeyError, FileNotFoundError):
            return None

    # ------------------------------------------------------------------ #
    # Point profile (location intelligence)
    # ------------------------------------------------------------------ #
    def point_profile(self, lat: float, lng: float) -> dict:
        """Full environment profile for any point (real data only)."""
        nearest = self.nearest_cell(lat, lng)
        if nearest is None:
            return {
                "available": False,
                "message": "No 100 m model grid cell within 3 km — data unavailable here.",
                "latitude": round(lat, 6), "longitude": round(lng, 6),
            }
        gid = str(nearest["grid_id"])
        feat = self.cell_features(gid)
        pred = self.predicted_lst(gid)
        lst = feat.get("MeanLST")
        aqi = feat.get("MeanAQI")
        ndvi = feat.get("MeanNDVI")
        green_cover = feat.get("GreenCover")

        risk = {
            "heat": _risk_level(heat_class(lst), ["Moderate", "Warm"], ["Hot", "Very Hot"]),
            "air_quality": _risk_level(aqi_category(aqi), ["Moderate"],
                                       ["Poor", "Very Poor", "Severe"]),
            "vegetation": _vegetation_risk(ndvi, green_cover),
            "urban_density": _density_risk(feat.get("BuildingCoveragePct")),
        }

        environment = {
            key: feat.get(key) for key in (
                "MeanLST", "MeanAQI", "MeanPM25", "MeanPM10", "MeanNO2",
                "MeanSO2", "MeanO3", "MeanCO", "MeanNDVI", "GreenCover",
                "VegetationDensity", "BuildingCoveragePct", "BuildingDensity",
                "TreeCount", "TreeDensity", "GreenSpacePct", "MeanElevation",
                "MeanSlope", "LandCoverClass", "ImperviousSurfaceRatio",
                "GreenToBuiltRatio", "DistToPark", "DistToWater",
                "HeatVulnerabilityIndex",
            )
        }
        environment["Predicted_LST"] = pred

        return {
            "available": True,
            "grid_id": nearest["grid_id"],
            "latitude": nearest["latitude"],
            "longitude": nearest["longitude"],
            "distance_m": nearest["distance_m"],
            "uhi_class": heat_class(lst or pred),
            "aqi_category": aqi_category(aqi),
            "environment": environment,
            "risk": risk,
            "model": {
                "predicted_lst": pred,
                "target_lst": lst,
                "note": "XGBoost per-cell prediction (models/best_model.pkl)",
            },
            "source": {
                "dataset": "100 m feature grid "
                           "(feature_engineering/training_dataset.csv) + predictions.csv",
                "resolution": "100 m grid / 10-30 m source rasters",
                "method": "Nearest grid cell lookup",
            },
        }

    # ------------------------------------------------------------------ #
    # Hotspots
    # ------------------------------------------------------------------ #
    def hotspots(self, limit: int = 50) -> list[dict]:
        grid = self._load_grid()
        baseline = self._load_baseline()
        features = self._load_features()
        rows: list[dict] = []
        for gid in grid:
            pred = baseline.get(gid)
            if pred is None:
                continue
            centroid = grid[gid]["centroid"]
            feat = {}
            if gid in features.index:
                row = features.loc[gid]
                feat = {k: _f(row.get(k)) for k in
                        ("MeanNDVI", "GreenCover", "BuildingCoveragePct", "MeanAQI",
                         "TreeDensity", "DistToPark") if k in features.columns}
            rows.append({
                "grid_id": _as_id(gid),
                "predicted_lst": round(pred, 2),
                "latitude": centroid[1],
                "longitude": centroid[0],
                "uhi_class": heat_class(pred),
                **feat,
            })
        rows.sort(key=lambda r: r["predicted_lst"], reverse=True)
        return rows[: int(limit)]

    # ------------------------------------------------------------------ #
    # Cooling potential (model-derived)
    # ------------------------------------------------------------------ #
    def cooling_potential(self) -> dict:
        """Per-cell maximum modeled cooling across all cached scenarios."""
        deltas, _stats = self._load_scenarios()
        if not deltas:
            return {"available": False,
                    "message": "No scenario cell results cached — run the scenario engine first."}
        grid = self._load_grid()
        cells: list[dict] = []
        for gid in grid:
            coolings = [d.get(gid) for d in deltas.values() if d.get(gid) is not None]
            if not coolings:
                continue
            max_cooling = min(coolings)  # most negative = strongest cooling
            centroid = grid[gid]["centroid"]
            cells.append({
                "grid_id": _as_id(gid),
                "latitude": centroid[1],
                "longitude": centroid[0],
                "max_cooling_c": round(max_cooling, 2),
                "best_scenario": min(
                    (name for name, d in deltas.items() if d.get(gid) is not None),
                    key=lambda name: deltas[name].get(gid, 0.0),
                ),
            })
        cells.sort(key=lambda c: c["max_cooling_c"])
        # Classify using the real distribution of modelled cooling.
        coolings = np.asarray([c["max_cooling_c"] for c in cells], dtype=np.float64)
        if coolings.size == 0:
            return {"available": False, "message": "No cooling data."}
        p25, p50, p75 = np.percentile(coolings, [25, 50, 75])

        def cls(cool: float) -> str:
            if cool < p25:
                return "VERY HIGH"
            if cool < p50:
                return "HIGH"
            if cool < p75:
                return "MODERATE"
            return "LOW"

        for c in cells:
            c["cooling_class"] = cls(c["max_cooling_c"])
        return {
            "available": True,
            "count": len(cells),
            "label": "Model-derived intervention potential (max cooling across "
                     "XGBoost scenarios)",
            "thresholds": {
                "very_high_under_c": round(float(p25), 2),
                "high_under_c": round(float(p50), 2),
                "moderate_under_c": round(float(p75), 2),
            },
            "cells": cells,
        }

    def cooling_potential_geojson(self) -> dict:
        """GeoJSON of cooling-potential classes for the 3D map (CURRENT=baseline)."""
        result = self.cooling_potential()
        if not result.get("available"):
            return {"type": "FeatureCollection", "features": []}
        grid = self._load_grid()
        features = []
        for c in result["cells"]:
            ring = grid.get(str(c["grid_id"]), {}).get("ring")
            if ring is None:
                continue
            features.append({
                "type": "Feature",
                "properties": {
                    "grid_id": c["grid_id"],
                    "max_cooling_c": c["max_cooling_c"],
                    "cooling_class": c["cooling_class"],
                    "best_scenario": c["best_scenario"],
                },
                "geometry": {"type": "Polygon", "coordinates": [ring]},
            })
        return {"type": "FeatureCollection", "features": features}

    # ------------------------------------------------------------------ #
    # Intervention opportunities ("where should we intervene?")
    # ------------------------------------------------------------------ #
    def interventions(self, per_scenario: int = 5) -> dict:
        deltas, stats = self._load_scenarios()
        grid = self._load_grid()
        if not deltas:
            return {"available": False,
                    "message": "No scenario cell results cached — run the scenario engine first."}
        ranked: list[dict] = []
        for name, d in deltas.items():
            best = sorted(((gid, delta) for gid, delta in d.items()),
                          key=lambda kv: kv[1])[: per_scenario]
            for gid, delta in best:
                centroid = grid.get(str(gid), {}).get("centroid")
                if centroid is None:
                    continue
                features = self.cell_features(gid)
                ranked.append({
                    "scenario": name,
                    "grid_id": _as_id(gid),
                    "latitude": centroid[1],
                    "longitude": centroid[0],
                    "current_lst_c": _f(features.get("MeanLST")),
                    "after_lst_c": None,  # filled below (needs the delta)
                    "cooling_c": round(delta, 2),
                })
        # after = current + delta (delta is scenario - baseline)
        for r in ranked:
            if r["current_lst_c"] is not None:
                r["after_lst_c"] = round(r["current_lst_c"] + r["cooling_c"], 2)
        ranked.sort(key=lambda r: r["cooling_c"])
        return {
            "available": True,
            "count": len(ranked),
            "label": "Areas where the modelled interventions produce the strongest cooling",
            "interventions": ranked[: max(1, per_scenario * len(deltas))],
            "scenario_stats": stats,
        }

    # ------------------------------------------------------------------ #
    # City intelligence (command centre)
    # ------------------------------------------------------------------ #
    def city_intelligence(self) -> dict:
        hotspots = self.hotspots(limit=5)
        deltas, stats = self._load_scenarios()
        features = self._load_features()

        baseline = self._load_baseline()
        avg_pred = (round(float(np.mean(list(baseline.values()))), 2)
                    if baseline else None)
        avg_aqi = _f(features["MeanAQI"].mean()) if "MeanAQI" in features.columns else None
        avg_ndvi = _f(features["MeanNDVI"].mean()) if "MeanNDVI" in features.columns else None
        avg_build = (_f(features["BuildingCoveragePct"].mean())
                     if "BuildingCoveragePct" in features.columns else None)

        best = stats[0] if stats else None
        hottest = hotspots[0] if hotspots else None

        return {
            "available": True,
            "city": "Bhubaneswar",
            "current_heat": avg_pred,
            "aqi": avg_aqi,
            "ndvi": avg_ndvi,
            "urban_density": avg_build,
            "hottest_zone": {
                "grid_id": hottest["grid_id"] if hottest else None,
                "predicted_lst": hottest["predicted_lst"] if hottest else None,
                "latitude": hottest["latitude"] if hottest else None,
                "longitude": hottest["longitude"] if hottest else None,
            } if hottest else None,
            "best_intervention": {
                "scenario": best["scenario"] if best else None,
                "mean_delta_lst": best["mean_delta_lst"] if best else None,
                "pct_cells_cooler": best["pct_cells_cooler"] if best else None,
            } if best else None,
            "scenario_count": len(deltas),
            "source": "Real grid features + XGBoost predictions + cached scenario results",
        }

    # ------------------------------------------------------------------ #
    # Distributions (analytics)
    # ------------------------------------------------------------------ #
    def distributions(self) -> dict:
        """Real histograms across the full grid for the analytics charts."""
        baseline = self._load_baseline()
        features = self._load_features()

        def histogram(values, bins: int = 24):
            arr = np.asarray([v for v in values if v is not None], dtype=np.float64)
            if arr.size == 0:
                return {"bins": [], "counts": [], "min": None, "max": None,
                        "mean": None}
            counts, edges = np.histogram(arr, bins=bins)
            mids = (edges[:-1] + edges[1:]) / 2.0
            return {
                "bins": [round(float(m), 2) for m in mids],
                "counts": [int(c) for c in counts],
                "min": round(float(arr.min()), 2),
                "max": round(float(arr.max()), 2),
                "mean": round(float(arr.mean()), 2),
            }

        columns = {"predicted_lst": "Predicted LST", "MeanAQI": "AQI",
                   "MeanNDVI": "NDVI", "BuildingCoveragePct": "Building Coverage",
                   "MeanPM25": "PM2.5", "GreenCover": "Green Cover"}
        out: dict[str, dict] = {}
        for col, label in columns.items():
            if col == "predicted_lst":
                out[col] = {"label": label, "unit": "°C",
                            **histogram(baseline.values())}
            elif col in features.columns:
                out[col] = {"label": label, "unit": "",
                            **histogram(features[col].tolist())}

        # Model performance from the test-set residuals (real).
        try:
            df = self._load_predictions()
            residuals = df["Residual"].tolist()
            out["model_performance"] = {
                "label": "Model residual (test set)",
                "unit": "°C",
                "mae": round(float(df["Residual"].abs().mean()), 3),
                "rmse": round(float(np.sqrt((df["Residual"] ** 2).mean())), 3),
                "n": len(df),
                **histogram(residuals, bins=20),
            }
        except (FileNotFoundError, KeyError):
            pass
        return out

    # ------------------------------------------------------------------ #
    # Explainable map ("why is this area hot?")
    # ------------------------------------------------------------------ #
    def explain(self, lat: float, lng: float) -> dict:
        profile = self.point_profile(lat, lng)
        if not profile.get("available"):
            return {**profile, "explanation": None}
        feat = profile["environment"]
        shap = self._load_shap()
        importance = {r["feature"]: r["mean_abs_shap"] for r in shap}

        means = {}
        try:
            features = self._load_features()
            means = {col: _f(features[col].mean())
                     for col in ACTIONABLE_FEATURES if col in features.columns}
        except FileNotFoundError:
            means = {}

        factors: list[dict] = []
        for col in ACTIONABLE_FEATURES:
            value = feat.get(col)
            mean = means.get(col)
            importance_val = importance.get(col)
            if value is None or importance_val is None:
                continue
            if mean is None:
                continue
            # Higher-is-hotter semantics for each feature (documented below).
            hotter_when_high = col not in ("MeanNDVI", "GreenCover",
                                           "TreeDensity", "GreenToBuiltRatio",
                                           "DistToPark")
            if col == "DistToPark":
                hotter_when_high = False  # farther from a park -> hotter
            direction = "above" if value > mean else "below"
            factors.append({
                "feature": FEATURE_MAP.get(col, col),
                "column": col,
                "value": round(value, 3) if isinstance(value, (int, float)) else value,
                "city_mean": round(mean, 3),
                "direction": direction,
                "hotter_when_high": hotter_when_high,
                "shap_importance": round(importance_val, 4),
            })
        factors.sort(key=lambda f: f["shap_importance"], reverse=True)
        return {
            **profile,
            "explanation": {
                "factors": factors[:8],
                "data_used": [
                    "100 m feature grid (real OSM + satellite features)",
                    "XGBoost prediction (models/best_model.pkl)",
                    "Global SHAP importance (ai-engine output)",
                ],
                "notes": [
                    "Per-cell SHAP values are not available; factors are ranked by "
                    "global mean |SHAP| and the cell's real feature value vs the "
                    "city mean.",
                    "This is a data-backed description, not a per-cell attribution.",
                ],
            },
        }

    # ------------------------------------------------------------------ #
    # Heat-safe (lower-exposure) routing
    # ------------------------------------------------------------------ #
    def route(self, start_lat: float, start_lng: float,
              end_lat: float, end_lng: float,
              heat_weight: float = 0.0) -> dict:
        """Grid-based routing: ``heat_weight=0`` fastest, higher = cooler.

        A* on the real 100 m cell lattice. The coolest route penalises high
        predicted-LST cells, so it trades a little distance for shade/cooling.
        This is NOT road-network routing — it is a grid-level estimate.
        """
        self._load_grid()
        start = self.nearest_cell(start_lat, start_lng, max_km=3.0)
        end = self.nearest_cell(end_lat, end_lng, max_km=3.0)
        if start is None or end is None:
            return {"available": False,
                    "message": "Start/end must be within 3 km of the model grid."}
        start_id, end_id = str(start["grid_id"]), str(end["grid_id"])
        if start_id == end_id:
            return {"available": True, "fastest": None, "coolest": None,
                    "message": "Start and destination are in the same grid cell."}

        baseline = self._load_baseline()
        lngs = self._lngs
        lats = self._lats
        gids = self._gids
        index = {gid: i for i, gid in enumerate(gids)}
        n = len(gids)

        # Neighbour lists via a KD tree over centroids (built once per call).
        try:
            from scipy.spatial import cKDTree
        except ImportError as exc:  # pragma: no cover - scipy is a project dependency
            raise RuntimeError("scipy is required for routing.") from exc
        tree = cKDTree(np.column_stack([lngs, lats]))
        dist_km = _haversine_m(start["latitude"], start["longitude"],
                               end["latitude"], end["longitude"]) / 1000.0
        if dist_km > 40:
            return {"available": False,
                    "message": "Route distance exceeds the supported 40 km grid range."}

        cell_lst = np.full(n, np.nan)
        for gid, value in baseline.items():
            if gid in index and value is not None:
                cell_lst[index[gid]] = value
        lst_ref = float(np.nanpercentile(cell_lst, 60)) if np.isfinite(cell_lst).any() else 35.0
        lst_std = float(np.nanstd(cell_lst)) if np.isfinite(cell_lst).any() else 1.0

        straight_m = _haversine_m(start["latitude"], start["longitude"],
                                  end["latitude"], end["longitude"])
        # Budget for the coolest route: it may detour, but only up to ~1.7x
        # the straight-line distance (keeps the comparison meaningful).
        cool_budget_m = max(1.7 * straight_m, 4000.0)

        def astar(weight: float) -> dict | None:
            """A*; cost = distance * heat_factor.

            heat_factor is 1 for cells at or below the 60th percentile of
            predicted LST and grows linearly above it — so the "coolest"
            route only avoids genuinely hot cells and never rewards
            unbounded detours through cool areas.
            """
            start_i = index[start_id]
            end_i = index[end_id]
            if weight > 0:
                base = (cell_lst - lst_ref) / max(lst_std, 1e-6)
                base = np.clip(base, 0.0, 3.0)
                heat_cost = 1.0 + weight * base
            else:
                heat_cost = np.ones(n)
            budget = cool_budget_m if weight > 0 else math.inf

            def h(i: int) -> float:
                return _haversine_m(lats[i], lngs[i],
                                    lats[end_i], lngs[end_i])

            open_heap = [(0.0, start_i)]
            g_score = {start_i: 0.0}
            dist_so_far = {start_i: 0.0}
            came_from: dict[int, int] = {}
            closed: set[int] = set()
            steps = 0
            max_steps = max(6000, int(straight_m / 100.0) * 14)
            while open_heap and steps < max_steps:
                _, current = heapq.heappop(open_heap)
                if current == end_i:
                    break
                if current in closed:
                    continue
                closed.add(current)
                steps += 1
                clng, clat = lngs[current], lats[current]
                # 8 nearest neighbours (~100-140 m away on the 100 m grid)
                _, nbr_idx = tree.query([clng, clat], k=9)
                if nbr_idx.ndim == 1:
                    nbrs = nbr_idx
                else:
                    nbrs = nbr_idx[0]
                for j in nbrs:
                    j = int(j)
                    if j == current or j in closed:
                        continue
                    if not np.isfinite(heat_cost[j]) and weight > 0:
                        continue  # no LST data -> skip for coolest route
                    edge = _haversine_m(clat, clng, lats[j], lngs[j])
                    if dist_so_far[current] + edge > budget:
                        continue  # respect the detour budget
                    tentative = g_score[current] + edge * heat_cost[j]
                    if tentative < g_score.get(j, math.inf):
                        g_score[j] = tentative
                        dist_so_far[j] = dist_so_far[current] + edge
                        came_from[j] = current
                        heapq.heappush(open_heap, (tentative + h(j), j))
            if end_i not in g_score:
                return None
            # Reconstruct
            path_i: list[int] = []
            node = end_i
            while node != start_i:
                path_i.append(node)
                node = came_from.get(node, start_i)
                if len(path_i) > 5000:
                    break
            path_i.append(start_i)
            path_i.reverse()
            return _route_stats(path_i, lngs, lats, cell_lst, gids)

        fastest = astar(0.0)
        coolest = astar(0.28)
        return {
            "available": True,
            "fastest": fastest,
            "coolest": coolest,
            "note": "Grid-level estimate on the 100 m model lattice (not "
                    "road-network routing). 'Coolest' minimises distance "
                    "weighted by predicted LST. Times assume walking at "
                    f"{WALK_SPEED_KMH:.1f} km/h — labelled as an estimate, "
                    "not a medical/safety claim.",
            "speed_kmh": WALK_SPEED_KMH,
        }


def _route_stats(path_i, lngs, lats, cell_lst, gids) -> dict:
    coords = [[round(float(lngs[i]), 6), round(float(lats[i]), 6)] for i in path_i]
    distance_m = sum(
        _haversine_m(lats[a], lngs[a], lats[b], lngs[b])
        for a, b in itertools.pairwise(path_i)
    )
    lsts = [cell_lst[i] for i in path_i if np.isfinite(cell_lst[i])]
    return {
        "distance_m": round(distance_m, 0),
        "distance_km": round(distance_m / 1000.0, 2),
        "time_min": round(distance_m / 1000.0 / WALK_SPEED_KMH * 60.0, 1),
        "avg_lst_c": round(float(np.mean(lsts)), 2) if lsts else None,
        "max_lst_c": round(float(np.max(lsts)), 2) if lsts else None,
        "n_cells": len(path_i),
        "geometry": {
            "type": "LineString",
            "coordinates": coords,
        },
    }


def _risk_level(class_label: str | None, moderate: list[str],
                high: list[str]) -> dict:
    if class_label is None:
        return {"level": None, "label": "Unavailable", "tone": "na"}
    if class_label in high:
        return {"level": "High", "label": class_label, "tone": "high"}
    if class_label in moderate:
        return {"level": "Moderate", "label": class_label, "tone": "moderate"}
    return {"level": "Low", "label": class_label, "tone": "low"}


def _vegetation_risk(ndvi: float | None, green_cover: float | None) -> dict:
    if ndvi is None and green_cover is None:
        return {"level": None, "label": "Unavailable", "tone": "na"}
    if ndvi is not None:
        if ndvi < 0.2:
            return {"level": "High", "label": f"NDVI {ndvi:.2f}", "tone": "high"}
        if ndvi < 0.4:
            return {"level": "Moderate", "label": f"NDVI {ndvi:.2f}", "tone": "moderate"}
        return {"level": "Low", "label": f"NDVI {ndvi:.2f}", "tone": "low"}
    if green_cover is not None:
        if green_cover < 20:
            return {"level": "High", "label": f"Green cover {green_cover:.0f}%", "tone": "high"}
        if green_cover < 40:
            return {"level": "Moderate",
                    "label": f"Green cover {green_cover:.0f}%", "tone": "moderate"}
        return {"level": "Low",
                "label": f"Green cover {green_cover:.0f}%", "tone": "low"}
    return {"level": None, "label": "Unavailable", "tone": "na"}


def _density_risk(building_coverage_pct: float | None) -> dict:
    if building_coverage_pct is None:
        return {"level": None, "label": "Unavailable", "tone": "na"}
    if building_coverage_pct >= 60:
        return {"level": "High",
                "label": f"{building_coverage_pct:.0f}% built", "tone": "high"}
    if building_coverage_pct >= 30:
        return {"level": "Moderate",
                "label": f"{building_coverage_pct:.0f}% built", "tone": "moderate"}
    return {"level": "Low",
            "label": f"{building_coverage_pct:.0f}% built", "tone": "low"}


def _as_id(value) -> int | str:
    try:
        return int(value)
    except (TypeError, ValueError):
        return value
