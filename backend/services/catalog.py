"""
Data layer catalog
==================
Discovers every artefact the pipeline produced (rasters, vectors, CSVs, plots)
and exposes it as an API-addressable catalogue. Layer names are URL-safe slugs
derived from the file name; the service resolves a slug back to a file with
path-traversal protection.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from backend.config.settings import Settings

log = logging.getLogger("backend.catalog")

CONTENT_TYPES = {
    ".geojson": "application/geo+json",
    ".json": "application/json",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".csv": "text/csv",
    ".html": "text/html",
}

RASTER_CATEGORIES = {
    "ndvi": "vegetation",
    "greencover": "vegetation",
    "vegetation": "vegetation",
    "landcover": "classification",
    "lst": "thermal",
    "heatmap": "thermal",
    "elevation": "terrain",
    "slope": "terrain",
    "aspect": "terrain",
    "hillshade": "terrain",
    "contours": "terrain",
    "aqi": "air-quality",
    "previews": "preview",
}


@dataclass(frozen=True)
class Layer:
    """One catalogue entry pointing at a real file on disk."""

    name: str
    title: str
    type: str          # raster | vector | timeseries | table | plot | model
    category: str
    path: Path
    url: str

    def to_dict(self) -> dict:
        p = self.path
        return {
            "name": self.name,
            "title": self.title,
            "type": self.type,
            "category": self.category,
            "path": str(p),
            "url": self.url,
            "size_bytes": p.stat().st_size if p.exists() else None,
            "modified_at": p.stat().st_mtime if p.exists() else None,
        }


class DataCatalog:
    """Discovers and resolves pipeline artefacts."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self._layers: dict[str, Layer] | None = None

    # ------------------------------------------------------------------ #
    def _register(self, layers: dict[str, Layer], dirpath: Path,
                  filetype: str, category: str | None = None,
                  url_prefix: str = "/api/data/layers") -> None:
        """Register every file in a directory (recursively for rasters)."""
        if not dirpath.exists():
            return
        for p in sorted(dirpath.rglob("*")):
            if not p.is_file() or p.suffix.lower() not in CONTENT_TYPES:
                continue
            if p.name.startswith("."):
                continue
            slug = _slugify(p.stem)
            # avoid clobbering a more specific layer with a generic stem
            if slug in layers:
                slug = f"{slug}-{p.parent.name}"
            layers[slug] = Layer(
                name=slug,
                title=_title(p.stem),
                type=filetype,
                category=category or _category(p.parent.name),
                path=p,
                url=f"{url_prefix}/{slug}",
            )

    def _build(self) -> dict[str, Layer]:
        layers: dict[str, Layer] = {}
        s = self.settings

        # --- single well-known artefacts --------------------------------
        def add(layer: Layer) -> None:
            if layer.path.exists():
                layers[layer.name] = layer

        add(Layer("predicted-lst", "Predicted Land Surface Temperature (grid)",
                  "vector", "thermal", s.predicted_geojson,
                  "/api/data/layers/predicted-lst"))
        add(Layer("predicted-lst-raster", "Predicted Land Surface Temperature (raster)",
                  "raster", "thermal", s.predicted_tif,
                  "/api/data/layers/predicted-lst-raster"))
        add(Layer("predicted-lst-preview", "Predicted LST map preview",
                  "plot", "thermal", s.predicted_png,
                  "/api/data/layers/predicted-lst-preview"))
        add(Layer("training-grid", "Training grid (100 m cells, all features)",
                  "vector", "feature-engineering", s.dataset_geojson,
                  "/api/data/layers/training-grid"))
        add(Layer("boundary", "Study area boundary (Bhubaneswar)",
                  "vector", "boundary", s.boundary_geojson,
                  "/api/data/layers/boundary"))

        # --- directories -------------------------------------------------
        self._register(layers, s.data_dir / "processed" / "ndvi", "raster")
        self._register(layers, s.data_dir / "processed" / "greencover", "raster")
        self._register(layers, s.data_dir / "processed" / "vegetation", "raster")
        self._register(layers, s.data_dir / "processed" / "landcover", "raster")
        self._register(layers, s.data_dir / "processed" / "lst", "raster")
        self._register(layers, s.data_dir / "processed" / "heatmap", "raster")
        self._register(layers, s.data_dir / "processed" / "elevation", "raster")
        self._register(layers, s.data_dir / "processed" / "slope", "raster")
        self._register(layers, s.data_dir / "processed" / "aspect", "raster")
        self._register(layers, s.data_dir / "processed" / "hillshade", "raster")
        self._register(layers, s.data_dir / "processed" / "contours", "vector")
        self._register(layers, s.data_dir / "processed" / "aqi" / "rasters", "raster")
        self._register(layers, s.data_dir / "processed" / "aqi" / "plots", "plot")
        self._register(layers, s.data_dir / "processed" / "previews", "plot")
        self._register(layers, s.data_dir / "processed" / "weather", "timeseries")
        self._register(layers, s.osm_layers_dir, "vector", category="infrastructure")
        self._register(layers, s.outputs_dir / "plots" / "SHAP", "plot", category="explainability")
        self._register(layers, s.outputs_dir / "plots", "plot")

        return layers

    # ------------------------------------------------------------------ #
    @property
    def layers(self) -> dict[str, Layer]:
        if self._layers is None:
            self._layers = self._build()
            log.info("Catalogued %d data layers", len(self._layers))
        return self._layers

    def list_layers(self, type_filter: str | None = None,
                    category: str | None = None) -> list[dict]:
        out = [layer.to_dict() for layer in self.layers.values()]
        if type_filter:
            out = [d for d in out if d["type"] == type_filter]
        if category:
            out = [d for d in out if d["category"] == category]
        return out

    def get_layer(self, name: str) -> Layer | None:
        return self.layers.get(name)

    def categories(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for layer in self.layers.values():
            counts[layer.category] = counts.get(layer.category, 0) + 1
        return counts


def _slugify(stem: str) -> str:
    """URL-safe slug: lowercase, keep alnum/dash/underscore."""
    out = []
    for ch in stem.lower():
        out.append(ch if ch.isalnum() or ch in "-_" else "-")
    return "-".join("".join(out).split("-"))


def _title(stem: str) -> str:
    return stem.replace("_", " ").replace("-", " ").strip().title()


def _category(folder: str) -> str:
    return RASTER_CATEGORIES.get(folder.lower(), folder.lower() or "other")
