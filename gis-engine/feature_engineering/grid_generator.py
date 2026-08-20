"""
STEP 1 - Grid generator
=======================
Builds a regular N x N metre grid (default 100 m) clipped to the study-area
boundary. Every cell gets:

    Grid_ID    - unique integer id (1..N)
    Latitude   - cell centroid latitude  (WGS84)
    Longitude  - cell centroid longitude (WGS84)
    Area       - cell area in square metres (partial cells at the boundary
                 are clipped, so the area is the true on-the-ground area)

The grid is generated and stored in the projected working CRS (UTM 45N /
EPSG:32645) so all vector distances and raster resolutions are in metres.
"""

from __future__ import annotations

import logging
from typing import Optional

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import box
from shapely.ops import unary_union

from config import Config

logger = logging.getLogger("feature_engineering.grid")


def generate_grid(
    boundary: gpd.GeoDataFrame,
    cfg: Config,
    cell_size_m: Optional[float] = None,
) -> gpd.GeoDataFrame:
    """
    Generate a regular grid over the study area.

    Parameters
    ----------
    boundary : GeoDataFrame in any CRS (reprojected internally).
    cfg      : pipeline configuration.
    cell_size_m : optional override of the configured cell size.

    Returns
    -------
    GeoDataFrame (EPSG:32645) with columns Grid_ID, geometry, Area,
    Latitude, Longitude.
    """
    cell = float(cell_size_m or cfg.grid.cell_size_m)
    if cell <= 0:
        raise ValueError(f"cell_size_m must be > 0, got {cell}")

    logger.info("Building %g m grid (EPSG:%d) ...", cell, cfg.grid.target_epsg)
    boundary_utm = boundary.to_crs(epsg=cfg.grid.target_epsg)
    boundary_geom = unary_union(boundary_utm.geometry.to_list())
    minx, miny, maxx, maxy = boundary_geom.bounds

    xs = np.arange(minx, maxx, cell)
    ys = np.arange(miny, maxy, cell)
    logger.info(
        "Grid extent: %.0f x %.0f m -> %d x %d cells (pre-clip)",
        maxx - minx, maxy - miny, len(xs), len(ys),
    )

    cells = [box(x, y, x + cell, y + cell) for x in xs for y in ys]
    grid = gpd.GeoDataFrame(geometry=cells, crs=cfg.grid.target_epsg)
    grid["Grid_ID"] = np.arange(1, len(grid) + 1)

    # Keep only cells that touch the study area, then clip to it so partial
    # boundary cells carry their true area.
    touches = grid.intersects(boundary_geom)
    grid = grid.loc[touches].copy()
    clipped = grid.geometry.intersection(boundary_geom)
    grid["geometry"] = clipped
    grid = grid[~grid.geometry.is_empty & grid.geometry.notna()].copy()
    grid["geometry"] = grid.geometry.buffer(0)

    grid["Area"] = grid.geometry.area  # square metres (projected CRS)
    centroids = grid.geometry.centroid.to_crs(epsg=cfg.grid.wgs84_epsg)
    grid["Latitude"] = centroids.y.values
    grid["Longitude"] = centroids.x.values

    grid = grid[["Grid_ID", "geometry", "Area", "Latitude", "Longitude"]]
    grid = grid.reset_index(drop=True)
    logger.info("Grid complete: %d cells, total area %.1f km2",
                len(grid), grid["Area"].sum() / 1e6)
    return grid


def load_boundary(cfg: Config) -> gpd.GeoDataFrame:
    """Load the study-area boundary GeoJSON (any CRS)."""
    if not cfg.paths.boundary.exists():
        raise FileNotFoundError(f"Boundary file not found: {cfg.paths.boundary}")
    boundary = gpd.read_file(cfg.paths.boundary)
    if boundary.empty:
        raise ValueError(f"Boundary contains no features: {cfg.paths.boundary}")
    if boundary.crs is None:
        raise ValueError(f"Boundary has no CRS: {cfg.paths.boundary}")
    logger.info("Boundary loaded: %s | CRS: %s | features: %d",
                cfg.paths.boundary.name, boundary.crs, len(boundary))
    return boundary
