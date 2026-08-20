#!/usr/bin/env python3
"""
Download Historical Weather Data
=================================
Fetches historical weather from Open-Meteo Archive API for dates matching
Landsat satellite acquisitions over Bhubaneswar.

Source: Open-Meteo Historical Weather API (https://open-meteo.com)
- Free, no API key required
- ERA5 reanalysis-backed global historical weather
- Daily resolution matching Landsat acquisition dates
- Covers 1940-present

For each Landsat acquisition date, collects:
    - air_temperature_max (°C)
    - air_temperature_min (°C)
    - air_temperature_mean (°C)
    - relative_humidity (%)
    - wind_speed_10m (m/s)
    - surface_pressure (hPa)
    - precipitation_sum (mm)
    - cloud_cover (%)
    - shortwave_radiation (W/m²)

The weather timestamp corresponds to the Landsat acquisition date.
Temporal matching: same calendar day as satellite overpass.

Outputs:
    data/historical_lst/weather/{date}.json    - daily weather per scene
    data/historical_lst/weather/manifest.json  - download manifest

Usage:
    python scripts/download_historical_weather.py
    python scripts/download_historical_weather.py --lat 20.2961 --lon 85.8245
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional
from urllib.error import HTTPError
from urllib.request import Request, urlopen

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("download_historical_weather")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
HISTORICAL_DIR = PROJECT_ROOT / "data" / "historical_lst"
CATALOGUE_PATH = HISTORICAL_DIR / "catalogue.json"
WEATHER_DIR = HISTORICAL_DIR / "weather"
MANIFEST_PATH = WEATHER_DIR / "manifest.json"

# Open-Meteo Historical Weather API
OPEN_METEO_BASE = "https://archive-api.open-meteo.com/v1/archive"

# Bhubaneswar centroid (Khandagiri/ITER area)
DEFAULT_LAT = 20.2961
DEFAULT_LON = 85.8245

# Open-Meteo daily parameters
DAILY_PARAMS = [
    "temperature_2m_max",
    "temperature_2m_min",
    "temperature_2m_mean",
    "relative_humidity_2m_mean",
    "wind_speed_10m_max",
    "surface_pressure_mean",
    "precipitation_sum",
    "cloud_cover_mean",
    "shortwave_radiation_sum",
]

# Model feature names for mapping
WEATHER_FEATURE_MAP = {
    "temperature_2m_max": "Temperature_Max",
    "temperature_2m_min": "Temperature_Min",
    "temperature_2m_mean": "Temperature_Mean",
    "relative_humidity_2m_mean": "Humidity",
    "wind_speed_10m_max": "WindSpeed",
    "surface_pressure_mean": "Pressure",
    "precipitation_sum": "Precipitation",
    "cloud_cover_mean": "CloudCover",
    "shortwave_radiation_sum": "SolarRadiation",
}


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Download historical weather for Landsat dates")
    p.add_argument("--lat", type=float, default=DEFAULT_LAT, help="Latitude")
    p.add_argument("--lon", type=float, default=DEFAULT_LON, help="Longitude")
    p.add_argument("--force", action="store_true", help="Re-download existing files")
    return p.parse_args()


def fetch_open_meteo(
    lat: float, lon: float, start_date: str, end_date: str
) -> dict:
    """Fetch daily weather from Open-Meteo Archive API."""
    params = {
        "latitude": lat,
        "longitude": lon,
        "start_date": start_date,
        "end_date": end_date,
        "daily": ",".join(DAILY_PARAMS),
        "timezone": "Asia/Kolkata",
    }

    # Build URL
    param_str = "&".join(f"{k}={v}" for k, v in params.items())
    url = f"{OPEN_METEO_BASE}?{param_str}"

    log.info("Fetching Open-Meteo: %s to %s", start_date, end_date)

    req = Request(url, headers={"User-Agent": "urban-digital-twin/1.0"})
    try:
        with urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except HTTPError as exc:
        log.error("Open-Meteo HTTP error %s: %s", exc.code, exc.read().decode())
        raise
    except Exception as exc:
        log.error("Open-Meteo request failed: %s", exc)
        raise

    return data


def process_weather_data(raw_data: dict) -> Dict[str, dict]:
    """Process raw Open-Meteo response into per-date weather records."""
    daily = raw_data.get("daily", {})
    dates = daily.get("time", [])

    if not dates:
        log.warning("No weather dates returned")
        return {}

    weather_by_date = {}
    for i, date_str in enumerate(dates):
        record = {"date": date_str}
        for param in DAILY_PARAMS:
            values = daily.get(param, [])
            value = values[i] if i < len(values) else None
            feature_name = WEATHER_FEATURE_MAP.get(param, param)
            record[feature_name] = value

        # Convert shortwave_radiation_sum from MJ/m²/day to W/m² (mean)
        # Open-Meteo returns MJ/m²/day; divide by 86400 to get W/m² mean
        if record.get("SolarRadiation") is not None:
            record["SolarRadiation"] = round(record["SolarRadiation"] * 1000000 / 86400, 2)

        weather_by_date[date_str] = record

    return weather_by_date


def load_catalogue() -> dict:
    """Load the historical LST catalogue to get scene dates."""
    if not CATALOGUE_PATH.exists():
        log.error("Catalogue not found: %s", CATALOGUE_PATH)
        log.error("Run download_historical_lst.py first")
        return {}

    with open(CATALOGUE_PATH, encoding="utf-8") as fh:
        return json.load(fh)


def main() -> int:
    args = parse_args()
    t_start = time.time()

    log.info("=" * 72)
    log.info("HISTORICAL WEATHER DOWNLOAD")
    log.info("Location: lat=%.4f, lon=%.4f", args.lat, args.lon)
    log.info("=" * 72)

    # Load catalogue to get scene dates
    catalogue = load_catalogue()
    if not catalogue:
        return 1

    observations = catalogue.get("observations", [])
    if not observations:
        log.error("No observations in catalogue")
        return 1

    # Get all dates
    all_dates = [obs["date"] for obs in observations]
    log.info("Catalogue has %d scene dates: %s to %s",
             len(all_dates), all_dates[0], all_dates[-1])

    # Filter to dates without weather data (unless --force)
    dates_to_fetch = []
    WEATHER_DIR.mkdir(parents=True, exist_ok=True)

    for date_str in all_dates:
        weather_path = WEATHER_DIR / f"{date_str}.json"
        if weather_path.exists() and not args.force:
            log.debug("Weather for %s already exists - skipping", date_str)
            continue
        dates_to_fetch.append(date_str)

    if not dates_to_fetch:
        log.info("All weather data already downloaded")
        return 0

    log.info("Need to download weather for %d dates", len(dates_to_fetch))

    # Fetch weather in batches (Open-Meteo supports date ranges)
    # Group consecutive dates to minimize API calls
    all_weather = {}

    # Sort dates
    dates_to_fetch.sort()

    # Fetch in yearly batches for efficiency
    years = sorted(set(d[:4] for d in dates_to_fetch))
    for year in years:
        year_dates = [d for d in dates_to_fetch if d.startswith(year)]
        if not year_dates:
            continue

        start = year_dates[0]
        end = year_dates[-1]

        log.info("Fetching weather for year %s: %s to %s", year, start, end)

        try:
            raw_data = fetch_open_meteo(args.lat, args.lon, start, end)
            weather = process_weather_data(raw_data)
            all_weather.update(weather)
        except Exception as exc:
            log.error("Failed to fetch weather for year %s: %s", year, exc)
            continue

        time.sleep(1)  # Rate limit

    # Save individual weather files
    saved_count = 0
    for date_str in dates_to_fetch:
        if date_str not in all_weather:
            log.warning("No weather data for %s", date_str)
            continue

        weather_path = WEATHER_DIR / f"{date_str}.json"
        record = all_weather[date_str]
        record["source"] = "Open-Meteo Historical Weather API"
        record["provider"] = "Open-Meteo (ERA5 reanalysis-backed)"
        record["latitude"] = args.lat
        record["longitude"] = args.lon
        record["timezone"] = "Asia/Kolkata"
        record["temporal_resolution"] = "daily"
        record["matched_to"] = "Landsat acquisition date"

        with open(weather_path, "w", encoding="utf-8") as fh:
            json.dump(record, fh, indent=2)

        saved_count += 1
        log.info("Saved weather for %s: T=%.1f°C, RH=%.0f%%, wind=%.1f m/s",
                 date_str,
                 record.get("Temperature_Mean", 0),
                 record.get("Humidity", 0),
                 record.get("WindSpeed", 0))

    # Build manifest
    manifest = {
        "pipeline": "download_historical_weather",
        "version": "1.0.0",
        "source": "Open-Meteo Historical Weather API",
        "provider": "Open-Meteo (ERA5 reanalysis-backed)",
        "latitude": args.lat,
        "longitude": args.lon,
        "parameters": DAILY_PARAMS,
        "feature_map": WEATHER_FEATURE_MAP,
        "total_dates": len(all_dates),
        "dates_fetched": len(dates_to_fetch),
        "dates_saved": saved_count,
        "dates_in_catalogue": len(all_dates),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "elapsed_seconds": round(time.time() - t_start, 1),
    }
    with open(MANIFEST_PATH, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2)

    elapsed = time.time() - t_start
    log.info("=" * 72)
    log.info("WEATHER DOWNLOAD COMPLETE (%.1f seconds)", elapsed)
    log.info("Dates saved: %d / %d", saved_count, len(dates_to_fetch))
    log.info("Output: %s", WEATHER_DIR)
    log.info("=" * 72)

    return 0


if __name__ == "__main__":
    sys.exit(main())
