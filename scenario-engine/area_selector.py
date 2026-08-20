"""
Area-Based Cell Selector
========================
Provides spatial cell selection for scenario interventions.

Supports four selection modes:
1. Draw polygon - user defines an arbitrary polygon
2. Select neighborhood - select from predefined neighborhoods
3. Select radius - circular area around a point
4. Select map cells - direct cell selection

This module implements the physical validity requirements:
- Interventions are applied ONLY to selected cells
- Cells outside the intervention area remain unchanged
- Area statistics are reported (intervention area km², affected cells, unaffected cells)
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd
from shapely.geometry import Point, Polygon, mapping, shape

log = logging.getLogger("scenario_engine.area_selector")

PROJECT_ROOT = Path(__file__).resolve().parent.parent


@dataclass
class AreaSelection:
    """Result of an area selection operation."""
    mode: str  # polygon | neighborhood | radius | cells
    cell_indices: list[int] = field(default_factory=list)
    cell_count: int = 0
    total_cells: int = 0
    area_km2: float = 0.0
    description: str = ""
    affected_pct: float = 0.0

    def to_dict(self) -> dict:
        return {
            "mode": self.mode,
            "affected_cells": self.cell_count,
            "unaffected_cells": self.total_cells - self.cell_count,
            "total_cells": self.total_cells,
            "intervention_area_km2": round(self.area_km2, 4),
            "affected_pct": round(self.affected_pct, 2),
            "description": self.description,
        }


class AreaSelector:
    """Select grid cells based on spatial criteria."""

    def __init__(self, grid_geojson_path: str | Path | None = None):
        self._grid_geojson_path = grid_geojson_path or (
            PROJECT_ROOT / "data" / "feature_engineering" / "training_dataset.geojson"
        )
        self._grid_features: list[dict] | None = None
        self._centroids: dict[str, Point] | None = None
        self._grid_ids: list[str] | None = None

    def _load_grid(self) -> None:
        """Load the grid GeoJSON for spatial operations."""
        if self._grid_features is not None:
            return

        path = Path(self._grid_geojson_path)
        if not path.exists():
            log.warning("Grid GeoJSON not found: %s", path)
            self._grid_features = []
            self._centroids = {}
            self._grid_ids = []
            return

        with open(path, encoding="utf-8") as fh:
            gj = json.load(fh)

        self._grid_features = gj.get("features", [])
        self._centroids = {}
        self._grid_ids = []

        for feat in self._grid_features:
            props = feat.get("properties", {})
            gid = str(props.get("Grid_ID", ""))
            geom = feat.get("geometry")
            if not gid or not geom:
                continue

            try:
                shp = shape(geom)
                centroid = shp.centroid
                self._centroids[gid] = centroid
                self._grid_ids.append(gid)
            except Exception as exc:
                log.debug("Could not compute centroid for %s: %s", gid, exc)

        log.info(
            "Grid loaded: %d features, %d centroids",
            len(self._grid_features),
            len(self._centroids),
        )

    def get_total_cells(self) -> int:
        """Total number of grid cells."""
        self._load_grid()
        return len(self._grid_ids)

    def select_by_polygon(
        self, polygon_coords: list[list[float]], total_cells: int | None = None
    ) -> AreaSelection:
        """Select cells inside a user-drawn polygon.

        Args:
            polygon_coords: List of [lon, lat] pairs defining the polygon.
            total_cells: Total cells in the grid (for stats). If None, auto-detected.

        Returns:
            AreaSelection with affected cells.
        """
        self._load_grid()
        if total_cells is None:
            total_cells = self.get_total_cells()

        try:
            # Create polygon from coordinates
            exterior = [(coord[0], coord[1]) for coord in polygon_coords]
            poly = Polygon(exterior)

            if not poly.is_valid:
                poly = poly.buffer(0)

            selected = []
            for i, gid in enumerate(self._grid_ids):
                centroid = self._centroids.get(gid)
                if centroid and poly.contains(centroid):
                    selected.append(i)

            area_km2 = poly.area / 1e6  # approximate for lat/lon
            if len(selected) == 0 and len(polygon_coords) > 0:
                # Try with buffer if no cells found
                poly_buffered = poly.buffer(0.002)  # ~200m buffer
                for i, gid in enumerate(self._grid_ids):
                    centroid = self._centroids.get(gid)
                    if centroid and poly_buffered.contains(centroid):
                        selected.append(i)
                area_km2 = poly_buffered.area / 1e6

            result = AreaSelection(
                mode="polygon",
                cell_indices=selected,
                cell_count=len(selected),
                total_cells=total_cells,
                area_km2=area_km2,
                description=f"User-drawn polygon with {len(polygon_coords)} vertices",
            )
            result.affected_pct = (len(selected) / total_cells * 100) if total_cells > 0 else 0
            return result

        except Exception as exc:
            log.error("Polygon selection failed: %s", exc)
            return AreaSelection(
                mode="polygon",
                total_cells=total_cells,
                description=f"Polygon selection failed: {exc}",
            )

    def select_by_neighborhood(
        self, neighborhood_name: str, total_cells: int | None = None
    ) -> AreaSelection:
        """Select cells in a predefined neighborhood.

        Args:
            neighborhood_name: Name of the neighborhood.
            total_cells: Total cells in the grid.

        Returns:
            AreaSelection with affected cells.
        """
        self._load_grid()
        if total_cells is None:
            total_cells = self.get_total_cells()

        # Load neighborhood definitions if available
        neighborhoods_path = PROJECT_ROOT / "data" / "neighborhoods.geojson"
        if neighborhoods_path.exists():
            with open(neighborhoods_path, encoding="utf-8") as fh:
                nh_gj = json.load(fh)
            for feat in nh_gj.get("features", []):
                props = feat.get("properties", {})
                if props.get("name", "").lower() == neighborhood_name.lower():
                    nh_geom = shape(feat["geometry"])
                    selected = []
                    for i, gid in enumerate(self._grid_ids):
                        centroid = self._centroids.get(gid)
                        if centroid and nh_geom.contains(centroid):
                            selected.append(i)

                    area_km2 = nh_geom.area / 1e6
                    result = AreaSelection(
                        mode="neighborhood",
                        cell_indices=selected,
                        cell_count=len(selected),
                        total_cells=total_cells,
                        area_km2=area_km2,
                        description=f"Neighborhood: {neighborhood_name}",
                    )
                    result.affected_pct = (len(selected) / total_cells * 100) if total_cells > 0 else 0
                    return result

        return AreaSelection(
            mode="neighborhood",
            total_cells=total_cells,
            description=f"Neighborhood '{neighborhood_name}' not found",
        )

    def select_by_radius(
        self,
        center_lon: float,
        center_lat: float,
        radius_m: float,
        total_cells: int | None = None,
    ) -> AreaSelection:
        """Select cells within a radius of a center point.

        Args:
            center_lon: Center longitude.
            center_lat: Center latitude.
            radius_m: Radius in meters.
            total_cells: Total cells in the grid.

        Returns:
            AreaSelection with affected cells.
        """
        self._load_grid()
        if total_cells is None:
            total_cells = self.get_total_cells()

        try:
            center = Point(center_lon, center_lat)
            # Approximate radius in degrees (1 degree ~ 111km at equator)
            radius_deg = radius_m / 111000.0

            selected = []
            for i, gid in enumerate(self._grid_ids):
                centroid = self._centroids.get(gid)
                if centroid and center.distance(centroid) <= radius_deg:
                    selected.append(i)

            # Calculate area (approximate)
            area_km2 = np.pi * (radius_m / 1000.0) ** 2

            result = AreaSelection(
                mode="radius",
                cell_indices=selected,
                cell_count=len(selected),
                total_cells=total_cells,
                area_km2=area_km2,
                description=f"Radius {radius_m}m around ({center_lon}, {center_lat})",
            )
            result.affected_pct = (len(selected) / total_cells * 100) if total_cells > 0 else 0
            return result

        except Exception as exc:
            log.error("Radius selection failed: %s", exc)
            return AreaSelection(
                mode="radius",
                total_cells=total_cells,
                description=f"Radius selection failed: {exc}",
            )

    def select_by_cells(
        self, cell_ids: list[str], total_cells: int | None = None
    ) -> AreaSelection:
        """Select specific cells by their Grid_ID.

        Args:
            cell_ids: List of Grid_ID strings.
            total_cells: Total cells in the grid.

        Returns:
            AreaSelection with affected cells.
        """
        self._load_grid()
        if total_cells is None:
            total_cells = self.get_total_cells()

        selected_set = set(str(gid) for gid in cell_ids)
        selected = [
            i for i, gid in enumerate(self._grid_ids)
            if gid in selected_set
        ]

        # Estimate area (100m grid cells)
        area_km2 = len(selected) * 0.01  # 100m x 100m = 0.01 km²

        result = AreaSelection(
            mode="cells",
            cell_indices=selected,
            cell_count=len(selected),
            total_cells=total_cells,
            area_km2=area_km2,
            description=f"Direct selection of {len(cell_ids)} cells",
        )
        result.affected_pct = (len(selected) / total_cells * 100) if total_cells > 0 else 0
        return result


def create_area_mask(
    selection: AreaSelection, total_rows: int
) -> np.ndarray:
    """Create a boolean mask for the selected cells.

    Args:
        selection: AreaSelection with cell_indices.
        total_rows: Total rows in the feature matrix.

    Returns:
        Boolean mask of shape (total_rows,) where True = selected cell.
    """
    mask = np.zeros(total_rows, dtype=bool)
    valid_indices = [i for i in selection.cell_indices if i < total_rows]
    mask[valid_indices] = True
    return mask


def apply_area_intervention(
    X: pd.DataFrame,
    mask: np.ndarray,
    perturbations: dict[str, tuple],
    simulator,
) -> pd.DataFrame:
    """Apply perturbations only to masked cells.

    Args:
        X: Feature DataFrame (all cells).
        mask: Boolean mask where True = cells to perturb.
        perturbations: Feature perturbations.
        simulator: ScenarioSimulator instance for perturbation logic.

    Returns:
        New DataFrame with perturbations applied only to masked cells.
    """
    X_perturbed = X.copy()

    # Get the subset of cells to perturb
    X_subset = X.loc[mask].copy()

    if len(X_subset) == 0:
        log.warning("No cells to perturb - mask is all False")
        return X_perturbed

    # Apply perturbations to the subset
    X_subset_perturbed = simulator._perturb(X_subset, perturbations)

    # Replace only the masked cells
    X_perturbed.loc[mask] = X_subset_perturbed.values

    return X_perturbed


def validate_before_after(
    baseline: np.ndarray,
    scenario: np.ndarray,
    mask: np.ndarray,
    tolerance: float = 1e-5,
) -> dict:
    """Validate that outside-intervention cells remain unchanged.

    Args:
        baseline: Baseline predictions for all cells.
        scenario: Scenario predictions for all cells.
        mask: Boolean mask where True = intervention area.
        tolerance: Tolerance for floating-point comparison.

    Returns:
        Validation report.
    """
    outside_mask = ~mask
    inside_mask = mask

    # Cells outside intervention should be unchanged
    outside_baseline = baseline[outside_mask]
    outside_scenario = scenario[outside_mask]
    outside_diff = np.abs(outside_baseline - outside_scenario)
    unchanged_outside = np.sum(outside_diff < tolerance)
    total_outside = np.sum(outside_mask)

    # Cells inside intervention may differ
    inside_baseline = baseline[inside_mask]
    inside_scenario = scenario[inside_mask]
    inside_diff = np.abs(inside_baseline - inside_scenario)
    changed_inside = np.sum(inside_diff >= tolerance)
    total_inside = np.sum(inside_mask)

    # Overall statistics
    total_changed = np.sum(np.abs(baseline - scenario) >= tolerance)
    total_unchanged = np.sum(np.abs(baseline - scenario) < tolerance)

    report = {
        "validation_passed": unchanged_outside == total_outside,
        "affected_cells": int(total_inside),
        "changed_cells": int(total_changed),
        "unchanged_cells": int(total_unchanged),
        "outside_intervention": {
            "total": int(total_outside),
            "unchanged": int(unchanged_outside),
            "changed": int(total_outside - unchanged_outside),
            "all_unchanged": unchanged_outside == total_outside,
        },
        "inside_intervention": {
            "total": int(total_inside),
            "changed": int(changed_inside),
            "unchanged": int(total_inside - changed_inside),
        },
    }

    if unchanged_outside < total_outside:
        report["warning"] = (
            f"{total_outside - unchanged_outside} cells outside intervention area "
            f"were changed. This may indicate spatial spillover in the model."
        )

    return report
