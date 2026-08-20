"""
STEPS 4-8 - NASA POWER weather processing
=========================================
Reads the raw POWER JSON, cleans and validates the daily series, applies unit
conversions, then derives:

  STEP 4  cleaned daily data (missing values removed, units converted, dates validated)
  STEP 5  monthly averages, seasonal averages, heat index, rolling 7-day averages
  STEP 6  five trend plots (temperature, humidity, wind, rainfall, solar)
  STEP 7  summary statistics + monthly climatology
  STEP 8  weather_daily.csv, weather_monthly.csv, weather_statistics.json, plots

Outputs:
  data/processed/weather/weather_daily.csv, weather_monthly.csv
  data/statistics/weather/weather_statistics.json
  data/plots/weather/{temperature,humidity,wind,rainfall,solar}_plot.png
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import matplotlib

matplotlib.use("Agg")  # headless-safe

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from tqdm import tqdm

from config import Config
from utils import PipelineError, read_json, write_json

logger = logging.getLogger("sentinel.weather.process")

SEASONS = {"DJF": [12, 1, 2], "MAM": [3, 4, 5], "JJA": [6, 7, 8], "SON": [9, 10, 11]}
SEASON_OF_MONTH = {m: s for s, months in SEASONS.items() for m in months}

PLOT_SPECS = {
    "T2M": ("temperature_plot.png", "Air Temperature at 2 m (°C)", "#d73027"),
    "RH2M": ("humidity_plot.png", "Relative Humidity at 2 m (%)", "#2c7bb6"),
    "WS2M": ("wind_plot.png", "Wind Speed at 2 m (m/s)", "#1a9850"),
    "PRECTOTCORR": ("rainfall_plot.png", "Precipitation (mm/day)", "#4575b4"),
    "ALLSKY_SFC_SW_DWN": ("solar_plot.png", "Solar Radiation (W/m²)", "#fdae61"),
}


# ---------------------------------------------------------------------------
# STEP 4 - load, clean, validate
# ---------------------------------------------------------------------------
def find_raw_json(cfg: Config) -> Path:
    """Locate the POWER JSON (explicit metadata path or glob fallback)."""
    meta = read_json(cfg.paths.raw_weather / "weather_metadata.json")
    explicit = meta.get("json_path")
    if explicit and Path(explicit).exists():
        return Path(explicit)
    matches = sorted(cfg.paths.raw_weather.glob("power_daily_*.json"))
    if not matches:
        raise PipelineError("No NASA POWER JSON found - run the download stage first")
    return matches[-1]


def load_daily_frame(cfg: Config) -> pd.DataFrame:
    """Parse the POWER JSON into a cleaned daily DataFrame (index = date)."""
    raw = json.loads(find_raw_json(cfg).read_text(encoding="utf-8"))
    parameters = raw["properties"]["parameter"]
    if not parameters:
        raise PipelineError("NASA POWER response contains no parameters")

    first = next(iter(parameters.values()))
    dates = pd.to_datetime(list(first.keys()), format="%Y%m%d")
    df = pd.DataFrame(
        {param: list(values.values()) for param, values in parameters.items()},
        index=dates,
    )
    df.index.name = "date"
    df = df[~df.index.duplicated()].sort_index()

    # Missing-value flag -> NaN
    missing = df == cfg.weather.missing_flag
    n_missing = int(missing.sum().sum())
    df = df.replace(cfg.weather.missing_flag, np.nan)

    # Unit conversions (configurable factors)
    for param, factor in cfg.weather.unit_conversions.items():
        if param in df.columns:
            df[param] = df[param] * factor

    # Date validation: report gaps in an otherwise continuous daily series
    expected = pd.date_range(df.index.min(), df.index.max(), freq="D")
    gaps = len(expected.difference(df.index))
    if gaps:
        logger.warning("Date validation: %d missing day(s) in %s..%s",
                       gaps, df.index.min().date(), df.index.max().date())
    logger.info("Loaded %d days (%s .. %s), %d missing value cell(s), %d date gap(s)",
                len(df), df.index.min().date(), df.index.max().date(), n_missing, gaps)
    return df


# ---------------------------------------------------------------------------
# STEP 5 - derived variables
# ---------------------------------------------------------------------------
def heat_index(t_c: pd.Series, rh: pd.Series) -> pd.Series:
    """
    NOAA Rothfusz heat index (degC), with the standard low-T / low-RH fallback.

    Applicable for T >= 27 degC and RH >= 40 %; outside that range a simpler
    Steadman-style approximation is used.
    """
    t_f = t_c * 9.0 / 5.0 + 32.0
    rh = rh.clip(lower=0.0)
    with np.errstate(invalid="ignore"):  # sqrt radicand can be negative where not used
        hi = (
            -42.379 + 2.04901523 * t_f + 10.14333127 * rh - 0.22475541 * t_f * rh
            - 0.00683783 * t_f ** 2 - 0.05481717 * rh ** 2 + 0.00122874 * t_f ** 2 * rh
            + 0.00085282 * t_f * rh ** 2 - 0.00000199 * t_f ** 2 * rh ** 2
        )
        # Adjustments for low humidity and very hot-humid conditions (NOAA)
        hi = np.where((rh < 13) & (t_f >= 80) & (t_f <= 112),
                      hi - ((13 - rh) / 4) * np.sqrt((17 - np.abs(t_f - 95)) / 17), hi)
        hi = np.where((rh > 85) & (t_f >= 80) & (t_f <= 87),
                      hi + ((rh - 85) / 10) * ((87 - t_f) / 5), hi)
        simple = 0.5 * (t_f + 61.0 + (t_f - 68.0) * 1.2 + rh * 0.094)
        hi = np.where((t_f < 80) | (rh < 40), simple, hi)
    hi = pd.Series((hi - 32) * 5.0 / 9.0, index=t_c.index)
    hi[t_c.isna() | rh.isna()] = np.nan
    return hi


def add_derived_variables(df: pd.DataFrame, cfg: Config) -> pd.DataFrame:
    """Add season, heat index and 7-day rolling averages to the daily frame."""
    out = df.copy()

    out["season"] = [SEASON_OF_MONTH[m] for m in out.index.month]

    if "T2M" in out.columns and "RH2M" in out.columns:
        out["HEAT_INDEX"] = heat_index(out["T2M"], out["RH2M"])

    rolling_cols = [c for c in out.columns if c != "season"]
    out[[f"{c}_7d" for c in rolling_cols]] = (
        out[rolling_cols].rolling(7, min_periods=1).mean()
    )
    return out


def monthly_averages(df: pd.DataFrame) -> pd.DataFrame:
    """Calendar-month means of the numeric daily variables."""
    numeric = df.select_dtypes(include=[np.number])
    return numeric.resample("MS").mean()


# ---------------------------------------------------------------------------
# STEP 6 - plots
# ---------------------------------------------------------------------------
def plot_series(df: pd.DataFrame, column: str, filename: str, title: str,
                color: str, cfg: Config) -> Path:
    out = cfg.paths.weather_plots / filename
    if out.exists() and cfg.pipeline.skip_existing and not cfg.pipeline.force:
        return out
    fig, ax = plt.subplots(figsize=(13, 5))
    ax.plot(df.index, df[column], color=color, linewidth=0.6, alpha=0.55,
            label="daily")
    ax.plot(df.index, df[column].rolling(30, min_periods=1).mean(),
            color="black", linewidth=1.4, label="30-day mean")
    ax.set_title(title, fontweight="bold")
    ax.set_xlabel("Date"); ax.set_ylabel(title.split(" (")[1].rstrip(")"))
    ax.legend(loc="upper right", fontsize=9)
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(out, dpi=cfg.pipeline.preview_dpi, bbox_inches="tight")
    plt.close(fig)
    logger.info("Plot saved -> %s", out)
    return out


def generate_plots(df: pd.DataFrame, cfg: Config) -> Dict[str, Path]:
    """STEP 6: one trend plot per requested weather variable."""
    cfg.paths.weather_plots.mkdir(parents=True, exist_ok=True)
    plots: Dict[str, Path] = {}
    for column, (filename, title, color) in tqdm(
            PLOT_SPECS.items(), desc="Weather plots", leave=False):
        if column not in df.columns:
            logger.warning("Column %s missing - skipping its plot", column)
            continue
        plots[column] = plot_series(df, column, filename, title, color, cfg)
    return plots


# ---------------------------------------------------------------------------
# STEP 7 - statistics
# ---------------------------------------------------------------------------
def describe_daily(df: pd.DataFrame) -> Dict[str, dict]:
    stats = {}
    for col in df.select_dtypes(include=[np.number]).columns:
        s = df[col]
        stats[col] = {
            "mean": round(float(s.mean()), 2),
            "max": round(float(s.max()), 2),
            "min": round(float(s.min()), 2),
            "std": round(float(s.std()), 2),
            "missing_days": int(s.isna().sum()),
        }
    return stats


def monthly_climatology(df: pd.DataFrame) -> Dict[str, Dict[str, float]]:
    """Mean of each variable per calendar month (Jan..Dec) across all years."""
    clim = {}
    numeric = df.select_dtypes(include=[np.number])
    for month in range(1, 13):
        subset = numeric[numeric.index.month == month]
        clim[f"{month:02d}"] = {
            col: (round(float(subset[col].mean()), 2) if len(subset) else None)
            for col in numeric.columns
        }
    return clim


def seasonal_climatology(df: pd.DataFrame) -> Dict[str, Dict[str, float]]:
    """Mean of each variable per meteorological season (DJF/MAM/JJA/SON)."""
    numeric = df.select_dtypes(include=[np.number])
    out = {}
    for season, months in SEASONS.items():
        subset = numeric[numeric.index.month.isin(months)]
        out[season] = {
            col: (round(float(subset[col].mean()), 2) if len(subset) else None)
            for col in numeric.columns
        }
    return out


def build_statistics(df: pd.DataFrame, raw_json: Path, cfg: Config) -> dict:
    hi = df.get("HEAT_INDEX")
    return {
        "source": {
            "provider": "NASA POWER",
            "json": str(raw_json),
            "community": cfg.weather.community,
            "period": {
                "start": str(df.index.min().date()),
                "end": str(df.index.max().date()),
                "days": int(len(df)),
            },
            "parameters": {p: {"unit_after_conversion": _unit(p, cfg)}
                           for p in cfg.weather.parameters},
        },
        "daily_stats": describe_daily(df),
        "monthly_climatology": monthly_climatology(df),
        "seasonal_climatology": seasonal_climatology(df),
        "heat_index": {
            "max": round(float(hi.max()), 2) if hi is not None and hi.notna().any() else None,
            "mean": round(float(hi.mean()), 2) if hi is not None and hi.notna().any() else None,
            "days_above_35c": int((hi > 35.0).sum()) if hi is not None else None,
            "days_above_40c": int((hi > 40.0).sum()) if hi is not None else None,
            "unit": "degC",
        } if hi is not None else None,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def _unit(param: str, cfg: Config) -> str:
    units = {
        "T2M": "degC", "RH2M": "%", "WS2M": "m/s",
        "PRECTOTCORR": "mm/day",
    }
    if param == "PS":
        return "hPa" if param in cfg.weather.unit_conversions else "kPa"
    if param == "ALLSKY_SFC_SW_DWN":
        return "W/m2" if param in cfg.weather.unit_conversions else "kWh/m2/day"
    return units.get(param, "unknown")


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------
def process_weather(cfg: Config) -> Tuple[Dict[str, Path], dict]:
    """STEPS 4-8: clean, derive, plot, summarise, export. Returns (outputs, stats)."""
    raw_json = find_raw_json(cfg)

    # ---- STEP 4: clean + convert ----
    df = load_daily_frame(cfg)
    if df.empty:
        raise PipelineError("Weather data frame is empty after cleaning")

    # ---- STEP 5: derived variables ----
    df = add_derived_variables(df, cfg)
    monthly = monthly_averages(df)

    # ---- STEP 8: exports ----
    cfg.paths.weather_processed.mkdir(parents=True, exist_ok=True)
    cfg.paths.weather_stats.mkdir(parents=True, exist_ok=True)
    daily_csv = cfg.paths.weather_processed / "weather_daily.csv"
    monthly_csv = cfg.paths.weather_processed / "weather_monthly.csv"
    daily_csv.write_text(df.to_csv())
    monthly_csv.write_text(monthly.to_csv())
    logger.info("Exported -> %s / %s", daily_csv.name, monthly_csv.name)

    # ---- STEP 6: plots ----
    plots = generate_plots(df, cfg)

    # ---- STEP 7: statistics ----
    stats = build_statistics(df, raw_json, cfg)
    stats_path = write_json(cfg.paths.weather_stats / "weather_statistics.json", stats)

    outputs: Dict[str, Path] = {
        "weather_daily.csv": daily_csv,
        "weather_monthly.csv": monthly_csv,
        "weather_statistics.json": stats_path,
    }
    outputs.update(plots)
    logger.info("Weather processing complete: %d output files", len(outputs))
    return outputs, stats


if __name__ == "__main__":  # pragma: no cover
    from utils import setup_logging

    cfg = Config.from_env()
    cfg.paths.ensure()
    setup_logging(cfg)
    outputs, stats = process_weather(cfg)
    t = stats["daily_stats"]["T2M"]
    print(f"\nT2M: mean {t['mean']} | max {t['max']} | min {t['min']} degC")
    print(f"Heat index > 35C: {stats['heat_index']['days_above_35c']} days")
    for name, path in outputs.items():
        print(f"  {name}: {path}")
