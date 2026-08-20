"""
STEP 1-3 - NASA POWER daily weather download
============================================
Reads boundary.geojson, computes the study-area centroid and downloads the
last 5 years of daily weather observations from the NASA POWER API
(T2M, RH2M, WS2M, PS, ALLSKY_SFC_SW_DWN, PRECTOTCORR).

The raw JSON response is stored atomically in ``data/raw/weather/``; re-runs
reuse an existing, complete download (use ``--force`` to refresh).
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import geopandas as gpd
import requests

from config import Config
from utils import PipelineError, load_boundary, read_json, write_json

logger = logging.getLogger("sentinel.weather.download")


@dataclass
class WeatherResult:
    """Locator + metadata for the downloaded POWER JSON."""

    json_path: Path
    centroid_lat: float
    centroid_lon: float
    start_date: str
    end_date: str
    parameters: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "json_path": str(self.json_path),
            "centroid_lat": self.centroid_lat,
            "centroid_lon": self.centroid_lon,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "parameters": self.parameters,
        }


# ---------------------------------------------------------------------------
# STEP 1-2 - boundary + centroid
# ---------------------------------------------------------------------------
def centroid_of(boundary: gpd.GeoDataFrame) -> Tuple[float, float]:
    """Centroid (lat, lon) of the study area; representative point if the
    centroid falls outside a concave geometry."""
    geom = boundary.geometry.union_all()
    pt = geom.centroid if geom.centroid.within(geom) else geom.representative_point()
    return float(pt.y), float(pt.x)


def power_date_range(cfg: Config) -> Tuple[date, date]:
    """Last N years of daily data ending today."""
    end = date.today()
    start = end.replace(year=end.year - cfg.weather.years_back)
    if start.day == 29 and start.month == 2:  # leap-day edge case
        start = start.replace(day=28)
    return start, end


# ---------------------------------------------------------------------------
# STEP 3 - download
# ---------------------------------------------------------------------------
def download_daily_power(
    cfg: Config, lat: float, lon: float, start: date, end: date
) -> Path:
    """Query the NASA POWER daily point API and save the JSON atomically."""
    out = cfg.paths.raw_weather / f"power_daily_{start:%Y%m%d}_{end:%Y%m%d}.json"
    if out.exists() and cfg.pipeline.skip_existing and not cfg.pipeline.force:
        logger.info("Weather JSON already downloaded - reusing %s", out.name)
        return out

    params = {
        "parameters": ",".join(cfg.weather.parameters),
        "community": cfg.weather.community,
        "longitude": lon,
        "latitude": lat,
        "start": start.strftime("%Y%m%d"),
        "end": end.strftime("%Y%m%d"),
        "format": "JSON",
    }
    headers = {"User-Agent": cfg.weather.user_agent}
    logger.info("Querying NASA POWER: %s (lat %.4f, lon %.4f, %s..%s)",
                cfg.weather.base_url, lat, lon, start, end)

    tmp = Path(str(out) + ".part")
    for attempt in range(cfg.weather.retries + 1):
        try:
            resp = requests.get(cfg.weather.base_url, params=params, headers=headers,
                                timeout=cfg.weather.timeout_seconds)
            if resp.status_code == 429:
                raise PipelineError("NASA POWER rate limited (HTTP 429)")
            resp.raise_for_status()
            data = resp.json()
            if "properties" not in data or "parameter" not in data["properties"]:
                raise PipelineError(f"Unexpected NASA POWER response: {str(data)[:300]}")
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(data, fh)
            os.replace(tmp, out)
            logger.info("Weather JSON saved -> %s", out)
            return out
        except (requests.RequestException, PipelineError, ValueError) as e:
            if attempt < cfg.weather.retries:
                wait = min(2 ** attempt * 5, 60)
                logger.warning("POWER request failed (attempt %d/%d): %s - retrying in %ds",
                               attempt + 1, cfg.weather.retries + 1, e, wait)
                time.sleep(wait)
            else:
                raise PipelineError(f"NASA POWER download failed: {e}") from e
    raise PipelineError("NASA POWER download failed")  # pragma: no cover


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------
def download_weather(cfg: Config, boundary: Optional[gpd.GeoDataFrame] = None) -> WeatherResult:
    """STEP 1-3: boundary -> centroid -> download last 5 years of daily weather."""
    boundary = boundary if boundary is not None else load_boundary(cfg.paths.boundary)
    lat, lon = centroid_of(boundary)
    start, end = power_date_range(cfg)

    json_path = download_daily_power(cfg, lat, lon, start, end)
    result = WeatherResult(
        json_path=json_path,
        centroid_lat=lat,
        centroid_lon=lon,
        start_date=start.strftime("%Y-%m-%d"),
        end_date=end.strftime("%Y-%m-%d"),
        parameters=list(cfg.weather.parameters),
    )
    write_json(cfg.paths.raw_weather / "weather_metadata.json", result.to_dict())
    logger.info("Weather download complete: %s (%.4f N, %.4f E)", json_path.name, lat, lon)
    return result


if __name__ == "__main__":  # pragma: no cover
    from utils import setup_logging

    cfg = Config.from_env()
    cfg.paths.ensure()
    setup_logging(cfg)
    result = download_weather(cfg)
    print(f"\nCentroid: {result.centroid_lat:.4f}, {result.centroid_lon:.4f}")
    print(f"Period: {result.start_date} .. {result.end_date}")
    print(f"JSON: {result.json_path}")
