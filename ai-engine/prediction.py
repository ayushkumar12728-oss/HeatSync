"""
Full-grid prediction & raster export (STEP 10)
==============================================
The training dataset already covers every 100 m grid cell of the study
area (53,802 cells). This module:

    1. Predicts LST for every grid cell with the final model.
    2. Writes data/predictions/predictions.csv           (test-set predictions)
    3. Writes data/predictions/Predicted_LST.geojson     (grid polygons + predictions)
    4. Writes data/predictions/Predicted_LST.tif         (100 m GeoTIFF, UTM 45N)
    5. Writes data/predictions/Predicted_LST.png         (map preview)

No additional GIS processing is performed - the polygons, CRS and grid
layout are taken directly from the feature-engineering outputs.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import List, Optional

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from shapely.geometry import shape
from tqdm import tqdm

log = logging.getLogger("aie.prediction")


class GridPredictor:
    """Predicts LST across the whole 100 m grid and exports geospatial outputs."""

    def __init__(self, cfg):
        self.cfg = cfg

    # ------------------------------------------------------------------ #
    def predict_all(self, model, X_all: pd.DataFrame, feature_cols: List[str],
                    ids: Optional[pd.Series] = None) -> pd.DataFrame:
        """Predict for every grid cell; returns DataFrame indexed like X_all."""
        pred = model.predict(X_all[feature_cols])
        out = pd.DataFrame({"Predicted_LST": pred}, index=X_all.index)
        if ids is not None:
            out.insert(0, "Grid_ID", ids.values)
        log.info("Predicted LST for %d grid cells (mean %.2f°C, std %.2f)",
                 len(out), float(pred.mean()), float(pred.std()))
        return out

    # ------------------------------------------------------------------ #
    def save_predictions_csv(self, test_pred: pd.DataFrame, y_test: pd.Series,
                             ids: Optional[pd.Series] = None) -> Path:
        """Test-set prediction table: Grid_ID, actual, predicted, residual."""
        df = pd.DataFrame({
            "Grid_ID": ids.values if ids is not None else np.arange(len(y_test)),
            "Target_LST": y_test.values,
            "Predicted_LST": test_pred["Predicted_LST"].values,
        })
        df["Residual"] = df["Predicted_LST"] - df["Target_LST"]
        path = self.cfg.paths.predictions_csv
        df.to_csv(path, index=False)
        log.info("Predictions CSV written: %s (%d rows)", path, len(df))
        return path

    # ------------------------------------------------------------------ #
    def export_geojson(self, all_pred: pd.DataFrame,
                       grid_ids: pd.Series) -> Optional[Path]:
        """Attach predicted LST (and residual) to the grid polygons."""
        if self.cfg.paths.dataset_geojson is None or not self.cfg.paths.dataset_geojson.exists():
            log.warning("No grid GeoJSON available - skipping Predicted_LST.geojson")
            return None
        with open(self.cfg.paths.dataset_geojson, "r", encoding="utf-8") as fh:
            geojson = json.load(fh)

        # Map Grid_ID -> predicted value (join for safety, not position).
        pred_map = dict(zip(grid_ids.values, all_pred["Predicted_LST"].values))
        # residual vs observed target when available
        has_target = "Target_LST" in (geojson["features"][0]["properties"] if geojson["features"] else {})

        for f in tqdm(geojson["features"], desc="Annotating GeoJSON", ncols=100):
            props = f["properties"]
            gid = props.get("Grid_ID")
            pred = pred_map.get(gid)
            if pred is not None:
                props["Predicted_LST"] = float(pred)
                if has_target and "Target_LST" in props:
                    props["LST_Residual"] = float(pred - props["Target_LST"])

        out = self.cfg.paths.predicted_geojson
        with open(out, "w", encoding="utf-8") as fh:
            json.dump(geojson, fh)
        log.info("Predicted GeoJSON written: %s", out)
        return out

    # ------------------------------------------------------------------ #
    def export_tif_png(self, all_pred: pd.DataFrame,
                       grid_ids: pd.Series) -> Optional[Path]:
        """Rasterize predicted LST to a 100 m GeoTIFF + PNG preview."""
        geojson_path = self.cfg.paths.dataset_geojson
        if not geojson_path.exists():
            log.warning("No grid GeoJSON - skipping Predicted_LST.tif / .png")
            return None

        with open(geojson_path, "r", encoding="utf-8") as fh:
            geojson = json.load(fh)

        pred_map = dict(zip(grid_ids.values, all_pred["Predicted_LST"].values))
        shapes = []
        xs, ys = [], []
        for f in geojson["features"]:
            gid = f["properties"].get("Grid_ID")
            val = pred_map.get(gid)
            if val is None:
                continue
            geom = shape(f["geometry"])
            shapes.append((geom, float(val)))
            xs.extend([geom.bounds[0], geom.bounds[2]])
            ys.extend([geom.bounds[1], geom.bounds[3]])

        if not shapes:
            log.warning("No matching grid cells for raster export.")
            return None

        import rasterio
        from rasterio import features as rio_features
        from rasterio.transform import from_origin

        cell = self.cfg.prediction.cell_size_m
        west, east, south, north = min(xs), max(xs), min(ys), max(ys)
        width = max(1, int(np.ceil((east - west) / cell)))
        height = max(1, int(np.ceil((north - south) / cell)))
        transform = from_origin(west, north, cell, cell)
        nodata = self.cfg.prediction.nodata

        raster = rio_features.rasterize(
            shapes, out_shape=(height, width), transform=transform,
            fill=nodata, dtype="float32",
        )
        # Values outside grid polygons remain nodata.
        raster = np.where(raster == nodata, np.nan, raster)

        tif_path = self.cfg.paths.predicted_tif
        with rasterio.open(
            tif_path, "w", driver="GTiff", height=height, width=width,
            count=1, dtype="float32", crs=self.cfg.prediction.crs,
            transform=transform, nodata=nodata,
        ) as dst:
            dst.write(np.where(np.isnan(raster), nodata, raster).astype("float32"), 1)
        log.info("GeoTIFF written: %s (%dx%d @ %dm, %s)",
                 tif_path, width, height, cell, self.cfg.prediction.crs)

        self._render_png(raster, transform)
        return tif_path

    # ------------------------------------------------------------------ #
    def _render_png(self, raster: np.ndarray, transform) -> Path:
        """Render the predicted-LST raster as a PNG preview."""
        import matplotlib.colors as mcolors

        valid = raster[~np.isnan(raster)]
        vmin, vmax = float(np.nanmin(raster)), float(np.nanmax(raster))
        cmap = plt.get_cmap("RdYlBu_r")
        cmap.set_bad(color="#d9d9d9")  # nodata cells in grey
        norm = mcolors.Normalize(vmin=vmin, vmax=vmax)

        fig, ax = plt.subplots(figsize=(10, 9))
        img = ax.imshow(raster, cmap=cmap, norm=norm)
        ax.set_title("Predicted Land Surface Temperature (°C) - 100 m grid")
        ax.set_xlabel("UTM 45N easting (m)")
        ax.set_ylabel("UTM 45N northing (m)")
        ax.grid(alpha=0.15)
        cbar = fig.colorbar(img, ax=ax, shrink=0.85)
        cbar.set_label("Predicted LST (°C)")
        fig.tight_layout()
        out = self.cfg.paths.predicted_png
        fig.savefig(out, dpi=150, bbox_inches="tight")
        plt.close(fig)
        log.info("PNG map written: %s", out)
        return out
