"""
STEP 1-3 - Air quality observations download
============================================
Builds a unified point-observation table for PM2.5, PM10, NO2, SO2, CO and O3
from a provider chain (tried in order):

  1. Sentinel-5P (Copernicus)  - gases NO2/SO2/CO/O3 as satellite retrievals,
                                 requires CDSE client credentials (free at
                                 https://dataspace.copernicus.eu)
  2. OpenAQ v3                 - all six pollutants from ground monitors,
                                 requires a free API key (https://openaq.org)
  3. CPCB Open Data            - best-effort Indian ground monitor scrape
  4. demo (fallback)           - clearly-labelled synthetic observations so the
                                 interpolation/AQI chain can run without keys

Output: data/raw/aqi/aqi_observations.csv + aqi_metadata.json
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd
import geopandas as gpd
import requests

from config import Config
from download_weather import centroid_of
from utils import PipelineError, load_boundary, read_json, resumable_download, write_json

logger = logging.getLogger("sentinel.aqi.download")

POLLUTANT_COLS = ["PM2.5", "PM10", "NO2", "SO2", "CO", "O3"]

# OpenAQ parameter names -> our pollutant columns
OPENAQ_PARAM_MAP = {
    "pm25": "PM2.5", "pm2.5": "PM2.5", "pm10": "PM10", "no2": "NO2",
    "so2": "SO2", "co": "CO", "o3": "O3",
}

# S5P netCDF variable keywords -> (column, molar mass g/mol)
S5P_VARIABLES = {
    "NO2": ("tropospheric_NO2_column_number_density", 46.0055),
    "SO2": ("SO2_column_number_density", 64.066),
    "CO": ("carbonmonoxide_total_column", 28.01),
    "O3": ("ozone_total_vertical_column", 47.998),
}


@dataclass
class AqiResult:
    """Locator for the downloaded observations."""

    points_csv: Path
    sources: List[str] = field(default_factory=list)
    n_observations: int = 0
    metadata_path: Optional[Path] = None


def _empty_points() -> pd.DataFrame:
    return pd.DataFrame(columns=["station_id", "lat", "lon", "datetime"] + POLLUTANT_COLS + ["source"])


# ---------------------------------------------------------------------------
# 1) Sentinel-5P via Copernicus Data Space OData
# ---------------------------------------------------------------------------
def _cdse_credentials(cfg: Config) -> Optional[tuple]:
    cid = os.environ.get(cfg.aqi.cdse_client_id_env)
    secret = os.environ.get(cfg.aqi.cdse_client_secret_env)
    if not cid or not secret:
        logger.info("CDSE credentials not set (%s/%s) - Sentinel-5P source unavailable",
                    cfg.aqi.cdse_client_id_env, cfg.aqi.cdse_client_secret_env)
        return None
    return cid, secret


def _cdse_token(cfg: Config, cid: str, secret: str) -> str:
    from urllib.parse import urlencode

    payload = urlencode({"grant_type": "client_credentials",
                         "client_id": cid, "client_secret": secret}).encode("utf-8")
    resp = requests.post(
        "https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token",
        data=payload, timeout=cfg.aqi.timeout_seconds,
    )
    resp.raise_for_status()
    token = resp.json().get("access_token")
    if not token:
        raise PipelineError("CDSE did not return an access token")
    return token


def _s5p_product_search(cfg: Config, token: str, bbox: tuple, top: int = 40) -> list:
    minx, miny, maxx, maxy = bbox
    polygon = (f"geography'SRID=4326;POLYGON(({minx} {miny},{maxx} {miny},"
               f"{maxx} {maxy},{minx} {maxy},{minx} {miny}))'")
    url = (f"{cfg.aqi.cdse_odata_url}/Products?$filter=Collection/Name eq 'SENTINEL-5P' "
           f"and OData.CSC.Intersects(area={polygon})&$orderby=ContentDate/Start desc&$top={top}")
    resp = requests.get(url, headers={"Authorization": f"Bearer {token}"},
                        timeout=cfg.aqi.timeout_seconds)
    resp.raise_for_status()
    return resp.json().get("value", [])


def _s5p_granule_to_points(cfg: Config, gas: str, product: dict, token: str) -> pd.DataFrame:
    """Download one S5P granule and extract bbox pixels as concentration points."""
    import xarray as xr

    product_id = product["Id"]
    date_str = product["ContentDate"]["Start"][:10]
    nc_path = cfg.paths.raw_aqi / f"s5p_{gas}_{date_str}.nc"
    if not (nc_path.exists() and cfg.pipeline.skip_existing and not cfg.pipeline.force):
        url = f"{cfg.aqi.cdse_zipper_url}/Products({product_id})/$value"
        resumable_download(url, nc_path, headers={"Authorization": f"Bearer {token}"},
                           chunk_size=cfg.aqi.chunk_size_bytes,
                           retries=cfg.aqi.retries,
                           timeout=cfg.aqi.timeout_seconds, logger=logger)

    keyword, molar_mass = S5P_VARIABLES[gas]
    ds = xr.open_dataset(nc_path, engine="h5netcdf")
    try:
        var_name = next(v for v in ds.data_vars if keyword in v)
        qa_name = next((v for v in ds.data_vars if "qa_value" in v), None)
        lat = ds["/PRODUCT/latitude"].values
        lon = ds["/PRODUCT/longitude"].values
        values = ds[var_name].values.astype(np.float64)
        if qa_name:
            values = np.where(ds[qa_name].values >= 50, values, np.nan)

        mask = (
            (lon >= 85.7) & (lon <= 86.0) & (lat >= 20.0) & (lat <= 20.5)
            & np.isfinite(values) & (values > 0)
        )
        # Column density (mol/m2) -> approx surface concentration (ug/m3)
        #   mol/m2 / BLH(m) = mol/m3 ; x M (g/mol) x 1e6 = ug/m3
        conc = values[mask] / cfg.aqi.s5p_blh_m * molar_mass * 1e6
        rows = pd.DataFrame({
            "station_id": [f"s5p-{gas}-{i}" for i in range(int(mask.sum()))],
            "lat": lat[mask], "lon": lon[mask],
            "datetime": pd.Timestamp(date_str).isoformat(),
            gas: conc,
        })
        rows["source"] = "sentinel-5p"
        for col in POLLUTANT_COLS:
            rows.setdefault(col, np.nan)
        logger.info("Sentinel-5P %s: %d bbox pixel observation(s)", gas, len(rows))
        return rows[["station_id", "lat", "lon", "datetime"] + POLLUTANT_COLS + ["source"]]
    finally:
        ds.close()


def fetch_sentinel5p(cfg: Config, bbox: tuple) -> pd.DataFrame:
    creds = _cdse_credentials(cfg)
    if not creds:
        return _empty_points()
    frames = []
    try:
        token = _cdse_token(cfg, *creds)
        products = _s5p_product_search(cfg, token, bbox)
        for gas in cfg.aqi.s5p_gases:
            marker = f"_{gas}____"
            product = next((p for p in products if marker in p.get("Name", "")), None)
            if product is None:
                logger.warning("No recent Sentinel-5P %s granule over the study area", gas)
                continue
            try:
                frames.append(_s5p_granule_to_points(cfg, gas, product, token))
            except Exception as e:
                logger.warning("Sentinel-5P %s processing failed: %s", gas, e)
    except Exception as e:
        logger.warning("Sentinel-5P source failed: %s", e)
    return pd.concat(frames, ignore_index=True) if frames else _empty_points()


# ---------------------------------------------------------------------------
# 2) OpenAQ v3
# ---------------------------------------------------------------------------
def fetch_openaq(cfg: Config, lat: float, lon: float) -> pd.DataFrame:
    key = os.environ.get(cfg.aqi.openaq_api_key_env)
    if not key:
        logger.info("OPENAQ_API_KEY not set - OpenAQ source unavailable (free key at openaq.org)")
        return _empty_points()
    since = (datetime.now(timezone.utc) - timedelta(days=cfg.aqi.openaq_lookback_days)).isoformat()
    url = (f"{cfg.aqi.openaq_base_url}/measurements"
           f"?coordinates={lat},{lon}&radius={int(cfg.aqi.openaq_radius_km * 1000)}"
           f"&limit=1000&datetime={since}")
    try:
        resp = requests.get(url, headers={"X-API-Key": key},
                            timeout=cfg.aqi.timeout_seconds)
        resp.raise_for_status()
        results = resp.json().get("results", [])
    except Exception as e:
        logger.warning("OpenAQ request failed: %s", e)
        return _empty_points()

    rows = []
    for r in results:
        param = (r.get("parameter") or {}).get("name", "").lower()
        pollutant = OPENAQ_PARAM_MAP.get(param)
        if pollutant is None or r.get("value") is None:
            continue
        coords = r.get("coordinates") or {}
        lat_r, lon_r = coords.get("latitude"), coords.get("longitude")
        if lat_r is None or lon_r is None:
            continue
        when = ((r.get("datetime") or {}).get("utc") or r.get("datetime"))
        rows.append({
            "station_id": r.get("locationId") or r.get("location"),
            "lat": float(lat_r), "lon": float(lon_r),
            "datetime": when, pollutant: float(r["value"]), "source": "openaq",
        })
    if not rows:
        logger.warning("OpenAQ returned no matching measurements near the study area")
        return _empty_points()
    df = pd.DataFrame(rows)
    for col in POLLUTANT_COLS:
        df.setdefault(col, np.nan)
    logger.info("OpenAQ: %d measurement row(s) for %d pollutant(s)",
                len(df), df[POLLUTANT_COLS].notna().sum().gt(0).sum())
    return df[["station_id", "lat", "lon", "datetime"] + POLLUTANT_COLS + ["source"]]


# ---------------------------------------------------------------------------
# 3) CPCB Open Data (best effort)
# ---------------------------------------------------------------------------
def fetch_cpcb(cfg: Config, lat: float, lon: float) -> pd.DataFrame:
    try:
        resp = requests.get(cfg.aqi.cpcb_url, timeout=cfg.aqi.timeout_seconds)
        resp.raise_for_status()
        payload = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else None
    except Exception as e:
        logger.warning("CPCB source unavailable (%s) - endpoint is often unreachable", e)
        return _empty_points()
    if not payload:
        logger.warning("CPCB returned no parseable data")
        return _empty_points()
    logger.warning("CPCB endpoint responded but its schema is undocumented - treating as unavailable")
    return _empty_points()


# ---------------------------------------------------------------------------
# 4) Demo (synthetic, clearly labelled)
# ---------------------------------------------------------------------------
def fetch_demo(cfg: Config, lat: float, lon: float) -> pd.DataFrame:
    logger.warning("No real AQ source configured - generating DEMO (synthetic) observations. "
                   "Set OPENAQ_API_KEY or CDSE_CLIENT_ID/SECRET for real data.")
    rng = np.random.default_rng(42)
    n = 10
    angles = np.linspace(0, 2 * np.pi, n, endpoint=False)
    radii = rng.uniform(2, 22, n)  # km from city centre
    km_lat = radii * np.cos(angles)
    km_lon = radii * np.sin(angles)
    lat_pts = lat + km_lat / 110.574
    lon_pts = lon + km_lon / (111.320 * np.cos(np.radians(lat)))
    dist = radii

    df = pd.DataFrame({
        "station_id": [f"demo-{i:02d}" for i in range(n)],
        "lat": lat_pts, "lon": lon_pts,
        "datetime": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "PM2.5": np.clip(58 - 0.9 * dist + rng.normal(0, 6, n), 5, None),
        "PM10": np.clip(120 - 1.8 * dist + rng.normal(0, 12, n), 10, None),
        "NO2": np.clip(42 - 0.7 * dist + rng.normal(0, 5, n), 1, None),
        "SO2": np.clip(18 - 0.3 * dist + rng.normal(0, 3, n), 0.5, None),
        "CO": np.clip(950 - 15 * dist + rng.normal(0, 90, n), 50, None),
        "O3": np.clip(42 + 0.3 * dist + rng.normal(0, 6, n), 5, None),
        "source": "demo-synthetic",
    })
    logger.info("Demo: generated %d synthetic observation points", len(df))
    return df[["station_id", "lat", "lon", "datetime"] + POLLUTANT_COLS + ["source"]]


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------
def download_aqi(cfg: Config, boundary: Optional[gpd.GeoDataFrame] = None) -> AqiResult:
    """STEP 1-3: read boundary, run the provider chain, save observations."""
    boundary = boundary if boundary is not None else load_boundary(cfg.paths.boundary)
    lat, lon = centroid_of(boundary)
    bbox = tuple(boundary.total_bounds)

    csv_path = cfg.paths.raw_aqi / "aqi_observations.csv"
    meta_path = cfg.paths.raw_aqi / "aqi_metadata.json"

    if csv_path.exists() and cfg.pipeline.skip_existing and not cfg.pipeline.force:
        meta = read_json(meta_path)
        logger.info("AQI observations already downloaded - reusing (use --force to refresh)")
        return AqiResult(points_csv=csv_path, sources=meta.get("sources", []),
                         n_observations=len(pd.read_csv(csv_path)), metadata_path=meta_path)

    providers = {
        "sentinel-5p": lambda: fetch_sentinel5p(cfg, bbox),
        "openaq": lambda: fetch_openaq(cfg, lat, lon),
        "cpcb": lambda: fetch_cpcb(cfg, lat, lon),
        "demo": lambda: fetch_demo(cfg, lat, lon),
    }

    if cfg.aqi.provider == "auto":
        order = ["sentinel-5p", "openaq", "cpcb", "demo"]
    else:
        order = [cfg.aqi.provider]

    frames, used = [], []
    for name in order:
        if name == "demo" and not cfg.aqi.demo_fallback:
            continue
        df = providers[name]()
        if not df.empty:
            frames.append(df)
            used.append(name)

    if not frames:
        raise PipelineError("No air quality observations available from any configured source")

    points = pd.concat(frames, ignore_index=True)
    # De-duplicate by rounded location (keep the first source)
    points["_key"] = points[["lat", "lon"]].round(4).astype(str).agg("_".join, axis=1)
    points = points.drop_duplicates(subset="_key", keep="first").drop(columns="_key")
    points = points.reset_index(drop=True)

    points.to_csv(csv_path, index=False)
    write_json(meta_path, {
        "sources": used,
        "centroid": {"lat": lat, "lon": lon},
        "n_observations": len(points),
        "per_pollutant_points": {
            p: int(points[p].notna().sum()) for p in POLLUTANT_COLS
        },
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    logger.info("AQI observations saved -> %s (%d rows, sources: %s)",
                csv_path, len(points), used)
    return AqiResult(points_csv=csv_path, sources=used,
                     n_observations=len(points), metadata_path=meta_path)


if __name__ == "__main__":  # pragma: no cover
    from utils import setup_logging

    cfg = Config.from_env()
    cfg.paths.ensure()
    setup_logging(cfg)
    result = download_aqi(cfg)
    print(f"\nSources: {result.sources}")
    print(f"Observations: {result.n_observations}")
    print(f"CSV: {result.points_csv}")
