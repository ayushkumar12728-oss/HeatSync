#!/usr/bin/env python3
"""
Convert predicted_lst_grid.geojson from EPSG:32645 (UTM 45N) to EPSG:4326 (WGS84).

Reads the existing file, reprojects every coordinate, and writes it back.
Handles Polygon, MultiPolygon, and any nested coordinate arrays.
"""

import json
import sys
import time
from pathlib import Path

from pyproj import Transformer

INPUT = Path("frontend/public/3d-layers/predicted_lst_grid.geojson")
OUTPUT = INPUT  # overwrite in place

transformer = Transformer.from_crs("EPSG:32645", "EPSG:4326", always_xy=True)

def reproject_coords(coords):
    """Recursively reproject a GeoJSON coordinate array (any nesting depth)."""
    if not coords:
        return coords
    # Leaf: a single [x, y] pair
    if isinstance(coords[0], (int, float)):
        lon, lat = transformer.transform(coords[0], coords[1])
        return [round(lon, 6), round(lat, 6)]
    # Nested array
    return [reproject_coords(c) for c in coords]


def main():
    if not INPUT.exists():
        print(f"ERROR: {INPUT} not found", file=sys.stderr)
        sys.exit(1)

    print(f"Reading {INPUT} ({INPUT.stat().st_size / 1e6:.1f} MB) ...")
    t0 = time.time()
    with open(INPUT, encoding="utf-8") as f:
        geojson = json.load(f)
    print(f"  Loaded in {time.time() - t0:.1f}s")

    features = geojson.get("features", [])
    print(f"  Features: {len(features)}")

    t1 = time.time()
    converted = 0
    skipped = 0
    for feature in features:
        geom = feature.get("geometry")
        if geom is None:
            skipped += 1
            continue
        geom_type = geom.get("type", "")
        coords = geom.get("coordinates")
        if coords is None:
            skipped += 1
            continue

        geom["coordinates"] = reproject_coords(coords)
        converted += 1

    print(f"  Converted: {converted}, Skipped: {skipped}")
    print(f"  Reprojection took {time.time() - t1:.1f}s")

    # Verify a sample coordinate looks like WGS84
    if features:
        sample = features[0]["geometry"]["coordinates"][0][0]
        if isinstance(sample[0], list):
            sample = sample[0]
        print(f"  Sample coordinate (should be ~85.x, ~20.x): [{sample[0]}, {sample[1]}]")
        if abs(sample[0]) > 180 or abs(sample[1]) > 90:
            print("  WARNING: Coordinates still look like UTM — conversion may have failed!", file=sys.stderr)
            sys.exit(1)

    # Strip CRS metadata since we're now in WGS84
    geojson.pop("crs", None)
    geojson.pop("name", None)

    print(f"Writing {OUTPUT} ...")
    t2 = time.time()
    with open(OUTPUT, "w", encoding="utf-8") as f:
        json.dump(geojson, f, separators=(",", ":"))
    print(f"  Written in {time.time() - t2:.1f}s ({OUTPUT.stat().st_size / 1e6:.1f} MB)")
    print("Done.")


if __name__ == "__main__":
    main()
