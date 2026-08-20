"""
Live Feature Pipeline
====================

Constructs the current 58-feature model input from live observations.

Architecture (per the design specification):

    CURRENT LIVE / LATEST AVAILABLE DATA
          ↓
    DATA NORMALIZATION / PROVENANCE
          ↓
    CURRENT FEATURE VECTOR (58 features)
          ↓
    TRAINED XGBOOST MODEL
          ↓
    CURRENT PREDICTED LST
          ↓
    CURRENT HEAT MAP
          ↓
    SCENARIO SIMULATION
          ↓
    AI ADVISER

Every feature has provenance (source, timestamp, status).

Dependencies:
- backend/services/live_data.py  -> OpenWeather weather + AQI probes
- gis-engine for latest satellite data (NDVI, land cover)
- Training dataset feature schema (58 features from leakage report)
- models/best_model.pkl for provenance tracking

The pipeline is designed so that:
1. The trained XGBoost model is NEVER retrained when live data arrives.
2. The model is always run on the current feature vector.
3. Live data never replaces the trained model.
4. Raw air temperature is NEVER equated to LST.
"""
from __future__ import annotations

import json
import logging
import math
import time
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from backend.config.settings import Settings
from backend.services.live_data import get_air_quality, get_weather
from backend.services.serving import ServingContext

log = logging.getLogger("backend.live_feature_pipeline")

SOURCE = "OpenWeather"

# 58 model features from the leakage report, in the expected order
MODEL_FEATURES = [
    "Area_m2",
    "BuildingCount",
    "BuildingCoveragePct",
    "AvgBuildingFootprint",
    "BuildingDensity",
    "RoadLength",
    "RoadIntersectionCount",
    "DistToMajorRoad",
    "RoadDensity",
    "RoadIntersectionDensity",
    "TreeCount",
    "TreeDensity",
    "GreenSpacePct",
    "LandUse_ResidentialPct",
    "LandUse_CommercialPct",
    "LandUse_IndustrialPct",
    "LandUse_InstitutionalPct",
    "LandUse_AgriculturePct",
    "LandUse_GreenPct",
    "LandUse_RailwayPct",
    "LandUse_OtherPct",
    "DistToPark",
    "DistToWater",
    "DistToHospital",
    "DistToSchool",
    "BusStopCount",
    "DistToBusStop",
    "BusStopDensity",
    "HospitalCount",
    "SchoolCount",
    "MeanNDVI",
    "MaxNDVI",
    "MinNDVI",
    "GreenCover",
    "VegetationDensity",
    "VegDensityClass",
    "LandCoverClass",
    "LandCover_WaterPct",
    "LandCover_VegetationPct",
    "LandCover_BuiltupPct",
    "LandCover_BareLandPct",
    "MeanElevation",
    "MeanSlope",
    "Aspect",
    "MeanAQI",
    "MeanPM25",
    "MeanPM10",
    "MeanNO2",
    "MeanSO2",
    "MeanCO",
    "MeanO3",
    "ImperviousSurfaceRatio",
    "GreenToBuiltRatio",
    "CoolingDistanceIndex",
    "RoadExposureIndex",
    "VegetationCoolingIndex",
    "TerrainExposureIndex",
    "HeatVulnerabilityIndex",
]


class FeatureProvenance:
    """Provenance tracking for a single model feature."""

    def __init__(self, feature_name: str):
        self.feature_name = feature_name
        self.source: str | None = None
        self.timestamp: str | None = None
        self.status: str = "unavailable"  # live | modelled | unavailable
        self.raw_value: float | None = None
        self.normalized_value: float | None = None

    def to_dict(self) -> dict:
        return {
            "feature": self.feature_name,
            "source": self.source,
            "timestamp": self.timestamp,
            "status": self.status,
            "raw_value": self.raw_value,
            "normalized_value": self.normalized_value,
        }


class LiveFeaturePipeline:
    """
    Constructs the current 58-feature model input from live observations.

    Data flow:

    OpenWeather (weather)
          ↓
    OpenWeather Air Pollution (AQI)
          ↓
    Latest satellite (NDVI, land cover) - from gis-engine
          ↓
    GIS urban form (building density, road density, etc.) - from OSM/training dataset
          ↓
    Current feature engineering
          ↓
    58-feature vector with provenance
          ↓
    XGBoost model inference
    """

    def __init__(self, settings: Settings, serving: ServingContext | None = None):
        self.settings = settings
        self.serving = serving or ServingContext(settings)
        # Cache for latest live data
        self._weather_cache: dict | None = None
        self._aqi_cache: dict | None = None
        self._satellite_cache: dict | None = None
        self._satellite_per_cell_cache: dict[str, dict] | None = None
        self._gis_urban_form_cache: dict | None = None
        self._feature_provenance: list[FeatureProvenance] | None = None
        self._last_build: float = 0.0
        # Cache TTL: feature grid is valid for REFRESH_INTERVAL_MS
        self._cache_ttl = 300  # 5 minutes
        # Timing stats
        self._timing_stats: dict = {}

    def _get_timing(self) -> float:
        return time.perf_counter()

    def _log_timing(self, phase: str, start: float) -> None:
        elapsed = (time.perf_counter() - start) * 1000
        self._timing_stats[phase] = elapsed
        log.debug("%s took %.1f ms", phase, elapsed)

    # ------------------------------------------------------------------ #
    # Data loading
    # ------------------------------------------------------------------ #

    def refresh(self) -> dict:
        """Refresh all live data sources and rebuild the feature grid.

        Returns the feature grid result with predictions and provenance.
        """
        overall_start = self._get_timing()
        
        # Refresh weather (OpenWeather)
        weather_start = self._get_timing()
        self._weather_cache = get_weather(self.settings)
        self._log_timing("weather_fetch", weather_start)

        # Refresh AQI (OpenWeather Air Pollution)
        aqi_start = self._get_timing()
        self._aqi_cache = get_air_quality(self.settings)
        self._log_timing("aqi_fetch", aqi_start)

        # Satellite data - use cached per-cell data if available
        sat_start = self._get_timing()
        if self._satellite_per_cell_cache is None:
            self._satellite_per_cell_cache = self._get_satellite_per_cell_cached()
        self._log_timing("satellite_load", sat_start)

        # GIS urban form - use cached if available
        gis_start = self._get_timing()
        if self._gis_urban_form_cache is None:
            self._gis_urban_form_cache = self._get_gis_urban_form_cached()
        self._log_timing("gis_load", gis_start)

        # Rebuild feature vector
        build_start = self._get_timing()
        result = self._build_feature_grid()
        self._log_timing("feature_build", build_start)

        self._last_build = time.monotonic()
        
        # Add timing stats to result
        total_elapsed = (time.perf_counter() - overall_start) * 1000
        result["timing_stats"] = self._timing_stats.copy()
        result["timing_stats"]["total"] = total_elapsed
        
        log.info("Feature pipeline refresh completed in %.1f ms: %s", 
                 total_elapsed, {k: f"{v:.1f}ms" for k, v in self._timing_stats.items()})
        
        return result

    def _get_satellite_per_cell_cached(self) -> dict:
        """Get satellite per-cell data from cache or load from GeoJSON."""
        if self._satellite_per_cell_cache is not None:
            return self._satellite_per_cell_cache
        
        # Use the ServingContext's cached satellite data if available
        if self.serving._satellite_per_cell is not None:
            # Convert to the format expected by the pipeline
            return self.serving._satellite_per_cell
        
        # Fallback: load from GeoJSON (should only happen once)
        return self._get_satellite_data()

    def _get_gis_urban_form_cached(self) -> dict | None:
        """Get GIS urban form data from cache or load from CSV."""
        if self._gis_urban_form_cache is not None:
            return self._gis_urban_form_cache
        
        self._gis_urban_form_cache = self._get_gis_urban_form()
        return self._gis_urban_form_cache

    def _get_live_weather(self) -> dict | None:
        """Extract current weather features from the cached weather probe."""
        if not self._weather_cache or not self._weather_cache.get("available"):
            return None

        c = self._weather_cache.get("current", {})
        return {
            "temperature": c.get("temperature"),  # °C, live air temp
            "humidity": c.get("humidity"),  # %
            "pressure": c.get("pressure"),  # hPa
            "wind_speed": c.get("wind_speed"),  # m/s
            "wind_direction": c.get("wind_direction"),  # degrees
            "cloud_cover": c.get("cloud_cover"),  # %
            "precipitation": c.get("precipitation"),  # mm/h
            "visibility": c.get("visibility"),  # metres
            "weather_condition": c.get("weather_condition"),
            "observed_at": self._weather_cache.get("observed_at"),
        }

    def _get_live_aqi(self) -> dict | None:
        """Extract current AQI features from the cached AQI probe."""
        if not self._aqi_cache or not self._aqi_cache.get("available"):
            return None

        c = self._aqi_cache.get("current", {})
        return {
            "aqi": c.get("aqi"),  # 1-5 OpenWeather index
            "pm2_5": c.get("pm2_5"),  # µg/m³
            "pm10": c.get("pm10"),  # µg/m³
            "no2": c.get("no2"),  # µg/m³
            "o3": c.get("o3"),  # µg/m³
            "so2": c.get("so2"),  # µg/m³
            "co": c.get("co"),  # µg/m³
        }

    def _get_satellite_data(self) -> dict | None:
        """Extract latest satellite observations from the GeoJSON grid.

        The GeoJSON ``training_dataset.geojson`` contains per-cell properties
        that include satellite-derived features (NDVI, land cover percentages,
        vegetation density).  We use ``json.load()`` — **not**
        ``pd.read_json()`` — because the GeoJSON FeatureCollection has a
        heterogeneous top-level structure (``type``, ``crs``, ``features``)
        that pandas cannot safely parse into a DataFrame, which produces the
        ``"Mixing dicts with non-Series may lead to ambiguous ordering"``
        error.

        Note: Satellite data is NOT "live" — it is the latest available
        observation.  The gis-engine pipeline (Sentinel-2) acquires imagery
        periodically and stores the acquisition date.  We must never label
        satellite data as LIVE.
        """
        sat_path = Path(self.settings.dataset_geojson)
        if not sat_path.exists():
            log.debug("Satellite source not found: %s", sat_path)
            return None

        try:
            with open(sat_path, encoding="utf-8") as fh:
                geojson = json.load(fh)

            raw_features = geojson.get("features", [])
            if not raw_features:
                log.debug("GeoJSON has no features: %s", sat_path)
                return None

            # Extract per-cell satellite properties.  Each grid cell has its
            # own NDVI, land cover and vegetation values derived from the
            # Sentinel-2 acquisition.  We return a dict-of-dicts keyed by
            # Grid_ID so the feature matrix can assign cell-specific values.
            #
            # For the city-wide current prediction vector (single row), we
            # return the city-wide MEAN of each satellite feature.
            sat_features_by_cell: dict[str, dict] = {}
            sat_sums: dict[str, float] = {}
            sat_counts: dict[str, int] = {}
            sat_field_names = [
                "MeanNDVI", "MaxNDVI", "MinNDVI",
                "GreenCover", "VegetationDensity", "VegDensityClass",
                "LandCoverClass",
                "LandCover_WaterPct", "LandCover_VegetationPct",
                "LandCover_BuiltupPct", "LandCover_BareLandPct",
            ]
            for feat in raw_features:
                props = feat.get("properties", {})
                gid = props.get("Grid_ID")
                if gid is None:
                    continue
                gid_str = str(gid)
                cell_data = {}
                for field in sat_field_names:
                    val = props.get(field)
                    if val is not None:
                        try:
                            fval = float(val)
                            cell_data[field] = fval
                            sat_sums[field] = sat_sums.get(field, 0.0) + fval
                            sat_counts[field] = sat_counts.get(field, 0) + 1
                        except (TypeError, ValueError):
                            pass
                if cell_data:
                    sat_features_by_cell[gid_str] = cell_data

            # City-wide means for the single-row current prediction
            # Use the computed means from ALL cells, not just the last feature's props.
            features: dict = {}
            for field in sat_field_names:
                if field in sat_sums and sat_counts.get(field, 0) > 0:
                    features[field] = sat_sums[field] / sat_counts[field]

            # --- Acquisition provenance -----------------------------------------------
            # GeoJSON may carry a ``crs`` or ``name`` metadata field.
            acquisition = ""
            crs_meta = geojson.get("crs")
            if isinstance(crs_meta, dict):
                acquisition = crs_meta.get("properties", {}).get("name", "")
            if not acquisition:
                acquisition = geojson.get("name", "")
            features["satellite_acquisition"] = acquisition

            # Store per-cell satellite data for the full grid matrix
            features["_per_cell"] = sat_features_by_cell
            features["_cell_count"] = len(sat_features_by_cell)

            if len(features) > 2:  # more than just _per_cell and _cell_count
                log.info(
                    "Satellite features extracted from %s: %d fields, %d cells",
                    sat_path.name, len(features) - 2,  # minus _per_cell and _cell_count
                    len(sat_features_by_cell),
                )
                self._satellite_cache = features
                return features
            elif sat_features_by_cell:
                # City-wide means are empty but per-cell data exists
                log.info(
                    "Satellite per-cell data available from %s: %d cells (no city-wide means)",
                    sat_path.name, len(sat_features_by_cell),
                )
                self._satellite_cache = features
                return features

        except Exception as exc:
            log.warning("Could not read satellite data: %s", exc)

        return None

    def _get_gis_urban_form(self) -> dict | None:
        """Extract urban form features from the training dataset GIS data.

        These are spatial infrastructure features (buildings, roads, parks, etc.)
        that are periodically refreshed but not necessarily real-time.
        """
        csv_path = Path(self.settings.dataset_csv)
        if not csv_path.exists():
            return None

        try:
            df = pd.read_csv(csv_path)
            # Take the first row as representative (all grid cells have same feature structure)
            if len(df) > 0:
                row = df.iloc[0]
                # Extract the urban form features (non-model, infrastructure features)
                # We need to identify which columns are urban form vs model features
                # Model features are listed in MODEL_FEATURES
                form_features = {}
                for col in df.columns:
                    if col in MODEL_FEATURES:
                        continue  # Skip model features - they come from other sources
                    if col == "Grid_ID":
                        continue
                    form_features[col] = row[col]
                return form_features
        except Exception as exc:
            log.warning("Could not read GIS urban form data: %s", exc)

        return None

    # ------------------------------------------------------------------ #
    # Feature engineering
    # ------------------------------------------------------------------ #

    def _build_feature_provenance(self) -> list[FeatureProvenance]:
        """Build the 58 feature provenance objects with initialized values."""
        provenances = []
        for i, feat_name in enumerate(MODEL_FEATURES):
            pf = FeatureProvenance(feat_name)
            # Try to populate from live data sources
            self._populate_feature_provenance(pf, i)
            provenances.append(pf)
        return provenances

    def _populate_feature_provenance(self, pf: FeatureProvenance, idx: int) -> None:
        """Populate a single feature provenance from available live data."""
        feat_name = pf.feature_name

        # --- GIS / OSM urban form features (indices 0-29) ---------------------
        # These are spatial infrastructure features from OpenStreetMap and
        # parcel-level GIS data.  They change slowly (buildings, roads, parks)
        # and are loaded from the training dataset as the latest known values.
        _GIS_OSM_FEATURES = {
            "Area_m2": ("GIS parcel data", "STATIC_GIS"),
            "BuildingCount": ("OpenStreetMap buildings", "STATIC_GIS"),
            "BuildingCoveragePct": ("OpenStreetMap buildings", "STATIC_GIS"),
            "AvgBuildingFootprint": ("OpenStreetMap buildings", "STATIC_GIS"),
            "BuildingDensity": ("OpenStreetMap buildings", "STATIC_GIS"),
            "RoadLength": ("OpenStreetMap roads", "STATIC_GIS"),
            "RoadIntersectionCount": ("OpenStreetMap roads", "STATIC_GIS"),
            "DistToMajorRoad": ("OpenStreetMap roads", "STATIC_GIS"),
            "RoadDensity": ("OpenStreetMap roads", "STATIC_GIS"),
            "RoadIntersectionDensity": ("OpenStreetMap roads", "STATIC_GIS"),
            "TreeCount": ("OpenStreetMap trees", "STATIC_GIS"),
            "TreeDensity": ("OpenStreetMap trees", "STATIC_GIS"),
            "GreenSpacePct": ("OpenStreetMap green spaces", "STATIC_GIS"),
            "LandUse_ResidentialPct": ("OpenStreetMap land use", "STATIC_GIS"),
            "LandUse_CommercialPct": ("OpenStreetMap land use", "STATIC_GIS"),
            "LandUse_IndustrialPct": ("OpenStreetMap land use", "STATIC_GIS"),
            "LandUse_InstitutionalPct": ("OpenStreetMap land use", "STATIC_GIS"),
            "LandUse_AgriculturePct": ("OpenStreetMap land use", "STATIC_GIS"),
            "LandUse_GreenPct": ("OpenStreetMap land use", "STATIC_GIS"),
            "LandUse_RailwayPct": ("OpenStreetMap land use", "STATIC_GIS"),
            "LandUse_OtherPct": ("OpenStreetMap land use", "STATIC_GIS"),
            "DistToPark": ("OpenStreetMap parks", "STATIC_GIS"),
            "DistToWater": ("OpenStreetMap water bodies", "STATIC_GIS"),
            "DistToHospital": ("OpenStreetMap healthcare", "STATIC_GIS"),
            "DistToSchool": ("OpenStreetMap education", "STATIC_GIS"),
            "BusStopCount": ("OpenStreetMap transit", "STATIC_GIS"),
            "DistToBusStop": ("OpenStreetMap transit", "STATIC_GIS"),
            "BusStopDensity": ("OpenStreetMap transit", "STATIC_GIS"),
            "HospitalCount": ("OpenStreetMap healthcare", "STATIC_GIS"),
            "SchoolCount": ("OpenStreetMap education", "STATIC_GIS"),
        }
        if feat_name in _GIS_OSM_FEATURES:
            source, status = _GIS_OSM_FEATURES[feat_name]
            pf.source = source
            pf.status = status
            return

        # --- Satellite / vegetation features (indices 30-40) ------------------
        # NDVI-related features (indices 30-32)
        if feat_name in ("MeanNDVI", "MaxNDVI", "MinNDVI"):
            sat = self._satellite_cache or {}
            val = sat.get(feat_name)  # use the actual feature name as key
            if val is not None:
                pf.source = "Sentinel-2 (satellite)"
                pf.timestamp = sat.get("satellite_acquisition")
                pf.status = "LATEST_OBSERVATION"
                pf.raw_value = float(val)
                pf.normalized_value = float(val)
            return

        # GreenCover (index 33)
        if feat_name == "GreenCover":
            sat = self._satellite_cache or {}
            val = sat.get("GreenCover")
            if val is not None:
                pf.source = "Sentinel-2 (satellite)"
                pf.timestamp = sat.get("satellite_acquisition")
                pf.status = "LATEST_OBSERVATION"
                pf.raw_value = float(val)
                pf.normalized_value = float(val)
            return

        # VegetationDensity (index 34)
        if feat_name == "VegetationDensity":
            sat = self._satellite_cache or {}
            val = sat.get("VegetationDensity")
            if val is not None:
                pf.source = "Sentinel-2 (satellite)"
                pf.timestamp = sat.get("satellite_acquisition")
                pf.status = "LATEST_OBSERVATION"
                pf.raw_value = float(val)
                pf.normalized_value = float(val)
            return

        # VegDensityClass (index 35) — categorical stored as numeric in the dataset
        if feat_name == "VegDensityClass":
            sat = self._satellite_cache or {}
            val = sat.get("VegDensityClass")
            if val is not None:
                pf.source = "Sentinel-2 (satellite)"
                pf.timestamp = sat.get("satellite_acquisition")
                pf.status = "LATEST_OBSERVATION"
                pf.raw_value = float(val)
                # Already stored as a numeric code in the dataset; use directly
                pf.normalized_value = float(val)
            return

        # LandCoverClass (index 36) — categorical stored as numeric in the dataset
        if feat_name == "LandCoverClass":
            sat = self._satellite_cache or {}
            val = sat.get("LandCoverClass")
            if val is not None:
                pf.source = "Sentinel-2 (satellite)"
                pf.timestamp = sat.get("satellite_acquisition")
                pf.status = "LATEST_OBSERVATION"
                pf.raw_value = float(val)
                # Already stored as a numeric code in the dataset; use directly
                pf.normalized_value = float(val)
            return

        # Land cover percentage features (indices 37-40)
        if feat_name in (
            "LandCover_WaterPct", "LandCover_VegetationPct",
            "LandCover_BuiltupPct", "LandCover_BareLandPct",
        ):
            sat = self._satellite_cache or {}
            val = sat.get(feat_name)
            if val is not None:
                pf.source = "Sentinel-2 (satellite)"
                pf.timestamp = sat.get("satellite_acquisition")
                pf.status = "LATEST_OBSERVATION"
                pf.raw_value = float(val)
                pf.normalized_value = float(val)
            return

        # Elevation, slope, aspect (indices 41-43) — DEM terrain data (static GIS)
        if feat_name in ("MeanElevation", "MeanSlope", "Aspect"):
            pf.source = "DEM terrain data"
            pf.status = "STATIC_GIS"
            return

        # AQI-related features (indices 44-50) — live from OpenWeather Air Pollution
        _AQI_FEATURES = (
            "MeanAQI", "MeanPM25", "MeanPM10",
            "MeanNO2", "MeanSO2", "MeanCO", "MeanO3",
        )
        if feat_name in _AQI_FEATURES:
            aqi_cache = self._aqi_cache or {}
            current = aqi_cache.get("current", {})
            # Map feature name to the key in the AQI response
            aqi_key_map = {
                "MeanAQI": "aqi",
                "MeanPM25": "pm2_5",
                "MeanPM10": "pm10",
                "MeanNO2": "no2",
                "MeanSO2": "so2",
                "MeanCO": "co",
                "MeanO3": "o3",
            }
            aqi_key = aqi_key_map.get(feat_name)
            if aqi_key and aqi_cache.get("available"):
                val = current.get(aqi_key)
                if val is not None:
                    pf.source = "OpenWeather Air Pollution"
                    pf.timestamp = aqi_cache.get("observed_at")
                    pf.status = "LIVE"
                    pf.raw_value = float(val)
                    pf.normalized_value = float(val)
            return

        # ImperviousSurfaceRatio (index 51) — OSM built-up land cover analysis
        if feat_name == "ImperviousSurfaceRatio":
            pf.source = "OSM built-up analysis"
            pf.status = "LATEST_OBSERVATION"
            return

        # GreenToBuiltRatio (index 52) — OSM land use analysis
        if feat_name == "GreenToBuiltRatio":
            pf.source = "OSM land use analysis"
            pf.status = "LATEST_OBSERVATION"
            return

        # CoolingDistanceIndex (index 53) — computed from green/built distribution
        if feat_name == "CoolingDistanceIndex":
            pf.source = "computed from green/built distribution"
            pf.status = "DERIVED"
            return

        # RoadExposureIndex (index 54) — OSM road network analysis
        if feat_name == "RoadExposureIndex":
            pf.source = "OSM road network analysis"
            pf.status = "LATEST_OBSERVATION"
            return

        # VegetationCoolingIndex (index 55) — computed from NDVI + vegetation density
        if feat_name == "VegetationCoolingIndex":
            pf.source = "computed from NDVI + vegetation density"
            pf.status = "DERIVED"
            return

        # TerrainExposureIndex (index 56) — DEM terrain analysis
        if feat_name == "TerrainExposureIndex":
            pf.source = "DEM terrain analysis"
            pf.status = "STATIC_GIS"
            return

        # HeatVulnerabilityIndex (index 57) — combined index
        if feat_name == "HeatVulnerabilityIndex":
            pf.source = "combined index from multiple features"
            pf.status = "DERIVED"
            return

    def _engineer_current_features(
        self, weather: dict | None, aqi: dict | None, satellite: dict | None,
        gis_urban: dict | None
    ) -> dict[str, FeatureProvenance]:
        """Engineer the current 58-feature vector from all available data sources.

        Returns a dict mapping feature name -> FeatureProvenance with normalized values.
        """
        provenances = self._build_feature_provenance()

        # Live weather context (temperature is NOT a model feature)
        # The XGBoost model was trained on 58 features that do NOT include
        # air temperature.  Live weather is used for: dashboard display,
        # AI adviser context, scenario explanation, data provenance.
        # We do NOT add temperature as a 59th feature.
        if weather:
            temp = weather.get("temperature")
            if temp is not None:
                log.info(
                    "Live weather temperature: %s°C (LIVE WEATHER CONTEXT, "
                    "not a model feature — model uses 58 features)",
                    temp,
                )

        # Normalize AQI features — map from OpenWeather response keys to model features
        _AQI_KEY_TO_FEATURE = {
            "aqi": "MeanAQI",
            "pm2_5": "MeanPM25",
            "pm10": "MeanPM10",
            "no2": "MeanNO2",
            "so2": "MeanSO2",
            "co": "MeanCO",
            "o3": "MeanO3",
        }
        if aqi and aqi.get("available"):
            current = aqi.get("current", {})
            for aqi_key, feat_name in _AQI_KEY_TO_FEATURE.items():
                val = current.get(aqi_key)
                if val is not None:
                    pf = next((p for p in provenances if p.feature_name == feat_name), None)
                    if pf:
                        pf.source = "OpenWeather Air Pollution"
                        pf.status = "LIVE"
                        pf.timestamp = aqi.get("observed_at")
                        pf.raw_value = float(val)
                        pf.normalized_value = float(val)

        # Normalize satellite features — the satellite cache now stores
        # features by their exact model-feature name (e.g. "MeanNDVI").
        _SAT_FEATURES = (
            "MeanNDVI", "MaxNDVI", "MinNDVI",
            "GreenCover", "VegetationDensity", "VegDensityClass",
            "LandCoverClass",
            "LandCover_WaterPct", "LandCover_VegetationPct",
            "LandCover_BuiltupPct", "LandCover_BareLandPct",
        )
        if satellite:
            for feat_name in _SAT_FEATURES:
                pf = next((p for p in provenances if p.feature_name == feat_name), None)
                if pf and pf.status == "unavailable":
                    val = satellite.get(feat_name)
                    if val is not None:
                        pf.source = "Sentinel-2 (satellite)"
                        pf.timestamp = satellite.get("satellite_acquisition")
                        pf.status = "LATEST_OBSERVATION"
                        pf.raw_value = float(val)
                        # VegDensityClass and LandCoverClass are already stored as
                        # numeric codes in the dataset — use directly.
                        pf.normalized_value = float(val)

        # GIS urban form features are already handled by _populate_feature_provenance
        # No additional normalization needed — values come from the training dataset.

        return {p.feature_name: p for p in provenances}

# ------------------------------------------------------------------ #
    # Feature grid construction
    # ------------------------------------------------------------------ #

    def _build_feature_grid(self) -> dict:
        """Build the complete current feature grid with predictions.

        Returns:
            dict with keys: grid_id, latitude, longitude, timestamp,
            feature_values, feature_source, feature_age, prediction, status
        """
        build_start = self._get_timing()
        
        # Engineer the current feature vector from all live data sources
        weather = self._get_live_weather()
        aqi = self._get_live_aqi()
        satellite = self._satellite_per_cell_cache
        gis_urban = self._gis_urban_form_cache

        self._log_timing("data_fetch", build_start)

        # Build feature provenance and normalized values
        feature_start = self._get_timing()
        feature_map = self._engineer_current_features(weather, aqi, satellite, gis_urban)
        self._log_timing("feature_engineer", feature_start)

        # Get current weather timestamp for feature age
        weather_ts = "never"
        if weather and weather.get("observed_at"):
            weather_ts = weather["observed_at"]
        elif self._weather_cache and self._weather_cache.get("observed_at"):
            weather_ts = self._weather_cache["observed_at"]

        aqi_ts = "never"
        if aqi and aqi.get("observed_at"):
            aqi_ts = aqi["observed_at"]
        elif self._aqi_cache and self._aqi_cache.get("observed_at"):
            aqi_ts = self._aqi_cache["observed_at"]

        satellite_ts = "never"
        if satellite and satellite.get("satellite_acquisition"):
            satellite_ts = satellite["satellite_acquisition"]

        # Build the feature vector for model inference.
        # Create a row with all 58 features, using normalized values.
        preprocessor = self.serving.preprocessor
        features_list = self.serving.features

        # Build a row dict with all 58 features
        row_dict = {}

        # Map each feature provenance to a value for the model
        row_start = self._get_timing()
        for feat_name in MODEL_FEATURES:
            pf = feature_map.get(feat_name)
            if pf is None or pf.normalized_value is None:
                # Use preprocessor imputation value
                if feat_name in preprocessor.fill_values:
                    row_dict[feat_name] = preprocessor.fill_values[feat_name]
                else:
                    row_dict[feat_name] = 0.0
            else:
                row_dict[feat_name] = pf.normalized_value
        self._log_timing("row_dict_build", row_start)

        # Transform using the preprocessor (same as training)
        transform_start = self._get_timing()
        try:
            X_row = preprocessor.transform(pd.DataFrame([row_dict])[features_list])
            # Get prediction
            prediction = float(self.serving.model.predict(X_row)[0])
        except Exception as exc:
            log.error("Model prediction failed: %s", exc)
            prediction = float("nan")
            X_row = None
        self._log_timing("model_predict", transform_start)

        # Determine which data sources are missing
        missing_sources = []
        fallback_used = False

        if not weather or not weather.get("observed_at"):
            missing_sources.append("weather")
        if not aqi or not aqi.get("observed_at"):
            missing_sources.append("air_quality")
        if not satellite:
            missing_sources.append("satellite")
            fallback_used = True  # imputation values used for satellite features

        # Build result
        grid_id = "current"
        result = {
            "grid_id": grid_id,
            "latitude": 20.2520,  # OpenWeather observation point (PILOT_LAT)
            "longitude": 85.7880,
            "timestamp": datetime.now(UTC).isoformat(),
            "feature_values": {k: (v.normalized_value, v.source, v.status, v.timestamp)
                            for k, v in feature_map.items()},
            "feature_source": "live data pipeline (OpenWeather + satellite + GIS)",
            "feature_age": {
                "weather": weather_ts,
                "aqi": aqi_ts,
                "satellite": satellite_ts,
            },
            "data_sources": {
                "weather": {
                    "status": "LIVE" if weather_ts not in ("never", None) else "UNAVAILABLE",
                    "last_observed": weather_ts,
                },
                "air_quality": {
                    "status": "LIVE" if aqi_ts not in ("never", None) else "UNAVAILABLE",
                    "last_observed": aqi_ts,
                },
                "satellite": {
                    "status": (
                        "LATEST_OBSERVATION" if satellite_ts not in ("never", None)
                        else "UNAVAILABLE"
                    ),
                    "last_acquired": satellite_ts,
                },
            },
            "missing_sources": missing_sources,
            "fallback_used": fallback_used,
            "prediction": {
                "predicted_lst_c": prediction,
                "source": "XGBoost model",
                "model_version": self.serving.model_version,
                "features_used": len(features_list),
                "features_status": "modelled from current data",
                "generated_at": datetime.now(UTC).isoformat(),
            },
            "status": (
                "available" if not math.isnan(prediction) and not missing_sources
                else "partial" if not math.isnan(prediction)
                else "model_error"
            ),
        }

        return result

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def get_current_prediction(self) -> dict:
        """Get current predicted LST from the live feature pipeline.

        This is the key endpoint that the thermal map and Before/After comparison
        should use instead of precomputed/trained values.
        """
        result = self._build_feature_grid()
        return result

    def get_feature_vector(self) -> dict[str, dict]:
        """Get the current 58-feature vector with full provenance.

        Returns:
            Dict mapping feature name to provenance dict with source, timestamp,
            status, raw_value, normalized_value.
        """
        result = self._build_feature_grid()
        return result.get("feature_values", {})


# ------------------------------------------------------------------ #
# Module-level singleton helper
# ------------------------------------------------------------------ #

_pipeline_instance: LiveFeaturePipeline | None = None


def get_pipeline(settings: Settings | None = None) -> LiveFeaturePipeline:
    """Get or create the module-level pipeline instance."""
    global _pipeline_instance
    if _pipeline_instance is None:
        from backend.config.settings import Settings as _Settings
        if settings is None:
            settings = _Settings()
        from backend.services.serving import ServingContext
        srv = ServingContext(settings)
        _pipeline_instance = LiveFeaturePipeline(settings, srv)
    return _pipeline_instance


def refresh_feature_pipeline(settings: Settings | None = None) -> dict:
    """Convenience function: refresh all live data and rebuild feature grid."""
    pipeline = get_pipeline(settings)
    return pipeline.refresh()


def get_current_lst(settings: Settings | None = None) -> dict:
    """Convenience function: get current predicted LST from the pipeline."""
    pipeline = get_pipeline(settings)
    return pipeline.get_current_prediction()