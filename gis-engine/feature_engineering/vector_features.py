"""
STEP 2 - Vector features
========================
Computes, for every 100 m grid cell, all urban-morphology features derived
from the OpenStreetMap vector layers:

    Buildings : BuildingCount, BuildingDensity, BuildingCoveragePct,
                AvgBuildingFootprint
    Roads     : RoadLength, RoadDensity, RoadIntersectionCount,
                RoadIntersectionDensity, DistToMajorRoad
    Trees     : TreeCount, TreeDensity
    Green     : GreenSpacePct
    Land use  : LandUse_<Class>Pct  (residential, commercial, industrial,
                institutional, agriculture, green, railway, other)
    Distances : DistToPark, DistToWater, DistToHospital, DistToSchool,
                DistToBusStop (nearest-edge, metres)
    Amenities : BusStopCount, BusStopDensity, HospitalCount, SchoolCount

All geometry work is performed in the projected working CRS (EPSG:32645) so
lengths / areas / distances are true metres.  Nearest-neighbour distances are
computed with a shapely STRtree, parallelised over cell chunks.
"""

from __future__ import annotations

import logging
import math
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from typing import Dict, List, Optional

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import Point
from shapely.ops import unary_union
from shapely.strtree import STRtree

from config import Config

logger = logging.getLogger("feature_engineering.vector")


# ---------------------------------------------------------------------------
# Layer loading helpers
# ---------------------------------------------------------------------------
def _clean_layer(gdf: gpd.GeoDataFrame, epsg: int) -> gpd.GeoDataFrame:
    """Drop empty/invalid geometries, reproject and repair (buffer 0)."""
    gdf = gdf.copy()
    gdf = gdf[gdf.geometry.notna() & ~gdf.geometry.is_empty]
    if gdf.crs is None:
        raise ValueError("Layer has no CRS; cannot reproject to EPSG:%d" % epsg)
    gdf = gdf.to_crs(epsg=epsg)
    # buffer(0) repairs invalid *polygons* only - it empties lines/points
    poly_mask = gdf.geometry.geom_type.isin(["Polygon", "MultiPolygon"])
    gdf.loc[poly_mask, "geometry"] = gdf.loc[poly_mask].geometry.buffer(0)
    gdf = gdf[~gdf.geometry.is_empty].copy()
    return gdf


def _load_candidates(cfg: Config, logical_name: str) -> Optional[gpd.GeoDataFrame]:
    """Load and merge every existing candidate file for a logical layer."""
    frames: List[gpd.GeoDataFrame] = []
    seen: set = set()
    for fname in cfg.paths.vector_layers.get(logical_name, []):
        path = (cfg.paths.osm_layers / fname).resolve()
        # Windows filesystems are case-insensitive: candidate names that only
        # differ by case point at the same file - load it once.
        if path in seen:
            continue
        seen.add(path)
        if not path.exists():
            continue
        try:
            frames.append(gpd.read_file(path))
        except Exception as exc:  # noqa: BLE001 - one bad file must not kill the run
            logger.warning("Failed to read layer file %s: %s", path, exc)
    if not frames:
        return None
    merged = pd.concat(frames, ignore_index=True)
    return _clean_layer(merged, cfg.grid.target_epsg)


def resolve_layers(cfg: Config) -> Dict[str, Optional[gpd.GeoDataFrame]]:
    """Resolve all logical vector layers (missing layers become None)."""
    layers: Dict[str, Optional[gpd.GeoDataFrame]] = {}
    for name in cfg.paths.vector_layers:
        layer = _load_candidates(cfg, name)
        layers[name] = layer
        if layer is None:
            logger.warning("Vector layer '%s' is missing - its features will be NaN",
                           name)
        else:
            logger.info("Vector layer '%-11s': %d features",
                        name, len(layer))
    return layers


# ---------------------------------------------------------------------------
# Nearest-neighbour distances (parallel, chunked over cells)
# ---------------------------------------------------------------------------
def _distance_chunk_worker(payload):
    """Top-level worker: nearest distance for one chunk of centroids.

    payload = (layer_geometries, chunk_centroids)
    """
    layer_geoms, centroids = payload
    if not layer_geoms or not centroids:
        return [np.nan] * len(centroids)
    tree = STRtree(layer_geoms)
    idx = tree.nearest(centroids)
    return [layer_geoms[i].distance(c) for i, c in zip(idx, centroids)]


def _chunked(lst, size):
    for i in range(0, len(lst), size):
        yield lst[i:i + size]


def nearest_distances(cells: gpd.GeoDataFrame,
                      layer: Optional[gpd.GeoDataFrame],
                      cfg: Config) -> np.ndarray:
    """
    Distance (metres) from every cell centroid to the nearest feature of a
    layer.  NaN when the layer is missing or empty.
    """
    n = len(cells)
    if layer is None or layer.empty:
        return np.full(n, np.nan)

    centroids = [g for g in cells.geometry.centroid]
    layer_geoms = list(layer.geometry)
    chunk = math.ceil(n / cfg.n_jobs)
    tasks = [(layer_geoms, list(c)) for c in _chunked(centroids, chunk)]

    if cfg.n_jobs > 1 and len(tasks) > 1:
        with ProcessPoolExecutor(max_workers=cfg.n_jobs) as ex:
            results = list(ex.map(_distance_chunk_worker, tasks))
    else:
        results = [_distance_chunk_worker(t) for t in tasks]

    flat = [v for part in results for v in part]
    return np.asarray(flat, dtype=float)


# ---------------------------------------------------------------------------
# Aggregation helpers (overlay-based)
# ---------------------------------------------------------------------------
def _overlay_area(cells: gpd.GeoDataFrame, layer: gpd.GeoDataFrame) -> pd.Series:
    """Total intersection area (m2) per Grid_ID."""
    layer = layer[layer.geometry.geom_type.isin(["Polygon", "MultiPolygon"])]
    if layer.empty:
        return pd.Series(dtype=float)
    inter = gpd.overlay(cells[["Grid_ID", "geometry"]],
                        layer[["geometry"]], how="intersection")
    if inter.empty:
        return pd.Series(dtype=float)
    inter["_area"] = inter.geometry.area
    return inter.groupby("Grid_ID")["_area"].sum()


def _overlay_length(cells: gpd.GeoDataFrame, layer: gpd.GeoDataFrame) -> pd.Series:
    """Total intersection length (m) per Grid_ID (for line layers)."""
    layer = layer[layer.geometry.geom_type.isin(["LineString", "MultiLineString"])]
    if layer.empty:
        return pd.Series(dtype=float)
    # keep_geom_type=False: intersecting polygon cells with road lines yields
    # line pieces, which the default would silently drop.
    inter = gpd.overlay(cells[["Grid_ID", "geometry"]],
                        layer[["geometry"]], how="intersection",
                        keep_geom_type=False)
    if inter.empty:
        return pd.Series(dtype=float)
    inter["_len"] = inter.geometry.length
    return inter.groupby("Grid_ID")["_len"].sum()


def _count_by_cell(cells: gpd.GeoDataFrame, layer: gpd.GeoDataFrame) -> pd.Series:
    """Number of layer features intersecting each cell."""
    join = gpd.sjoin(cells[["Grid_ID", "geometry"]], layer[["geometry"]],
                     how="inner", predicate="intersects")
    return join.groupby("Grid_ID").size()


def _safe_min(s1: pd.Series, s2: pd.Series) -> pd.Series:
    """Element-wise min that tolerates NaN in either series."""
    both = pd.concat([s1, s2], axis=1)
    return both.min(axis=1, skipna=False).where(both.notna().any(axis=1))


# ---------------------------------------------------------------------------
# Per-feature-group builders
# ---------------------------------------------------------------------------
def _building_features(cells: gpd.GeoDataFrame,
                       buildings: Optional[gpd.GeoDataFrame],
                       cell_area_km2: pd.Series) -> pd.DataFrame:
    out = pd.DataFrame(index=cells["Grid_ID"])
    out["BuildingCount"] = 0.0
    out["BuildingCoveragePct"] = 0.0
    out["AvgBuildingFootprint"] = np.nan
    if buildings is None or buildings.empty:
        return out

    polys = buildings[buildings.geometry.geom_type.isin(["Polygon", "MultiPolygon"])]
    join = gpd.sjoin(cells[["Grid_ID", "geometry"]],
                     polys[["geometry"]], how="inner", predicate="intersects")
    counts = join.groupby("Grid_ID").size()
    if not polys.empty:
        polys = polys.copy()
        polys["_footprint"] = polys.geometry.area
        join2 = gpd.sjoin(cells[["Grid_ID", "geometry"]],
                          polys[["_footprint", "geometry"]],
                          how="inner", predicate="intersects")
        avg = join2.groupby("Grid_ID")["_footprint"].mean()

    out["BuildingCount"] = counts.reindex(out.index).fillna(0.0)
    avg = avg.reindex(out.index) if not polys.empty else pd.Series(np.nan, index=out.index)
    # cells without any building have no footprint -> 0 (keeps the column
    # instead of leaving >50%% missing and triggering the column drop)
    out["AvgBuildingFootprint"] = avg.where(out["BuildingCount"] > 0, 0.0)

    if not polys.empty:
        cov = _overlay_area(cells, polys)
        out["BuildingCoveragePct"] = (
            cov.reindex(out.index).fillna(0.0) / (cell_area_km2 * 1e6) * 100.0
        )
    out["BuildingDensity"] = out["BuildingCount"] / cell_area_km2
    return out


def _road_features(cells: gpd.GeoDataFrame,
                   roads: Optional[gpd.GeoDataFrame],
                   cfg: Config,
                   cell_area_km2: pd.Series) -> pd.DataFrame:
    out = pd.DataFrame(index=cells["Grid_ID"])
    out["RoadLength"] = 0.0
    out["RoadIntersectionCount"] = 0.0
    out["DistToMajorRoad"] = np.nan
    if roads is None or roads.empty:
        out["RoadDensity"] = 0.0
        out["RoadIntersectionDensity"] = 0.0
        return out

    lines = roads[roads.geometry.geom_type == "LineString"].copy()
    motor_lines = lines
    if "highway" in lines.columns:
        motor_lines = lines[lines["highway"].astype(str).str.strip().isin(
            cfg.vector.road_highway_types)]
    if not motor_lines.empty:
        lengths = _overlay_length(cells, motor_lines)
        out["RoadLength"] = lengths.reindex(out.index).fillna(0.0)

    # --- intersections of the motorised road network ---------------------
    # The noded road network (unary_union) splits every road at crossings and
    # junctions; a junction is a vertex shared by >= 3 line segments.
    if not motor_lines.empty:
        try:
            union = unary_union(motor_lines.geometry.to_list())
            segs = union.geoms if hasattr(union, "geoms") else [union]
            vertex_counts: Counter = Counter()
            for seg in segs:
                for x, y in seg.coords:
                    vertex_counts[(round(float(x), 3), round(float(y), 3))] += 1
            junction_pts = [
                Point(xy) for xy, n in vertex_counts.items() if n >= 3
            ]
            if junction_pts:
                pts_gdf = gpd.GeoDataFrame(geometry=junction_pts,
                                           crs=cfg.grid.target_epsg)
                counts = _count_by_cell(cells, pts_gdf)
                out["RoadIntersectionCount"] = counts.reindex(out.index).fillna(0.0)
        except Exception as exc:  # noqa: BLE001 - intersection is best-effort
            logger.warning("Road intersection extraction failed: %s", exc)

    # --- distance to the nearest major / arterial road -------------------
    if "highway" in motor_lines.columns:
        major = motor_lines[motor_lines["highway"].astype(str).str.strip().isin(
            cfg.vector.major_road_types)]
    else:
        major = motor_lines
    if not major.empty:
        out["DistToMajorRoad"] = nearest_distances(cells, major, cfg)

    out["RoadDensity"] = out["RoadLength"] / cell_area_km2
    out["RoadIntersectionDensity"] = out["RoadIntersectionCount"] / cell_area_km2
    return out


def _tree_features(cells: gpd.GeoDataFrame,
                   trees: Optional[gpd.GeoDataFrame],
                   cell_area_km2: pd.Series) -> pd.DataFrame:
    out = pd.DataFrame(index=cells["Grid_ID"])
    out["TreeCount"] = 0.0
    if trees is not None and not trees.empty:
        counts = _count_by_cell(cells, trees)
        out["TreeCount"] = counts.reindex(out.index).fillna(0.0)
    out["TreeDensity"] = out["TreeCount"] / cell_area_km2
    return out


def _green_space_features(cells: gpd.GeoDataFrame,
                          parks: Optional[gpd.GeoDataFrame],
                          green_extra: Optional[gpd.GeoDataFrame],
                          cell_area_km2: pd.Series) -> pd.DataFrame:
    out = pd.DataFrame(index=cells["Grid_ID"])
    out["GreenSpacePct"] = 0.0
    greens: List[gpd.GeoDataFrame] = []
    for layer in (parks, green_extra):
        if layer is not None and not layer.empty:
            polys = layer[layer.geometry.geom_type.isin(["Polygon", "MultiPolygon"])]
            if not polys.empty:
                greens.append(polys[["geometry"]])
    if greens:
        green = pd.concat(greens, ignore_index=True)
        area = _overlay_area(cells, green)
        out["GreenSpacePct"] = (
            area.reindex(out.index).fillna(0.0) / (cell_area_km2 * 1e6) * 100.0
        )
    return out


def _landuse_features(cells: gpd.GeoDataFrame,
                      landuse: Optional[gpd.GeoDataFrame],
                      cfg: Config,
                      cell_area_km2: pd.Series) -> pd.DataFrame:
    classes = list(cfg.vector.landuse_groups.keys()) + ["Other"]
    out = pd.DataFrame(index=cells["Grid_ID"])
    for c in classes:
        out[f"LandUse_{c}Pct"] = 0.0
    if landuse is None or landuse.empty:
        return out

    polys = landuse[landuse.geometry.geom_type.isin(["Polygon", "MultiPolygon"])]
    if polys.empty:
        return out
    polys = polys.copy()

    def coarse(v):
        v = str(v).strip()
        for cls, vals in cfg.vector.landuse_groups.items():
            if v in vals:
                return cls
        return "Other"

    polys["_class"] = polys["landuse"].map(coarse) if "landuse" in polys.columns else "Other"

    inter = gpd.overlay(cells[["Grid_ID", "geometry"]],
                        polys[["_class", "geometry"]], how="intersection")
    if inter.empty:
        return out
    inter["_area"] = inter.geometry.area
    grouped = inter.groupby(["Grid_ID", "_class"])["_area"].sum().unstack(fill_value=0.0)
    cell_area = cell_area_km2 * 1e6
    for c in classes:
        col = grouped[c] if c in grouped.columns else pd.Series(0.0, index=grouped.index)
        out[f"LandUse_{c}Pct"] = col.reindex(out.index).fillna(0.0) / cell_area * 100.0
    return out


def _amenity_features(cells: gpd.GeoDataFrame,
                      layer: Optional[gpd.GeoDataFrame],
                      cfg: Config,
                      cell_area_km2: pd.Series,
                      name: str) -> pd.DataFrame:
    """Count / density + nearest distance for a point-ish amenity layer."""
    out = pd.DataFrame(index=cells["Grid_ID"])
    out[f"{name}Count"] = 0.0
    out[f"DistTo{name}"] = np.nan
    if layer is not None and not layer.empty:
        counts = _count_by_cell(cells, layer)
        out[f"{name}Count"] = counts.reindex(out.index).fillna(0.0)
        out[f"DistTo{name}"] = nearest_distances(cells, layer, cfg)
    out[f"{name}Density"] = out[f"{name}Count"] / cell_area_km2
    return out


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------
def compute_vector_features(cells: gpd.GeoDataFrame,
                            cfg: Config) -> pd.DataFrame:
    """
    Compute every STEP-2 vector feature for the grid.

    Returns a DataFrame indexed by Grid_ID with one column per feature.
    """
    layers = resolve_layers(cfg)
    area_km2 = cells.set_index("Grid_ID")["Area"] / 1e6

    out = pd.DataFrame(index=cells["Grid_ID"])

    buildings = layers["buildings"]
    out = out.join(_building_features(cells, buildings, area_km2))

    roads = layers["roads"]
    out = out.join(_road_features(cells, roads, cfg, area_km2))

    trees = layers["trees"]
    out = out.join(_tree_features(cells, trees, area_km2))

    parks = layers["parks"]
    green_extra = layers["green_extra"]
    out = out.join(_green_space_features(cells, parks, green_extra, area_km2))

    landuse = layers["landuse"]
    out = out.join(_landuse_features(cells, landuse, cfg, area_km2))

    # Distances to cooling / heat-source landmarks --------------------------
    water = layers["water"]
    out["DistToPark"] = nearest_distances(cells, parks, cfg)
    out["DistToWater"] = nearest_distances(cells, water, cfg)
    out["DistToHospital"] = nearest_distances(cells, layers["hospitals"], cfg)
    out["DistToSchool"] = nearest_distances(cells, layers["schools"], cfg)

    # Bus stops (count + density + distance) -------------------------------
    out = out.join(_amenity_features(cells, layers["bus_stops"], cfg, area_km2,
                                     "BusStop"))

    # Hospital / school counts ----------------------------------------------
    for name, layer in (("Hospital", layers["hospitals"]),
                        ("School", layers["schools"])):
        out[f"{name}Count"] = (
            _count_by_cell(cells, layer).reindex(out.index).fillna(0.0)
            if layer is not None and not layer.empty else 0.0
        )

    # Railways are optional - a length column when the layer exists ---------
    railways = layers["railways"]
    if railways is not None and not railways.empty:
        rail_lines = railways[railways.geometry.geom_type == "LineString"]
        if not rail_lines.empty:
            length = _overlay_length(cells, rail_lines)
            out["RailwayLength"] = length.reindex(out.index).fillna(0.0)
            out["RailwayDensity"] = out["RailwayLength"] / area_km2
        else:
            logger.info("Railway layer present but has no line geometries - skipped")

    out = out.reindex(index=cells["Grid_ID"])
    logger.info("Vector features computed: %d rows x %d columns",
                len(out), out.shape[1])
    return out
