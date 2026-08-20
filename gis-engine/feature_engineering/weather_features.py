"""
STEP 4 - Weather features
=========================
Joins the NASA POWER weather archive (already processed into
``weather_daily.csv`` / ``weather_monthly.csv``) to the grid by the *scene
acquisition date* (taken from the Landsat LST statistics, overridable via
``--acquisition-date``).

Every grid cell of a scene shares the same meteorological conditions, so the
weather row for the acquisition date is broadcast to all cells:

    Temperature, Humidity, WindSpeed, Pressure, SolarRadiation, Rainfall,
    HeatIndex                       (daily values)
    Temperature_7d, Humidity_7d, ... (7-day rolling means, precomputed)
    Temperature_MonthlyMean, ...     (monthly means from the monthly archive)
    Season, Month                    (season code + calendar month)

The weather files are treated as read-only inputs - nothing is downloaded.
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime
from typing import Dict, Optional

import numpy as np
import pandas as pd

from config import Config

logger = logging.getLogger("feature_engineering.weather")


def get_acquisition_date(cfg: Config,
                         override: Optional[str] = None) -> date:
    """Resolve the scene acquisition date (LST statistics JSON or override)."""
    if override:
        return datetime.strptime(override, "%Y-%m-%d").date()

    if cfg.paths.lst_stats.exists():
        try:
            with open(cfg.paths.lst_stats, "r", encoding="utf-8") as fh:
                stats = json.load(fh)
            raw = stats.get("acquisition_date") or stats.get("date")
            if raw:
                return datetime.fromisoformat(str(raw).replace("Z", "+00:00")).date()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not read acquisition date from %s: %s",
                           cfg.paths.lst_stats, exc)

    # Fall back to the last available daily weather record
    daily = pd.read_csv(cfg.paths.weather_daily, parse_dates=[cfg.weather.date_col])
    last = pd.to_datetime(daily[cfg.weather.date_col]).max().date()
    logger.warning("No acquisition date found - using latest weather date %s", last)
    return last


def _nearest_date_row(daily: pd.DataFrame, target: date,
                      date_col: str) -> pd.Series:
    dates = pd.to_datetime(daily[date_col]).dt.date
    if target in set(dates):
        return daily.loc[dates == target].iloc[0]
    idx = (dates.apply(lambda d: abs((d - target).days))).idxmin()
    nearest = dates.loc[idx]
    logger.info("Exact weather row for %s not found - using nearest date %s",
                target, nearest)
    return daily.loc[idx]


def load_weather_features(cfg: Config,
                          acquisition_date: Optional[str] = None,
                          ) -> pd.DataFrame:
    """
    Build a single-row DataFrame of weather features for the acquisition
    date (index = [0]); main.py broadcasts it to every grid cell.
    """
    daily = pd.read_csv(cfg.paths.weather_daily,
                        parse_dates=[cfg.weather.date_col])
    target = get_acquisition_date(cfg, acquisition_date)
    row = _nearest_date_row(daily, target, cfg.weather.date_col)

    col_map = cfg.weather.column_map
    features: Dict[str, float] = {}
    for src, dst in col_map.items():
        if src in daily.columns:
            features[dst] = float(row[src])
        features[f"{dst}{cfg.weather.rolling_suffix}"] = (
            float(row[f"{src}{cfg.weather.rolling_suffix}"])
            if f"{src}{cfg.weather.rolling_suffix}" in daily.columns else np.nan
        )

    # Season + month --------------------------------------------------------
    acq = pd.Timestamp(target)
    features["Season"] = row[cfg.weather.season_col] if cfg.weather.season_col in daily.columns else "NA"
    features["Month"] = int(acq.month)

    # Monthly means from the monthly archive (same month as acquisition) ----
    if cfg.paths.weather_monthly.exists():
        monthly = pd.read_csv(cfg.paths.weather_monthly,
                              parse_dates=[cfg.weather.date_col])
        month_col = pd.to_datetime(monthly[cfg.weather.date_col]).dt.to_period("M")
        match = monthly[month_col == acq.to_period("M")]
        if not match.empty:
            mrow = match.iloc[0]
            for src, dst in col_map.items():
                if src in monthly.columns:
                    features[f"{dst}{cfg.weather.monthly_suffix}"] = float(mrow[src])
        else:
            logger.info("No monthly row for %s - monthly means left NaN",
                        acq.to_period("M"))

    df = pd.DataFrame([features])
    logger.info("Weather features for acquisition date %s: %d columns",
                target, len(df.columns))
    return df
