"""
Central configuration for the GIS Feature Engineering Engine
=============================================================
All input paths, grid settings, land-cover class mappings, weather column
mappings, derived-feature weights and output locations are defined here so
the rest of the pipeline stays parameter-free.

Run the pipeline with::

    cd gis-engine/feature_engineering
    python main.py
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

# scripts/feature_engineering/config.py -> scripts -> project root
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def slug(value: str) -> str:
    """Sanitise a label into a safe ML column name (no spaces / punctuation)."""
    out = []
    for ch in str(value):
        if ch.isalnum():
            out.append(ch)
        elif ch in (" ", "-", "/", "_", "."):
            out.append("_")
    return "_".join("".join(out).split("_"))


@dataclass
class PathsConfig:
    """Every input file / directory the engine reads, plus output locations."""

    # --- Boundary ---------------------------------------------------------
    boundary: Path = PROJECT_ROOT / "boundary.geojson"

    # --- Vector inputs (OSM feature layers, extracted by scripts/extract_osm_layers.py) --
    osm_layers: Path = PROJECT_ROOT / "data" / "raw" / "osm" / "layers"
    # logical layer name -> candidate file names (first existing one wins).
    # This keeps the engine robust to the exact naming of the GeoJSON files
    # (e.g. Roads.geojson vs all_highway.geojson).
    vector_layers: Dict[str, List[str]] = field(default_factory=lambda: {
        "roads":      ["all_highway.geojson", "Roads.geojson"],
        "buildings":  ["all_building.geojson", "Buildings.geojson"],
        "parks":      ["parks.geojson", "all_leisure.geojson", "Parks.geojson"],
        "trees":      ["trees.geojson", "Trees.geojson"],
        "water":      ["all_water.geojson", "water_bodies.geojson", "Water.geojson"],
        "landuse":    ["all_landuse.geojson", "LandUse.geojson"],
        "schools":    ["buildings_school.geojson", "schools.geojson", "Schools.geojson"],
        "hospitals":  ["buildings_hospital.geojson", "all_healthcare.geojson",
                       "healthcare_hospitals.geojson", "Hospitals.geojson"],
        "railways":   ["landuse_railway.geojson", "Railways.geojson"],
        "bus_stops":  ["bus_stops.geojson", "BusStops.geojson"],
        # green-space contributors (merged to compute GreenSpacePct)
        "green_extra": ["forests.geojson", "landuse_grass.geojson", "gardens.geojson",
                        "natural_grassland.geojson", "tree_rows.geojson"],
    })

    # --- Raster inputs ----------------------------------------------------
    ndvi: Path = PROJECT_ROOT / "data" / "processed" / "ndvi" / "ndvi.tif"
    greencover: Path = PROJECT_ROOT / "data" / "processed" / "greencover" / "green_cover.tif"
    vegetation: Path = PROJECT_ROOT / "data" / "processed" / "vegetation" / "vegetation_density.tif"
    landcover: Path = PROJECT_ROOT / "data" / "processed" / "landcover" / "landcover.tif"
    lst: Path = PROJECT_ROOT / "data" / "processed" / "lst" / "LST.tif"
    lst_stats: Path = PROJECT_ROOT / "data" / "processed" / "lst" / "LST_statistics.json"
    elevation: Path = PROJECT_ROOT / "data" / "processed" / "elevation" / "Elevation.tif"
    slope: Path = PROJECT_ROOT / "data" / "processed" / "slope" / "Slope.tif"
    aspect: Path = PROJECT_ROOT / "data" / "processed" / "aspect" / "Aspect.tif"
    aqi_dir: Path = PROJECT_ROOT / "data" / "processed" / "aqi" / "rasters"

    # --- Weather inputs ---------------------------------------------------
    weather_daily: Path = PROJECT_ROOT / "data" / "processed" / "weather" / "weather_daily.csv"
    weather_monthly: Path = PROJECT_ROOT / "data" / "processed" / "weather" / "weather_monthly.csv"

    # --- Outputs ----------------------------------------------------------
    output: Path = PROJECT_ROOT / "data" / "feature_engineering"
    intermediate: Path = PROJECT_ROOT / "data" / "intermediate"
    plots: Path = PROJECT_ROOT / "data" / "feature_engineering" / "plots"
    reports: Path = PROJECT_ROOT / "data" / "feature_engineering" / "reports"

    # --- Final deliverables ----------------------------------------------
    dataset_csv: Path = PROJECT_ROOT / "data" / "feature_engineering" / "training_dataset.csv"
    dataset_normalized_csv: Path = (
        PROJECT_ROOT / "data" / "feature_engineering" / "training_dataset_normalized.csv"
    )
    dataset_geojson: Path = (
        PROJECT_ROOT / "data" / "feature_engineering" / "training_dataset.geojson"
    )
    feature_statistics: Path = (
        PROJECT_ROOT / "data" / "feature_engineering" / "feature_statistics.json"
    )
    correlation_matrix: Path = (
        PROJECT_ROOT / "data" / "feature_engineering" / "correlation_matrix.csv"
    )
    feature_importance: Path = (
        PROJECT_ROOT / "data" / "feature_engineering" / "feature_importance_baseline.csv"
    )
    missing_value_report: Path = (
        PROJECT_ROOT / "data" / "feature_engineering" / "missing_value_report.json"
    )
    quality_report: Path = (
        PROJECT_ROOT / "data" / "feature_engineering" / "quality_report.json"
    )

    def ensure(self) -> None:
        """Create all output directories (idempotent)."""
        for d in (self.output, self.intermediate, self.plots, self.reports):
            d.mkdir(parents=True, exist_ok=True)


@dataclass
class GridConfig:
    """STEP 1 - regular grid settings."""

    cell_size_m: float = 100.0          # 100 m x 100 m cells
    target_epsg: int = 32645            # UTM 45N - projected working CRS (metres)
    wgs84_epsg: int = 4326              # WGS84 lat/lon for output coordinates


@dataclass
class LandcoverConfig:
    """Class codes written by the Sentinel-2 processing stage (1-indexed)."""

    classes: Dict[int, str] = field(default_factory=lambda: {
        1: "Water",
        2: "Vegetation",
        3: "Built-up",
        4: "Bare Land",
    })

    @property
    def class_names(self) -> List[str]:
        return list(self.classes.values())


@dataclass
class VectorConfig:
    """Highway taxonomy + coarse land-use grouping used by vector_features."""

    # Motorised roads counted for RoadLength / RoadDensity /
    # RoadIntersectionDensity (footways, cycleways, paths, steps, tracks excluded).
    road_highway_types: List[str] = field(default_factory=lambda: [
        "motorway", "trunk", "primary", "secondary", "tertiary",
        "unclassified", "residential", "service", "living_street", "pedestrian",
        "primary_link", "secondary_link", "tertiary_link", "trunk_link",
        "motorway_link", "construction", "raceway", "bus_guideway",
    ])
    # Arterial roads used for "Distance to Major Road".
    major_road_types: List[str] = field(default_factory=lambda: [
        "motorway", "trunk", "primary", "secondary", "tertiary",
        "primary_link", "secondary_link", "tertiary_link", "trunk_link", "motorway_link",
    ])
    # OSM `landuse` values -> coarse class (used for LandUse percentage columns).
    landuse_groups: Dict[str, List[str]] = field(default_factory=lambda: {
        "Residential":    ["residential"],
        "Commercial":     ["commercial", "retail", "garages", "depot", "port", "harbour"],
        "Industrial":     ["industrial", "quarry", "landfill", "brownfield"],
        "Institutional":  ["education", "religious", "military"],
        "Agriculture":    ["farmland", "farmyard", "agriculture", "orchard", "vineyard",
                           "greenhouse_horticulture", "greenfield", "allotments"],
        "Green":          ["forest", "grass", "meadow", "recreation_ground", "cemetery",
                           "village_green"],
        "Railway":        ["railway"],
    })


@dataclass
class WeatherConfig:
    """STEP 4 - weather column mapping (daily + monthly CSVs)."""

    # weather_daily.csv column -> feature column
    column_map: Dict[str, str] = field(default_factory=lambda: {
        "T2M": "Temperature",
        "RH2M": "Humidity",
        "WS2M": "WindSpeed",
        "PS": "Pressure",
        "ALLSKY_SFC_SW_DWN": "SolarRadiation",
        "PRECTOTCORR": "Rainfall",
        "HEAT_INDEX": "HeatIndex",
    })
    rolling_suffix: str = "_7d"     # rolling columns already present: T2M_7d, RH2M_7d, ...
    monthly_suffix: str = "_MonthlyMean"
    date_col: str = "date"
    season_col: str = "season"


@dataclass
class DerivedConfig:
    """STEP 5 - weights and scale constants for the derived UHI indices."""

    # Thermal mass weighting used for HeatVulnerabilityIndex (sums to 1.0).
    hvi_weights: Dict[str, float] = field(default_factory=lambda: {
        "impervious": 0.30,
        "low_green": 0.25,
        "building_density": 0.20,
        "road_exposure": 0.15,
        "low_ndvi": 0.10,
    })
    # Reference distance (m) used to convert proximity into a 0-1 score:
    # score = 1 / (1 + distance / ref_distance)
    proximity_ref_m: float = 500.0
    cooling_distance_weights: Dict[str, float] = field(default_factory=lambda: {
        "proximity": 0.5,
        "green_area": 0.5,
    })
    road_exposure_weights: Dict[str, float] = field(default_factory=lambda: {
        "density": 0.5,
        "proximity": 0.5,
    })
    ndvi_pct_lo: float = 2.0         # NDVI normalisation percentiles
    ndvi_pct_hi: float = 98.0


@dataclass
class QualityConfig:
    """STEP 6 - cleaning / quality thresholds and report settings."""

    max_missing_pct: float = 50.0    # drop columns missing more than this %
    fill_method: str = "median"      # median | mean
    correlation_threshold: float = 0.95   # (informational only)
    rf_n_estimators: int = 300
    rf_random_state: int = 42
    # Columns excluded from the baseline importance model (target / leakage).
    importance_exclude: List[str] = field(default_factory=lambda: [
        "Grid_ID", "Latitude", "Longitude", "Area_m2",
        "MeanLST", "MaxLST", "MinLST", "Target_LST",
        "LandCoverClass", "VegDensityClass", "Season", "Month",
    ])
    plot_dpi: int = 150


@dataclass
class Config:
    """Top-level configuration bundle."""

    paths: PathsConfig = field(default_factory=PathsConfig)
    grid: GridConfig = field(default_factory=GridConfig)
    landcover: LandcoverConfig = field(default_factory=LandcoverConfig)
    vector: VectorConfig = field(default_factory=VectorConfig)
    weather: WeatherConfig = field(default_factory=WeatherConfig)
    derived: DerivedConfig = field(default_factory=DerivedConfig)
    quality: QualityConfig = field(default_factory=QualityConfig)
    log_level: str = "INFO"
    n_jobs: int = max(1, (os.cpu_count() or 2) // 2)

    @classmethod
    def from_env(cls) -> "Config":
        cfg = cls()
        if os.environ.get("FE_GRID_SIZE"):
            cfg.grid.cell_size_m = float(os.environ["FE_GRID_SIZE"])
        if os.environ.get("FE_ACQUISITION_DATE"):
            cfg.acquisition_date = os.environ["FE_ACQUISITION_DATE"]
        return cfg
