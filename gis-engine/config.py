"""
Central configuration for the Sentinel-2 pipeline
=================================================
All paths, STAC endpoints, band lists, NDVI thresholds and pipeline behaviour
are defined here so the rest of the code stays parameter-free.

Usage:
    from config import Config
    cfg = Config.from_env()
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent


@dataclass
class PathsConfig:
    """Every directory the pipeline reads from or writes to."""

    root: Path = PROJECT_ROOT
    raw_sentinel: Path = PROJECT_ROOT / "data" / "raw" / "sentinel"
    raw_landsat: Path = PROJECT_ROOT / "data" / "raw" / "landsat"
    raw_dem: Path = PROJECT_ROOT / "data" / "raw" / "dem"
    raw_weather: Path = PROJECT_ROOT / "data" / "raw" / "weather"
    raw_aqi: Path = PROJECT_ROOT / "data" / "raw" / "aqi"
    clipped: Path = PROJECT_ROOT / "data" / "processed" / "clipped"
    weather_processed: Path = PROJECT_ROOT / "data" / "processed" / "weather"
    weather_stats: Path = PROJECT_ROOT / "data" / "statistics" / "weather"
    weather_plots: Path = PROJECT_ROOT / "data" / "plots" / "weather"
    aqi: Path = PROJECT_ROOT / "data" / "processed" / "aqi"
    aqi_rasters: Path = PROJECT_ROOT / "data" / "processed" / "aqi" / "rasters"
    aqi_statistics: Path = PROJECT_ROOT / "data" / "processed" / "aqi" / "statistics"
    aqi_plots: Path = PROJECT_ROOT / "data" / "processed" / "aqi" / "plots"
    ndvi: Path = PROJECT_ROOT / "data" / "processed" / "ndvi"
    greencover: Path = PROJECT_ROOT / "data" / "processed" / "greencover"
    vegetation: Path = PROJECT_ROOT / "data" / "processed" / "vegetation"
    landcover: Path = PROJECT_ROOT / "data" / "processed" / "landcover"
    lst: Path = PROJECT_ROOT / "data" / "processed" / "lst"
    heatmap: Path = PROJECT_ROOT / "data" / "processed" / "heatmap"
    dem: Path = PROJECT_ROOT / "data" / "processed" / "dem"
    elevation: Path = PROJECT_ROOT / "data" / "processed" / "elevation"
    slope: Path = PROJECT_ROOT / "data" / "processed" / "slope"
    aspect: Path = PROJECT_ROOT / "data" / "processed" / "aspect"
    hillshade: Path = PROJECT_ROOT / "data" / "processed" / "hillshade"
    contours: Path = PROJECT_ROOT / "data" / "processed" / "contours"
    previews: Path = PROJECT_ROOT / "data" / "processed" / "previews"
    stats: Path = PROJECT_ROOT / "data" / "processed" / "stats"
    logs: Path = PROJECT_ROOT / "logs"
    boundary: Path = PROJECT_ROOT / "boundary.geojson"

    def ensure(self) -> None:
        """Create all output directories (idempotent)."""
        dirs = [
            self.raw_sentinel, self.raw_landsat, self.raw_dem, self.raw_weather,
            self.clipped, self.ndvi, self.greencover, self.vegetation,
            self.landcover, self.lst, self.heatmap, self.dem, self.elevation,
            self.slope, self.aspect, self.hillshade, self.contours,
            self.weather_processed, self.weather_stats, self.weather_plots,
            self.raw_aqi, self.aqi, self.aqi_rasters, self.aqi_statistics,
            self.aqi_plots, self.previews, self.stats, self.logs,
        ]
        for d in dirs:
            d.mkdir(parents=True, exist_ok=True)


@dataclass
class Sentinel2Config:
    """Search + download settings for Sentinel-2 Level-2A."""

    # Bands required for NDVI and land cover (all native 10 m):
    #   B02 Blue, B03 Green, B04 Red, B08 NIR
    bands: List[str] = field(default_factory=lambda: ["B02", "B03", "B04", "B08"])

    # --- Microsoft Planetary Computer (preferred provider) ---
    collection: str = "sentinel-2-l2a"
    pc_stac_url: str = "https://planetarycomputer.microsoft.com/api/stac/v1"

    # --- Copernicus Data Space (fallback provider) ---
    cdse_stac_url: str = "https://catalogue.dataspace.copernicus.eu/stac"
    cdse_token_url: str = (
        "https://identity.dataspace.copernicus.eu/auth/realms/CDSE/"
        "protocol/openid-connect/token"
    )
    # Leave as None to use the public client ("cdse-public").
    cdse_client_id: Optional[str] = None
    cdse_client_secret: Optional[str] = None

    # --- Search criteria ---
    max_cloud_cover: float = 10.0          # percent
    lookback_days: int = 365               # search window: now - N days .. now
    max_items: int = 50

    # --- Raster handling ---
    resolution: int = 10                   # metres
    scale: float = 0.0001                  # S2 L2A stored as uint16 * scale
    offset: float = 0.0
    utm_epsg: Optional[int] = None         # auto-detected from boundary if None

    # --- Download robustness ---
    timeout_seconds: int = 120
    retries: int = 3
    chunk_size_bytes: int = 1 << 20        # 1 MiB


@dataclass
class ThresholdsConfig:
    """All configurable NDVI thresholds used to derive products."""

    # STEP 6 - Green Cover: vegetation where NDVI > threshold
    green_cover_ndvi: float = 0.30

    # STEP 7 - Vegetation Density: 5 classes from these 4 breakpoints
    #   Very Low < b1 <= Low < b2 <= Moderate < b3 <= High < b4 <= Very High
    veg_density_breaks: List[float] = field(
        default_factory=lambda: [0.10, 0.20, 0.40, 0.60]
    )
    veg_density_labels: List[str] = field(
        default_factory=lambda: ["Very Low", "Low", "Moderate", "High", "Very High"]
    )

    # STEP 8 - Land Cover (rule-based on NDVI; no SWIR band available):
    #   Water      : NDVI < water
    #   Built-up   : water <= NDVI < builtup
    #   Bare Land  : builtup <= NDVI < bare
    #   Vegetation : NDVI >= bare
    landcover_water_ndvi: float = 0.05
    landcover_builtup_ndvi: float = 0.15
    landcover_bare_ndvi: float = 0.30
    landcover_labels: List[str] = field(
        default_factory=lambda: ["Water", "Vegetation", "Built-up", "Bare Land"]
    )


@dataclass
class LandsatConfig:
    """Search + download settings for Landsat 8/9 Collection 2 Level-2."""

    # ST_B10 = USGS Level-2 surface temperature (already atmosphere + emissivity
    # corrected). QA_PIXEL lets us mask clouds/cloud shadows/fill at scene level.
    # `bands` are the official product names used for output files; `asset_keys`
    # maps them to provider asset keys (Planetary Computer uses lowercase names).
    bands: List[str] = field(default_factory=lambda: ["ST_B10", "QA_PIXEL"])
    thermal_band: str = "ST_B10"
    qa_band: str = "QA_PIXEL"
    asset_keys: Dict[str, str] = field(
        default_factory=lambda: {"ST_B10": "lwir11", "QA_PIXEL": "qa_pixel"}
    )
    mtl_assets: List[str] = field(default_factory=lambda: ["mtl.json", "mtl.txt"])

    # --- Providers ---
    collection: str = "landsat-c2-l2"
    pc_stac_url: str = "https://planetarycomputer.microsoft.com/api/stac/v1"
    usgs_stac_url: str = "https://landsatlook.usgs.gov/stac-server"

    # --- Search criteria ---
    max_cloud_cover: float = 10.0          # percent, whole scene
    lookback_days: int = 730               # Landsat revisit is 16 days; widen window
    max_items: int = 50

    # --- Official USGS Collection-2 Level-2 scaling for ST_B10 (Kelvin) ---
    # ST_K = DN * scale_mul + scale_add   (overridden by the MTL when available)
    scale_mul: float = 0.00341802
    scale_add: float = 149.0
    kelvin_to_celsius: float = -273.15

    # --- Raster handling ---
    resolution: int = 30
    utm_epsg: Optional[int] = None         # auto-detected from boundary if None
    mask_clouds: bool = True               # use QA_PIXEL bits 0-4 (fill/cloud/etc.)

    # --- Download robustness ---
    timeout_seconds: int = 120
    retries: int = 3
    chunk_size_bytes: int = 1 << 20        # 1 MiB


# Indian AQI (CPCB) sub-index breakpoints: (lower, upper, aqi_low, aqi_high)
# CO is in mg/m3; all other pollutants in ug/m3.
AQI_BREAKPOINTS = {
    "PM2.5": [(0, 30, 0, 50), (31, 60, 51, 100), (61, 90, 101, 200),
               (91, 120, 201, 300), (121, 250, 301, 400), (251, None, 401, 500)],
    "PM10": [(0, 50, 0, 50), (51, 100, 51, 100), (101, 250, 101, 200),
              (251, 350, 201, 300), (351, 430, 301, 400), (431, None, 401, 500)],
    "NO2": [(0, 40, 0, 50), (41, 80, 51, 100), (81, 180, 101, 200),
             (181, 280, 201, 300), (281, 400, 301, 400), (401, None, 401, 500)],
    "SO2": [(0, 40, 0, 50), (41, 80, 51, 100), (81, 380, 101, 200),
             (381, 800, 201, 300), (801, 1600, 301, 400), (1601, None, 401, 500)],
    "CO": [(0, 1.0, 0, 50), (1.1, 2.0, 51, 100), (2.1, 10.0, 101, 200),
            (10.1, 17.0, 201, 300), (17.1, 34.0, 301, 400), (34.1, None, 401, 500)],
    "O3": [(0, 50, 0, 50), (51, 100, 51, 100), (101, 168, 101, 200),
            (169, 208, 201, 300), (209, 748, 301, 400), (749, None, 401, 500)],
}

AQI_CATEGORIES = [
    ("Good", 0), ("Satisfactory", 51), ("Moderate", 101),
    ("Poor", 201), ("Very Poor", 301), ("Severe", 401),
]


@dataclass
class AQIConfig:
    """Air quality settings: provider chain, interpolation and AQI rules."""

    pollutants: List[str] = field(default_factory=lambda: ["PM2.5", "PM10", "NO2", "SO2", "CO", "O3"])

    # Provider chain tried in order when provider="auto":
    #   sentinel-5p -> openaq -> cpcb -> demo
    provider: str = "auto"      # auto | sentinel-5p | openaq | cpcb | demo
    demo_fallback: bool = True  # allow the clearly-labelled synthetic demo source

    # 1) Sentinel-5P via Copernicus Data Space (OData) - needs client credentials
    cdse_odata_url: str = "https://catalogue.dataspace.copernicus.eu/odata/v1"
    cdse_zipper_url: str = "https://zipper.dataspace.copernicus.eu/odata/v1"
    cdse_client_id_env: str = "CDSE_CLIENT_ID"
    cdse_client_secret_env: str = "CDSE_CLIENT_SECRET"
    s5p_gases: List[str] = field(default_factory=lambda: ["NO2", "SO2", "CO", "O3"])
    s5p_search_days: int = 21        # most recent granule within this window
    s5p_blh_m: float = 1000.0        # assumed boundary-layer height for column->surface

    # 2) OpenAQ v3 - needs a free API key
    openaq_base_url: str = "https://api.openaq.org/v3"
    openaq_api_key_env: str = "OPENAQ_API_KEY"
    openaq_radius_km: float = 60.0
    openaq_lookback_days: int = 30

    # 3) CPCB Open Data (best effort)
    cpcb_url: str = "https://airquality.cpcb.gov.in/ccr-data/pub/station_wise_latest_aqi.php"

    # Spatial interpolation
    grid_resolution_m: int = 1000    # interpolation grid cell size
    interp_method: str = "auto"      # auto | pykrige | idw
    min_points_idw: int = 2
    min_points_krige: int = 5        # kriging below this falls back to IDW
    variogram_model: str = "spherical"

    # Robustness
    timeout_seconds: int = 120
    retries: int = 3
    chunk_size_bytes: int = 1 << 20


@dataclass
class WeatherConfig:
    """NASA POWER weather settings."""

    base_url: str = "https://power.larc.nasa.gov/api/temporal/daily/point"
    community: str = "RE"   # Renewable Energy community (all params available)

    # Daily parameters (2 m height unless noted)
    parameters: List[str] = field(default_factory=lambda: [
        "T2M",                # air temperature at 2 m            [degC]
        "RH2M",               # relative humidity at 2 m          [%]
        "WS2M",               # wind speed at 2 m                 [m/s]
        "PS",                 # surface pressure                  [kPa]
        "ALLSKY_SFC_SW_DWN",  # all-sky surface shortwave flux     [kWh/m2/day]
        "PRECTOTCORR",        # corrected precipitation           [mm/day]
    ])

    # Unit conversions applied after download (factor per parameter)
    #   PS: kPa -> hPa (meteorological standard)      x10
    #   ALLSKY_SFC_SW_DWN: kWh/m2/day -> W/m2 mean    x1000/24
    unit_conversions: Dict[str, float] = field(default_factory=lambda: {
        "PS": 10.0,
        "ALLSKY_SFC_SW_DWN": 1000.0 / 24.0,
    })

    years_back: int = 5        # download the last N years of daily data
    missing_flag: float = -999.0

    # Robustness
    timeout_seconds: int = 120
    retries: int = 4
    user_agent: str = "urban-digital-twin/1.0 (contact: local)"


@dataclass
class DEMConfig:
    """DEM download + terrain processing settings."""

    # Preferred provider: Copernicus DEM GLO-30 from the public AWS Open Data
    # bucket (no auth). Tiles are 1x1 degree, ~30 m, EPSG:4326.
    provider: str = "copernicus"          # "copernicus" | "srtm"
    copernicus_base_url: str = "https://copernicus-dem-30m.s3.amazonaws.com"
    tile_size_deg: float = 1.0

    # Fallback: NASA SRTM 30 m (SRTMGL1) via OpenTopography (requires a free
    # API key - set the environment variable below).
    opentopography_url: str = "https://portal.opentopography.org/API/globaldem"
    srtm_dem_type: str = "SRTMGL1"
    api_key_env: str = "OPENTOPOGRAPHY_API_KEY"

    # Terrain derivatives
    contour_interval_m: float = 5.0
    hillshade_azimuth: float = 315.0
    hillshade_altitude: float = 45.0
    # "numpy" -> Horn (1981) 3x3 finite differences (always works)
    # "richdem" -> use RichDEM if importable (no Python 3.14 wheel currently)
    engine: str = "numpy"

    # Download robustness
    timeout_seconds: int = 300
    retries: int = 3
    chunk_size_bytes: int = 1 << 20      # 1 MiB


@dataclass
class HeatClassConfig:
    """STEP 7 - Heat classification into 6 classes (Very Cool .. Very Hot)."""

    # "quantile" -> class breaks at scene percentiles (scene-adaptive, default)
    # "fixed"    -> absolute temperature breaks in degrees Celsius
    method: str = "quantile"
    quantile_breaks: List[float] = field(
        default_factory=lambda: [15.0, 35.0, 55.0, 75.0, 90.0]  # percentiles
    )
    fixed_breaks_c: List[float] = field(
        default_factory=lambda: [20.0, 25.0, 30.0, 35.0, 40.0]  # degrees Celsius
    )
    labels: List[str] = field(
        default_factory=lambda: ["Very Cool", "Cool", "Moderate", "Warm", "Hot", "Very Hot"]
    )


@dataclass
class PipelineConfig:
    """Pipeline behaviour flags."""

    skip_existing: bool = True     # do not redo work that already produced files
    force: bool = False            # --force: recompute / re-download everything
    log_level: str = "INFO"
    preview_dpi: int = 150
    ndvi_vmin: float = -0.5
    ndvi_vmax: float = 1.0


@dataclass
class Config:
    """Top-level configuration bundle."""

    paths: PathsConfig = field(default_factory=PathsConfig)
    sentinel: Sentinel2Config = field(default_factory=Sentinel2Config)
    landsat: LandsatConfig = field(default_factory=LandsatConfig)
    dem: DEMConfig = field(default_factory=DEMConfig)
    weather: WeatherConfig = field(default_factory=WeatherConfig)
    aqi: AQIConfig = field(default_factory=AQIConfig)
    heat: HeatClassConfig = field(default_factory=HeatClassConfig)
    thresholds: ThresholdsConfig = field(default_factory=ThresholdsConfig)
    pipeline: PipelineConfig = field(default_factory=PipelineConfig)

    @classmethod
    def from_env(cls) -> "Config":
        """Build a config, honouring a small set of environment overrides."""
        cfg = cls()
        cfg.sentinel.max_cloud_cover = float(
            os.environ.get("MAX_CLOUD_COVER", cfg.sentinel.max_cloud_cover)
        )
        cfg.sentinel.lookback_days = int(
            os.environ.get("S2_LOOKBACK_DAYS", cfg.sentinel.lookback_days)
        )
        cfg.sentinel.cdse_client_id = os.environ.get("CDSE_CLIENT_ID")
        cfg.sentinel.cdse_client_secret = os.environ.get("CDSE_CLIENT_SECRET")
        return cfg
