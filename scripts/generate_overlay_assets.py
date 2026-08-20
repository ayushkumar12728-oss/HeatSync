#!/usr/bin/env python3
"""
Generate browser-ready assets for the 3D city map
==================================================
Reads the real pipeline outputs on disk and produces the lightweight, browser
safe representations the MapLibre frontend renders. Nothing is invented: every
asset is a faithful rendering of the actual GeoTIFF / GeoJSON artifacts.

Outputs (written into ``frontend/public/`` so Vite serves them directly):

* ``overlays/*.png``  — full-city coloured renderings of each thematic raster
  (LST, predicted LST, NDVI, green cover, vegetation density, land cover, AQI
  + pollutants, elevation, slope, aspect, hillshade, heat classes) plus
  ``overlays/overlays.json`` with WGS84 bounds + legend metadata.
* ``terrain/{z}/{x}/{y}.png`` — terrarium-encoded raster-DEM tiles for
  MapLibre ``setTerrain`` (real DEM, no vertical exaggeration).
* ``3d-layers/web_3d_trees.geojson`` — real OSM tree points + tree rows +
  wood/scrub features as point records (clustered client-side).

Run:  python scripts/generate_overlay_assets.py
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np
import rasterio
from rasterio.transform import array_bounds, from_bounds
from rasterio.warp import Resampling, reproject

ROOT = Path(__file__).resolve().parent.parent
PROCESSED = ROOT / "data" / "processed"
PREDICTIONS = ROOT / "data" / "predictions"
PUBLIC = ROOT / "frontend" / "public"
OVERLAY_DIR = PUBLIC / "overlays"
TERRAIN_DIR = PUBLIC / "terrain"
OSM_DIR = ROOT / "data" / "raw" / "osm" / "layers"

MAX_PIXELS = 2400  # longest side of an overlay PNG (browser-safe size)

# --------------------------------------------------------------------------- #
# Colormaps — every colour below mirrors gis-engine/process_*.py / config.py
# --------------------------------------------------------------------------- #
HEAT_CLASS_COLORS = ["#2166ac", "#67a9cf", "#fdae61", "#f46d43", "#d73027", "#67001f"]
LANDCOVER_COLORS = ["#2c7bb6", "#1a9850", "#d7191c", "#fdae61"]  # Water, Veg, Built, Bare
VEG_DENSITY_COLORS = ["#d9f0a3", "#a6d96a", "#66bd63", "#1a9850", "#006837"]
GREEN_COVER_COLORS = ["#d9d9d9", "#1a9850"]
ASPECT_COLORS = ["#fbbf24", "#fb923c", "#f87171", "#e879f9",
                 "#a78bfa", "#818cf8", "#38bdf8", "#34d399"]


def _norm_color(hex_color: str) -> tuple[float, float, float]:
    hex_color = hex_color.lstrip("#")
    return tuple(int(hex_color[i:i + 2], 16) / 255.0 for i in (0, 2, 4))


def _listed_colormap(colors: list[str]):
    """Return a matplotlib ListedColormap + matching labels."""
    import matplotlib
    matplotlib.use("Agg")
    from matplotlib.colors import ListedColormap
    return ListedColormap([_norm_color(c) for c in colors])


def _linear_cmap(stops: list[tuple[float, str]]):
    """Build a LinearSegmentedColormap from (value, hex) stops."""
    import matplotlib
    matplotlib.use("Agg")
    from matplotlib.colors import LinearSegmentedColormap
    values = [s[0] for s in stops]
    colors = [_norm_color(s[1]) for s in stops]
    return LinearSegmentedColormap.from_list(
        "custom", list(zip(values, colors, strict=True)))


def _render(src_path: Path, cmap, vmin: float | None, vmax: float | None,
            out_name: str, metadata: dict) -> None:
    """Render a raster to a PNG overlay + record its WGS84 bounds."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib.colors import Normalize
    except ImportError:
        print("  ! matplotlib required", file=sys.stderr)
        return

    with rasterio.open(src_path) as src:
        data = src.read(1).astype(np.float64)
        if src.nodata is not None:
            data = np.where(data == src.nodata, np.nan, data)
        # bounds of the raster in its own CRS
        left, bottom, right, top = array_bounds(src.height, src.width, src.transform)

    bounds_wgs84 = _bounds_wgs84(src_path, left, bottom, right, top)

    norm = Normalize(vmin=vmin, vmax=vmax)
    cmap.set_bad(color="#000000", alpha=0.0)  # transparent nodata
    rgba = cmap(norm(data))
    rgba = np.where(np.isnan(data)[..., None], [0, 0, 0, 0], rgba)

    h, w = data.shape
    longest = max(h, w)
    if longest > MAX_PIXELS:
        scale = MAX_PIXELS / longest
        from PIL import Image
        img = Image.fromarray((rgba[:, :, :3] * 255).astype(np.uint8), "RGB")
        alpha = Image.fromarray((rgba[:, :, 3] * 255).astype(np.uint8), "L")
        img = img.resize((max(1, int(w * scale)), max(1, int(h * scale))),
                         Image.BILINEAR)
        alpha = alpha.resize((max(1, int(w * scale)), max(1, int(h * scale))),
                             Image.BILINEAR)
        img.putalpha(alpha)
        img.save(OVERLAY_DIR / f"{out_name}.png", optimize=True)
    else:
        plt.imsave(OVERLAY_DIR / f"{out_name}.png", rgba)
    plt.close("all")

    meta = {
        "key": out_name,
        "url": f"/overlays/{out_name}.png",
        "bounds_wgs84": bounds_wgs84,
        "vmin": vmin,
        "vmax": vmax,
        **metadata,
    }
    print(f"  + {out_name}.png  ({w}x{h})")
    _OVERLAYS[out_name] = meta


def _bounds_wgs84(src_path: Path, left: float, bottom: float, right: float,
                  top: float) -> list[list[float]]:
    """Raster corners in WGS84 as [SW, SE, NE, NW] for MapLibre image sources."""
    with rasterio.open(src_path) as src:
        crs = src.crs
    if crs is None or crs.to_epsg() == 4326:
        lng1, lng2, lat1, lat2 = left, right, bottom, top
    else:
        from pyproj import Transformer
        t = Transformer.from_crs(crs, "EPSG:4326", always_xy=True)
        lng1, lat1 = t.transform(left, bottom)
        lng2, lat2 = t.transform(right, top)
    return [[lng1, lat1], [lng2, lat1], [lng2, lat2], [lng1, lat2]]


_OVERLAYS: dict[str, dict] = {}


def _stats(path: Path) -> tuple[float, float]:
    with rasterio.open(path) as src:
        data = src.read(1)
        finite = data[np.isfinite(data)]
    if finite.size == 0:
        return 0.0, 1.0
    return float(np.nanpercentile(finite, 2)), float(np.nanpercentile(finite, 98))


# --------------------------------------------------------------------------- #
# Overlay generation
# --------------------------------------------------------------------------- #
def generate_overlays() -> None:
    OVERLAY_DIR.mkdir(parents=True, exist_ok=True)
    print("== Overlays ==")

    # --- Heat: observed + predicted LST ---------------------------------- #
    lst = PROCESSED / "lst" / "LST.tif"
    if lst.exists():
        lo, hi = _stats(lst)
        _render(lst, _linear_cmap([(0, "#2c7bb6"), (0.5, "#ffffbf"), (1, "#d7191c")]),
                lo, hi, "lst", {
                    "title": "Land Surface Temperature (observed)",
                    "unit": "°C", "group": "HEAT",
                    "source": "Landsat 8/9 Collection-2 Level-2 (ST_B10), 30 m",
                    "type": "continuous",
                })
    pred = PREDICTIONS / "Predicted_LST.tif"
    if pred.exists():
        lo, hi = _stats(pred)
        _render(pred, _linear_cmap([(0, "#2c7bb6"), (0.5, "#ffffbf"), (1, "#d7191c")]),
                lo, hi, "predicted_lst", {
                    "title": "Predicted LST (XGBoost)",
                    "unit": "°C", "group": "HEAT",
                    "source": "XGBoost model prediction raster (data/predictions)",
                    "type": "continuous",
                })

    # --- Heat classes ------------------------------------------------------ #
    hc = PROCESSED / "heatmap" / "heat_classes.tif"
    if hc.exists():
        _render(hc, _listed_colormap(HEAT_CLASS_COLORS), 1, 6, "heat_classes", {
            "title": "Heat Classification", "unit": "class", "group": "HEAT",
            "source": "Landsat LST, fixed breaks 20/25/30/35/40 °C",
            "type": "categorical",
            "stops": [{"color": c, "label": lab}
                      for c, lab in zip(HEAT_CLASS_COLORS,
                                        ["Very Cool", "Cool", "Moderate", "Warm",
                                         "Hot", "Very Hot"], strict=True)],
        })

    # --- Vegetation -------------------------------------------------------- #
    ndvi = PROCESSED / "ndvi" / "ndvi.tif"
    if ndvi.exists():
        _render(ndvi, _linear_cmap([(0, "#d73027"), (0.45, "#fee08b"),
                                    (0.8, "#a6d96a"), (1, "#1a9850")]),
                -0.5, 1.0, "ndvi", {
                    "title": "NDVI", "unit": "index (-1..1)", "group": "VEGETATION",
                    "source": "Sentinel-2 Level-2A, 10 m", "type": "continuous",
                })
    gc = PROCESSED / "greencover" / "green_cover.tif"
    if gc.exists():
        _render(gc, _listed_colormap(GREEN_COVER_COLORS), 0, 1, "green_cover", {
            "title": "Green Cover", "unit": "0/1", "group": "VEGETATION",
            "source": "Sentinel-2 NDVI > 0.30, 10 m", "type": "categorical",
            "stops": [{"color": "#d9d9d9", "label": "Non-vegetation"},
                      {"color": "#1a9850", "label": "Vegetation"}],
        })
    vd = PROCESSED / "vegetation" / "vegetation_density.tif"
    if vd.exists():
        _render(vd, _listed_colormap(VEG_DENSITY_COLORS), 1, 5, "vegetation_density", {
            "title": "Vegetation Density", "unit": "class", "group": "VEGETATION",
            "source": "Sentinel-2 NDVI classes, 10 m", "type": "categorical",
            "stops": [{"color": c, "label": lab} for c, lab in zip(
                VEG_DENSITY_COLORS,
                ["Very Low", "Low", "Moderate", "High", "Very High"], strict=True)],
        })

    # --- Land cover --------------------------------------------------------- #
    lc = PROCESSED / "landcover" / "landcover.tif"
    if lc.exists():
        _render(lc, _listed_colormap(LANDCOVER_COLORS), 1, 4, "landcover", {
            "title": "Land Cover", "unit": "class", "group": "LAND COVER",
            "source": "Sentinel-2 rule-based (NDVI), 10 m", "type": "categorical",
            "stops": [{"color": c, "label": lab} for c, lab in zip(
                LANDCOVER_COLORS, ["Water", "Vegetation", "Built-up", "Bare Land"],
                strict=True)],
        })

    # --- Air quality (AQI + pollutants) ------------------------------------ #
    aqi_dir = PROCESSED / "aqi" / "rasters"
    aqi_cmap = _linear_cmap([(0, "#16a34a"), (0.5, "#eab308"), (1, "#dc2626")])
    aqi_sources = {
        "AQI": ("aqi", "Air Quality Index"),
        "PM25": ("pm25", "PM2.5 (µg/m³)"),
        "PM10": ("pm10", "PM10 (µg/m³)"),
        "NO2": ("no2", "NO₂ (µg/m³)"),
        "SO2": ("so2", "SO₂ (µg/m³)"),
        "O3": ("o3", "O₃ (µg/m³)"),
        "CO": ("co", "CO (mg/m³)"),
    }
    for fname, (key, title) in aqi_sources.items():
        path = aqi_dir / f"{fname}.tif"
        if path.exists():
            lo, hi = _stats(path)
            _render(path, aqi_cmap, lo, hi, key, {
                "title": title, "unit": "", "group": "AIR QUALITY",
                "source": "CPCB / OpenAQ / Sentinel-5P interpolation, 1 km",
                "type": "continuous",
            })

    # --- Terrain ------------------------------------------------------------- #
    elev = PROCESSED / "elevation" / "Elevation.tif"
    if elev.exists():
        lo, hi = _stats(elev)
        _render(elev, _linear_cmap([(0, "#237e63"), (0.5, "#f6e9b8"), (1, "#8c510a")]),
                lo, hi, "elevation", {
                    "title": "Elevation (DEM)", "unit": "m", "group": "TERRAIN",
                    "source": "Copernicus DEM GLO-30 / SRTM, 30 m", "type": "continuous",
                })
    slope = PROCESSED / "slope" / "Slope.tif"
    if slope.exists():
        lo, hi = _stats(slope)
        _render(slope, _linear_cmap([(0, "#f7fcfd"), (0.6, "#c2e699"), (1, "#4d004b")]),
                lo, hi, "slope", {
                    "title": "Slope", "unit": "°", "group": "TERRAIN",
                    "source": "DEM derivative (Horn 1981), 30 m", "type": "continuous",
                })
    aspect = PROCESSED / "aspect" / "Aspect.tif"
    if aspect.exists():
        _render(aspect, _listed_colormap(ASPECT_COLORS), 0, 360, "aspect", {
            "title": "Aspect", "unit": "°", "group": "TERRAIN",
            "source": "DEM derivative, 30 m", "type": "categorical",
        })
    hill = PROCESSED / "hillshade" / "Hillshade.tif"
    if hill.exists():
        _render(hill, _linear_cmap([(0, "#000000"), (1, "#ffffff")]),
                0, 255, "hillshade", {
                    "title": "Hillshade", "unit": "illumination", "group": "TERRAIN",
                    "source": "DEM derivative, 30 m", "type": "continuous",
                })

    with open(OVERLAY_DIR / "overlays.json", "w", encoding="utf-8") as fh:
        json.dump({"count": len(_OVERLAYS), "overlays": _OVERLAYS}, fh, indent=2)
    print(f"  -> overlays.json ({len(_OVERLAYS)} overlays)")


# --------------------------------------------------------------------------- #
# Terrain tiles (terrarium-encoded raster-dem, real DEM)
# --------------------------------------------------------------------------- #
WEB_MERCATOR_ORIGIN_X = -20037508.342789244
WEB_MERCATOR_ORIGIN_Y = 20037508.342789244
WEB_MERCATOR_SPAN = 2 * abs(WEB_MERCATOR_ORIGIN_X)


def _tile_bounds_3857(z: int, x: int, y: int) -> tuple[float, float, float, float]:
    size = WEB_MERCATOR_SPAN / (2 ** z)
    minx = WEB_MERCATOR_ORIGIN_X + x * size
    maxx = WEB_MERCATOR_ORIGIN_X + (x + 1) * size
    maxy = WEB_MERCATOR_ORIGIN_Y - y * size
    miny = WEB_MERCATOR_ORIGIN_Y - (y + 1) * size
    return minx, miny, maxx, maxy


def _lon_to_tile_x(lng: float, z: int) -> float:
    return (lng + 180.0) / 360.0 * (2 ** z)


def _lat_to_tile_y(lat: float, z: int) -> float:
    lat_rad = math.radians(lat)
    return (1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * (2 ** z)


def _encode_terrarium(elev_m: float) -> tuple[int, int, int]:
    e = elev_m + 32768.0
    if e < 0:
        return 0, 0, 0
    r = int(e) // 256
    g = int(e) % 256
    b = int((e - int(e)) * 256.0) % 256
    return r, g, b


def generate_terrain(dem: Path, max_zoom: int = 14) -> None:
    print("== Terrain tiles ==")
    if not dem.exists():
        print("  ! DEM not found:", dem)
        return
    with rasterio.open(dem) as src:
        src_crs = src.crs
        src_transform = src.transform
        src_data = src.read(1).astype(np.float64)
        src_nodata = src.nodata
        height, width = src_data.shape
        left, bottom, right, top = array_bounds(height, width, src_transform)
        if src_nodata is not None:
            src_data = np.where(src_data == src_nodata, np.nan, src_data)
        else:
            src_data = np.where(np.isfinite(src_data), src_data, np.nan)

    # project the DEM corners into web mercator to find the tile range
    from pyproj import Transformer
    t = Transformer.from_crs(src_crs, "EPSG:3857", always_xy=True)
    mx1, my1 = t.transform(left, bottom)
    mx2, my2 = t.transform(right, top)
    minx_3857, maxx_3857 = min(mx1, mx2), max(mx1, mx2)
    miny_3857, maxy_3857 = min(my1, my2), max(my1, my2)

    total = 0
    for z in range(0, max_zoom + 1):
        x_min = math.floor(_lon_to_tile_x(max(left, -180.0), z))
        x_max = math.floor(_lon_to_tile_x(min(right, 180.0), z))
        # y from the projected bounds (more robust than the lon/lat formula)
        y_min = math.floor((WEB_MERCATOR_ORIGIN_Y - maxy_3857)
                           / (WEB_MERCATOR_SPAN / (2 ** z)))
        y_max = math.floor((WEB_MERCATOR_ORIGIN_Y - miny_3857)
                           / (WEB_MERCATOR_SPAN / (2 ** z)))
        for x in range(x_min, x_max + 1):
            for y in range(y_min, y_max + 1):
                tb = _tile_bounds_3857(z, x, y)
                if (tb[2] < minx_3857 or tb[0] > maxx_3857
                        or tb[3] < miny_3857 or tb[1] > maxy_3857):
                    continue
                tile = _render_dem_tile(src_data, src_transform, src_crs,
                                        tb, 256)
                out = TERRAIN_DIR / str(z) / str(x)
                out.mkdir(parents=True, exist_ok=True)
                with rasterio.open(
                        out / f"{y}.png", "w", driver="PNG",
                        width=256, height=256, count=3, dtype="uint8") as dst:
                    dst.write(tile)
                total += 1
    print(f"  -> {total} terrain tiles written to {TERRAIN_DIR}")


def _render_dem_tile(src_data, src_transform, src_crs, tile_bounds_3857,
                     size: int) -> np.ndarray:
    """Reproject the DEM window into one 256px tile and encode terrarium RGB."""
    out = np.zeros((size, size), dtype=np.float64)
    dst_transform = from_bounds(*tile_bounds_3857, size, size)
    reproject(
        src_data,
        out,
        src_transform=src_transform,
        src_crs=src_crs,
        src_nodata=np.nan,
        dst_transform=dst_transform,
        dst_crs="EPSG:3857",
        dst_nodata=np.nan,
        resampling=Resampling.bilinear,
    )
    rgb = np.zeros((3, size, size), dtype=np.uint8)
    for i in range(size):
        for j in range(size):
            elev = out[j, i]
            if np.isnan(elev):
                rgb[:, j, i] = (0, 0, 0)
            else:
                rgb[:, j, i] = _encode_terrarium(float(elev))
    return rgb


# --------------------------------------------------------------------------- #
# Trees layer (real OSM tree records, clustered client-side)
# --------------------------------------------------------------------------- #
def generate_trees() -> None:
    print("== Trees layer ==")
    features: list[dict] = []

    def add_point(lng: float, lat: float, kind: str, source_file: str) -> None:
        features.append({
            "type": "Feature",
            "properties": {"kind": kind, "source": "OSM", "source_file": source_file},
            "geometry": {"type": "Point", "coordinates": [round(lng, 6), round(lat, 6)]},
        })

    trees_path = OSM_DIR / "trees.geojson"
    if trees_path.exists():
        with open(trees_path, encoding="utf-8") as fh:
            fc = json.load(fh)
        for f in fc.get("features", []):
            geom = f.get("geometry") or {}
            if geom.get("type") == "Point":
                lng, lat = geom["coordinates"]
                add_point(lng, lat, "tree", "trees.geojson")

    rows_path = OSM_DIR / "tree_rows.geojson"
    if rows_path.exists():
        with open(rows_path, encoding="utf-8") as fh:
            fc = json.load(fh)
        for f in fc.get("features", []):
            geom = f.get("geometry") or {}
            if geom.get("type") != "LineString":
                continue
            coords = geom["coordinates"]
            if len(coords) < 2:
                continue
            # sample every ~40 m along the real OSM tree-row geometry
            total = sum(
                _haversine(coords[i][1], coords[i][0],
                           coords[i + 1][1], coords[i + 1][0])
                for i in range(len(coords) - 1))
            n = max(2, int(total / 40.0))
            for k in range(n):
                t = k / max(1, n - 1)
                idx = t * (len(coords) - 1)
                i0 = int(idx)
                frac = idx - i0
                if i0 >= len(coords) - 1:
                    i0 = len(coords) - 2
                    frac = 1.0
                lng = coords[i0][0] + (coords[i0 + 1][0] - coords[i0][0]) * frac
                lat = coords[i0][1] + (coords[i0 + 1][1] - coords[i0][1]) * frac
                add_point(lng, lat, "tree_row", "tree_rows.geojson")

    # natural wood / scrub / tree polygons -> centroid points
    natural_path = OSM_DIR / "all_natural.geojson"
    if natural_path.exists():
        with open(natural_path, encoding="utf-8") as fh:
            fc = json.load(fh)
        for f in fc.get("features", []):
            natural = str((f.get("properties") or {}).get("natural", "")).lower()
            if natural not in ("wood", "scrub", "tree"):
                continue
            geom = f.get("geometry") or {}
            coords = _flatten_coords(geom)
            if not coords:
                continue
            lng = sum(c[0] for c in coords) / len(coords)
            lat = sum(c[1] for c in coords) / len(coords)
            add_point(lng, lat, f"natural_{natural}", "all_natural.geojson")

    # Written to the OSM layer catalogue (served by the backend, consistent
    # with the other web_3d_* layers) AND to the frontend public fallback.
    fc = {"type": "FeatureCollection",
          "note": "Real OSM tree records (points, tree rows sampled at "
                  "40 m, wood/scrub centroids). No fabricated trees.",
          "features": features}
    for out in (OSM_DIR / "web_3d_trees.geojson",
                PUBLIC / "3d-layers" / "web_3d_trees.geojson"):
        out.parent.mkdir(parents=True, exist_ok=True)
        with open(out, "w", encoding="utf-8") as fh:
            json.dump(fc, fh)
    print(f"  -> web_3d_trees.geojson ({len(features)} records)")


def _flatten_coords(geom: dict) -> list[list[float]]:
    out: list[list[float]] = []

    def walk(value) -> None:
        if (isinstance(value, list) and len(value) >= 2
                and isinstance(value[0], (int, float))
                and isinstance(value[1], (int, float))):
            out.append([float(value[0]), float(value[1])])
            return
        if isinstance(value, list):
            for item in value:
                walk(item)

    walk(geom.get("coordinates"))
    return out


def _haversine(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    r = 6_371_000.0
    a = (math.sin(math.radians(lat2 - lat1) / 2) ** 2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2))
         * math.sin(math.radians(lng2 - lng1) / 2) ** 2)
    return 2 * r * math.asin(min(1.0, math.sqrt(a)))


def main() -> None:
    generate_overlays()
    generate_trees()
    generate_terrain(PROCESSED / "dem" / "dem_clipped.tif", max_zoom=14)
    print("Done.")


if __name__ == "__main__":
    main()
