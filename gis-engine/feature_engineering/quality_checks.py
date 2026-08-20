"""
STEP 7 - Quality checks, reports & visualisations
==================================================
Runs post-merge diagnostics and writes every secondary deliverable:

    feature_statistics.json        describe() per feature column
    missing_value_report.json      missing values before/after cleaning
    quality_report.json            CRS / geometry / duplicates / ranges
    correlation_matrix.csv         Pearson correlations (numeric features)
    feature_importance_baseline.csv RandomForest baseline vs Target_LST
                                   (falls back to |corr| if sklearn absent)
    training_dataset_normalized.csv z-score normalised copy of the dataset
    plots/correlation_heatmap.png
    plots/feature_distribution.png
    plots/feature_histograms.png
    plots/spatial_feature_maps.png
    plots/target_distribution.png

Also writes the final training_dataset.csv (raw) and training_dataset.geojson.
"""

from __future__ import annotations

import json
import logging
from typing import Dict, List, Optional, Tuple

import geopandas as gpd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from config import Config, slug
from merge_features import CATEGORICAL_COLUMNS, ID_COLUMNS, normalize_numeric

logger = logging.getLogger("feature_engineering.quality")


def _numeric_features(df: pd.DataFrame) -> List[str]:
    return [c for c in df.columns
            if c not in ID_COLUMNS + CATEGORICAL_COLUMNS
            and pd.api.types.is_numeric_dtype(df[c])]


def _to_jsonable(obj):
    if isinstance(obj, dict):
        return {str(k): _to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_to_jsonable(v) for v in obj]
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        v = float(obj)
        return v if np.isfinite(v) else None
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    if isinstance(obj, (np.ndarray,)):
        return _to_jsonable(obj.tolist())
    if isinstance(obj, (pd.Timestamp,)):
        return str(obj)
    if isinstance(obj, (str, bytes)):
        return obj
    try:
        if pd.isna(obj):
            return None
    except (TypeError, ValueError):
        pass
    return obj


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------
def feature_statistics(df: pd.DataFrame) -> Dict:
    stats = {}
    for col in _numeric_features(df):
        s = df[col]
        stats[col] = {
            "count": int(s.count()),
            "mean": float(s.mean()),
            "std": float(s.std(ddof=0)),
            "min": float(s.min()),
            "p25": float(s.quantile(0.25)),
            "median": float(s.median()),
            "p75": float(s.quantile(0.75)),
            "max": float(s.max()),
        }
    return stats


def missing_value_report(df: pd.DataFrame,
                         cleaning_meta: Dict) -> Dict:
    cleaning = cleaning_meta.get("report", cleaning_meta)
    report = {
        "fill_method": cleaning.get("missing_value_fill_method"),
        "columns_dropped_excessive_missing": cleaning.get(
            "columns_dropped_excessive_missing", []),
        "columns_with_missing_before_fill": cleaning.get(
            "missing_before_fill", {}),
        "columns_with_missing_after_fill": {},
    }
    for col in df.columns:
        if col in ID_COLUMNS + ["geometry"]:
            continue
        n_missing = int(df[col].isna().sum())
        if n_missing:
            report["columns_with_missing_after_fill"][col] = n_missing
    return report


def quality_report(df: pd.DataFrame, cleaning_meta: Dict) -> Dict:
    numeric = _numeric_features(df)
    cleaning = cleaning_meta.get("report", cleaning_meta)
    report = {
        "pipeline": "GIS Feature Engineering - Urban Heat Island training dataset",
        **cleaning,
        "feature_columns": numeric,
        "n_features": len(numeric),
        "categorical_columns": [c for c in CATEGORICAL_COLUMNS if c in df.columns],
        "target_column": "Target_LST",
        "data_ranges": {c: [float(df[c].min()), float(df[c].max())]
                        for c in numeric},
        "target_stats": {
            "mean": float(df["Target_LST"].mean()),
            "std": float(df["Target_LST"].std(ddof=0)),
            "min": float(df["Target_LST"].min()),
            "max": float(df["Target_LST"].max()),
        },
    }
    return report


# ---------------------------------------------------------------------------
# Correlation matrix
# ---------------------------------------------------------------------------
def correlation_matrix(df: pd.DataFrame) -> pd.DataFrame:
    numeric = _numeric_features(df)
    return df[numeric].corr(method="pearson")


# ---------------------------------------------------------------------------
# Baseline feature importance
# ---------------------------------------------------------------------------
def baseline_importance(df: pd.DataFrame, cfg: Config) -> Tuple[pd.DataFrame, str]:
    """RandomForestRegressor importance vs Target_LST (|corr| fallback)."""
    exclude = set(cfg.quality.importance_exclude) | {"geometry", "Target_LST"}
    features = [c for c in _numeric_features(df) if c not in exclude]
    X = df[features].to_numpy()
    y = df["Target_LST"].to_numpy()

    try:
        from sklearn.ensemble import RandomForestRegressor
        model = RandomForestRegressor(
            n_estimators=cfg.quality.rf_n_estimators,
            random_state=cfg.quality.rf_random_state,
            n_jobs=-1,
        )
        model.fit(X, y)
        scores = model.feature_importances_
        method = "RandomForestRegressor (sklearn)"
    except ImportError:
        logger.warning("scikit-learn not available - using |Pearson r| "
                       "as baseline importance")
        corr = pd.Series(y).corr(pd.DataFrame(X))
        scores = np.abs(np.nan_to_num(corr.to_numpy()))
        method = "absolute Pearson correlation (fallback)"

    imp = pd.DataFrame({"feature": features, "importance": scores})
    imp = imp.sort_values("importance", ascending=False).reset_index(drop=True)
    imp["importance_pct"] = imp["importance"] / imp["importance"].sum() * 100.0
    imp = imp.round(6)
    return imp, method


# ---------------------------------------------------------------------------
# Visualisations
# ---------------------------------------------------------------------------
def _save(fig, path):
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    logger.info("Saved plot: %s", path)


def plot_correlation_heatmap(corr: pd.DataFrame, out_path) -> None:
    fig, ax = plt.subplots(figsize=(max(12, len(corr) * 0.35),
                                    max(10, len(corr) * 0.30)))
    im = ax.imshow(corr.values, cmap="coolwarm", vmin=-1, vmax=1)
    ax.set_xticks(range(len(corr)), corr.columns, rotation=90, fontsize=6)
    ax.set_yticks(range(len(corr)), corr.columns, fontsize=6)
    fig.colorbar(im, ax=ax, shrink=0.6, label="Pearson r")
    ax.set_title("Feature correlation matrix")
    _save(fig, out_path)


def plot_feature_distribution(df: pd.DataFrame, out_path) -> None:
    feats = _numeric_features(df)
    # pick a representative subset so the figure stays readable
    priority = ["MeanNDVI", "MeanLST", "BuildingDensity", "RoadDensity",
                "GreenSpacePct", "MeanElevation", "MeanSlope", "Aspect",
                "MeanPM25", "ImperviousSurfaceRatio", "HeatVulnerabilityIndex",
                "CoolingDistanceIndex"]
    cols = [c for c in priority if c in feats] + feats[:4]
    cols = list(dict.fromkeys(cols))[:12]
    norm = normalize_numeric(df[cols])
    fig, ax = plt.subplots(figsize=(12, 6))
    ax.boxplot([norm[c].dropna().values for c in cols],
               tick_labels=cols, showfliers=False)
    ax.set_xticklabels(cols, rotation=45, ha="right", fontsize=7)
    ax.set_ylabel("Z-score")
    ax.set_title("Feature distributions (normalised)")
    _save(fig, out_path)


def plot_feature_histograms(df: pd.DataFrame, out_path) -> None:
    feats = _numeric_features(df)
    n = min(12, len(feats))
    cols = feats[:n]
    ncols = 4
    nrows = int(np.ceil(n / ncols))
    fig, axes = plt.subplots(nrows, ncols, figsize=(3.2 * ncols, 2.4 * nrows))
    axes = np.atleast_1d(axes).ravel()
    for ax, col in zip(axes, cols):
        ax.hist(df[col].dropna().values, bins=40, color="#4C72B0", alpha=0.85)
        ax.set_title(col, fontsize=7)
        ax.tick_params(labelsize=5)
    for ax in axes[len(cols):]:
        ax.axis("off")
    fig.suptitle("Feature histograms", fontsize=12)
    fig.tight_layout()
    _save(fig, out_path)


def plot_spatial_maps(gdf: gpd.GeoDataFrame, out_path) -> None:
    cols = ["MeanLST", "MeanNDVI", "BuildingDensity", "GreenSpacePct"]
    cols = [c for c in cols if c in gdf.columns]
    n = len(cols)
    if n == 0:
        return
    fig, axes = plt.subplots(1, n, figsize=(4.6 * n, 4.4))
    axes = np.atleast_1d(axes)
    for ax, col in zip(axes, cols):
        gdf.plot(column=col, ax=ax, legend=True,
                 cmap="viridis_r" if col == "MeanLST" else "viridis",
                 legend_kwds={"shrink": 0.7}, edgecolor="none", linewidth=0)
        ax.set_title(col, fontsize=9)
        ax.set_axis_off()
    fig.suptitle("Spatial feature maps (100 m grid)", fontsize=12)
    fig.tight_layout()
    _save(fig, out_path)


def plot_target_distribution(df: pd.DataFrame, out_path) -> None:
    vals = df["Target_LST"].dropna().values
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.hist(vals, bins=60, density=True, alpha=0.7, color="#C44E52",
            label="histogram")
    try:
        from scipy.stats import gaussian_kde
        xs = np.linspace(vals.min(), vals.max(), 300)
        ax.plot(xs, gaussian_kde(vals)(xs), color="black", lw=1.5,
                label="KDE")
    except Exception:  # noqa: BLE001
        pass
    ax.axvline(vals.mean(), color="grey", ls="--", lw=1,
               label=f"mean = {vals.mean():.2f} C")
    ax.set_xlabel("Target_LST (degC)")
    ax.set_ylabel("density")
    ax.set_title("Target distribution - cell mean land surface temperature")
    ax.legend()
    _save(fig, out_path)


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------
def run_quality_checks(gdf: gpd.GeoDataFrame,
                       cfg: Config,
                       cleaning_meta: Dict) -> Dict:
    """
    Write every secondary deliverable + the final dataset files.

    Returns a small summary dict.
    """
    cfg.paths.ensure()
    plt.rcParams["savefig.dpi"] = cfg.quality.plot_dpi
    df = gdf.drop(columns=["geometry"], errors="ignore").copy()

    # --- final dataset files ------------------------------------------------
    # Raw CSV: what XGBoost will consume (tree models are scale-invariant).
    df.to_csv(cfg.paths.dataset_csv, index=False)
    # Normalised copy (STEP 6 "normalize numeric variables").
    norm = normalize_numeric(df)
    norm.to_csv(cfg.paths.dataset_normalized_csv, index=False)
    # Spatial export.
    gdf_out = gdf.copy()
    if "geometry" in gdf_out.columns and gdf_out.crs is None:
        gdf_out = gdf_out.set_crs(epsg=cfg.grid.target_epsg)
    gdf_out.to_file(cfg.paths.dataset_geojson, driver="GeoJSON")

    # --- correlation + importance -------------------------------------------
    corr = correlation_matrix(df)
    corr.round(6).to_csv(cfg.paths.correlation_matrix)
    importance, method = baseline_importance(df, cfg)
    importance.to_csv(cfg.paths.feature_importance, index=False)

    # --- JSON reports --------------------------------------------------------
    with open(cfg.paths.feature_statistics, "w", encoding="utf-8") as fh:
        json.dump(_to_jsonable(feature_statistics(df)), fh, indent=2)
    with open(cfg.paths.missing_value_report, "w", encoding="utf-8") as fh:
        json.dump(_to_jsonable(missing_value_report(df, cleaning_meta)),
                  fh, indent=2)
    with open(cfg.paths.quality_report, "w", encoding="utf-8") as fh:
        json.dump(_to_jsonable(quality_report(df, cleaning_meta)), fh, indent=2)

    # --- plots ---------------------------------------------------------------
    plot_correlation_heatmap(corr, cfg.paths.plots / "correlation_heatmap.png")
    plot_feature_distribution(df, cfg.paths.plots / "feature_distribution.png")
    plot_feature_histograms(df, cfg.paths.plots / "feature_histograms.png")
    plot_spatial_maps(gdf, cfg.paths.plots / "spatial_feature_maps.png")
    plot_target_distribution(df, cfg.paths.plots / "target_distribution.png")

    logger.info("Baseline importance method: %s", method)
    logger.info("Top 5 predictors: %s",
                importance.head(5)["feature"].tolist())
    return {
        "rows": int(len(df)),
        "columns": int(len(df.columns)),
        "importance_method": method,
        "top_predictors": importance.head(10)["feature"].tolist(),
    }
