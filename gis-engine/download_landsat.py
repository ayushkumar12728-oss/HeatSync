"""
STEP 2 & 3 - Landsat 8/9 Collection 2 Level-2 search and download
=================================================================
Searches Microsoft Planetary Computer (preferred) for the latest Landsat
8/9 scene with < 10% cloud cover covering the whole boundary, then downloads
the thermal band (ST_B10), the pixel-quality band (QA_PIXEL) and the MTL
metadata into ``data/raw/landsat/``.

Falls back to the public USGS LandsatLook STAC catalog. Downloads are
resumable and completed files are skipped on re-runs.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import geopandas as gpd
import numpy as np
import rasterio
import rioxarray  # noqa: F401  (registers the .rio accessor on xarray objects)

from config import Config
from utils import (
    PipelineError,
    atomic_write_geotiff,
    item_datetime_utc,
    load_boundary,
    read_json,
    read_stackstac_window,
    resumable_download,
    select_best_scene,
    sign_pc_assets,
    utm_epsg_for,
    write_json,
)

logger = logging.getLogger("sentinel.landsat.download")


@dataclass
class LandsatResult:
    """Everything the processing stage needs to know about the scene."""

    scene_id: str
    provider: str
    datetime: Optional[str]
    cloud_cover: Optional[float]
    crs_epsg: int
    resolution: int
    scale_mul: float
    scale_add: float
    bands: Dict[str, Path] = field(default_factory=dict)
    mtl_path: Optional[Path] = None
    metadata_path: Optional[Path] = None

    @classmethod
    def from_metadata(cls, meta: dict, cfg: Config) -> "LandsatResult":
        return cls(
            scene_id=meta.get("scene_id", "unknown"),
            provider=meta.get("provider", "unknown"),
            datetime=meta.get("datetime"),
            cloud_cover=meta.get("cloud_cover"),
            crs_epsg=int(meta.get("crs_epsg", 0) or 0),
            resolution=int(meta.get("resolution", cfg.landsat.resolution)),
            scale_mul=float(meta.get("scale_mul", cfg.landsat.scale_mul)),
            scale_add=float(meta.get("scale_add", cfg.landsat.scale_add)),
            bands={b: cfg.paths.raw_landsat / f"{b}.tif" for b in cfg.landsat.bands},
            mtl_path=cfg.paths.raw_landsat / "mtl.json",
            metadata_path=cfg.paths.raw_landsat / "metadata.json",
        )


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------
def search_landsat_pc(boundary: gpd.GeoDataFrame, cfg: Config) -> List[object]:
    """Search the Planetary Computer STAC catalog for Landsat C2 L2 scenes."""
    try:
        import planetary_computer
        import pystac_client
    except ImportError as e:
        raise PipelineError(
            "Missing packages for Planetary Computer search: "
            "pip install pystac-client planetary-computer stackstac"
        ) from e

    bbox = [float(v) for v in boundary.total_bounds]
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=cfg.landsat.lookback_days)

    catalog = pystac_client.Client.open(
        cfg.landsat.pc_stac_url, modifier=planetary_computer.sign_inplace
    )
    search = catalog.search(
        collections=[cfg.landsat.collection],
        bbox=bbox,
        datetime=f"{start.isoformat()}/{end.isoformat()}",
        query={"eo:cloud_cover": {"lt": cfg.landsat.max_cloud_cover}},
        max_items=cfg.landsat.max_items * 2,
    )
    items = list(search.items())
    logger.info(
        "Planetary Computer: %d Landsat candidate scene(s) with cloud cover < %.0f%%",
        len(items), cfg.landsat.max_cloud_cover,
    )
    return items


def search_usgs(boundary: gpd.GeoDataFrame, cfg: Config) -> List[object]:
    """Fallback search on the public USGS LandsatLook STAC catalog."""
    import pystac

    end = datetime.now(timezone.utc)
    start = end - timedelta(days=cfg.landsat.lookback_days)
    params = {
        "collections": cfg.landsat.collection,
        "bbox": ",".join(f"{v:.6f}" for v in boundary.total_bounds),
        "datetime": f"{start.isoformat()}/{end.isoformat()}",
        "limit": str(cfg.landsat.max_items),
    }
    url = f"{cfg.landsat.usgs_stac_url.rstrip('/')}/search?{urlencode(params)}"
    try:
        with urlopen(Request(url, headers={"User-Agent": "urban-digital-twin"}), 
                     timeout=cfg.landsat.timeout_seconds) as resp:
            features = json.loads(resp.read().decode("utf-8")).get("features", [])
    except Exception as e:
        raise PipelineError(f"USGS LandsatLook search failed: {e}") from e

    items: List[object] = []
    for feat in features:
        cloud = feat.get("properties", {}).get("eo:cloud_cover")
        if cloud is not None and float(cloud) >= cfg.landsat.max_cloud_cover:
            continue
        if "ST_B10" not in feat.get("assets", {}):
            continue
        try:
            items.append(pystac.Item.from_dict(feat))
        except Exception:
            logger.debug("Skipping USGS feature that is not a valid STAC item")
    logger.info("USGS LandsatLook: %d Landsat candidate scene(s)", len(items))
    return items


# ---------------------------------------------------------------------------
# Band + metadata download
# ---------------------------------------------------------------------------
def _asset_key(cfg: Config, band: str) -> str:
    """Map a product band name (ST_B10) to the provider's asset key (lwir11)."""
    return cfg.landsat.asset_keys.get(band, band)


def _download_bands(
    boundary: gpd.GeoDataFrame, item, cfg: Config, provider: str
) -> Dict[str, Path]:
    """Read ST_B10 + QA_PIXEL clipped to the boundary bbox at 30 m via stackstac."""
    if provider == "planetary-computer":
        sign_pc_assets(item)
    epsg = cfg.landsat.utm_epsg or utm_epsg_for(boundary)
    bounds_utm = [float(v) for v in boundary.to_crs(f"EPSG:{epsg}").total_bounds]
    asset_names = [_asset_key(cfg, b) for b in cfg.landsat.bands]

    da = read_stackstac_window(
        item, asset_names, epsg, cfg.landsat.resolution,
        bounds_utm, retries=cfg.landsat.retries,
    )

    paths: Dict[str, Path] = {}
    for band in cfg.landsat.bands:
        out = cfg.paths.raw_landsat / f"{band}.tif"
        if out.exists() and cfg.pipeline.skip_existing and not cfg.pipeline.force:
            logger.info("%s already downloaded - skipping", band)
            paths[band] = out
            continue

        band_da = da.sel(band=_asset_key(cfg, band)).squeeze()
        data = band_da.values.astype(np.uint16)
        transform = band_da.rio.transform()
        meta = {
            "driver": "GTiff",
            "dtype": "uint16",
            "count": 1,
            "height": data.shape[0],
            "width": data.shape[1],
            "crs": f"EPSG:{epsg}",
            "transform": transform,
            "nodata": 0,
            "compress": "deflate",
            "tiled": True,
            "blockxsize": 256,
            "blockysize": 256,
        }
        atomic_write_geotiff(out, data, meta)
        logger.info("Saved raw band %s -> %s", band, out)
        paths[band] = out
    return paths


def _download_mtl(item, cfg: Config, provider: str) -> Optional[Path]:
    """Download the MTL metadata file (JSON preferred, .txt fallback)."""
    for key in cfg.landsat.mtl_assets:
        asset = item.assets.get(key)
        if asset is None:
            continue
        if provider == "planetary-computer":
            sign_pc_assets(item)  # signs every asset again (idempotent)
        href = asset.href
        out = cfg.paths.raw_landsat / ("mtl.json" if key.endswith(".json") else "mtl.txt")
        if out.exists() and cfg.pipeline.skip_existing and not cfg.pipeline.force:
            return out
        try:
            resumable_download(
                href, out,
                chunk_size=cfg.landsat.chunk_size_bytes,
                retries=cfg.landsat.retries,
                timeout=cfg.landsat.timeout_seconds,
                logger=logger,
            )
            return out
        except PipelineError:
            logger.warning("Failed to download MTL asset '%s'; continuing without it", key)
            return None
    logger.warning("No MTL asset found in the scene; using default USGS scaling factors")
    return None


def _write_metadata(
    cfg: Config, boundary: gpd.GeoDataFrame, item, provider: str,
    paths: Dict[str, Path], epsg: int, mtl_path: Optional[Path],
) -> Path:
    cloud = item.properties.get("eo:cloud_cover")
    meta = {
        "scene_id": item.id,
        "provider": provider,
        "collection": cfg.landsat.collection,
        "datetime": item_datetime_utc(item).isoformat(),
        "cloud_cover": float(cloud) if cloud is not None else None,
        "crs_epsg": epsg,
        "resolution_m": cfg.landsat.resolution,
        "scale_mul": cfg.landsat.scale_mul,
        "scale_add": cfg.landsat.scale_add,
        "bands": {b: str(p) for b, p in paths.items()},
        "mtl": str(mtl_path) if mtl_path else None,
        "bounds_4326": [float(v) for v in boundary.total_bounds],
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    meta_path = write_json(cfg.paths.raw_landsat / "metadata.json", meta)
    logger.info("Scene metadata written -> %s", meta_path)
    return meta_path


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------
def download_landsat(cfg: Config, boundary: Optional[gpd.GeoDataFrame] = None) -> LandsatResult:
    """
    Full STEP 2 + STEP 3 workflow: search, select, download thermal bands + MTL.

    Skips cleanly when all raw bands + metadata already exist (unless forced).
    """
    boundary = boundary if boundary is not None else load_boundary(cfg.paths.boundary)
    epsg = cfg.landsat.utm_epsg or utm_epsg_for(boundary)
    meta_path = cfg.paths.raw_landsat / "metadata.json"

    all_present = all(
        (cfg.paths.raw_landsat / f"{b}.tif").exists() for b in cfg.landsat.bands
    )
    if all_present and meta_path.exists() and cfg.pipeline.skip_existing and not cfg.pipeline.force:
        logger.info("All %d Landsat bands already downloaded - reusing scene (use --force to re-download)",
                    len(cfg.landsat.bands))
        return LandsatResult.from_metadata(read_json(meta_path), cfg)

    # Search: Planetary Computer first, USGS LandsatLook as fallback.
    provider = "planetary-computer"
    try:
        items = search_landsat_pc(boundary, cfg)
    except PipelineError as e:
        logger.warning("Planetary Computer search unavailable (%s); trying USGS LandsatLook", e)
        items = []
    if not items:
        logger.warning("No scenes on Planetary Computer; trying USGS LandsatLook")
        provider = "usgs-landsatlook"
        items = search_usgs(boundary, cfg)

    item = select_best_scene(items, boundary, cfg.landsat.max_cloud_cover)
    paths = _download_bands(boundary, item, cfg, provider)
    mtl_path = _download_mtl(item, cfg, provider)
    meta_path = _write_metadata(cfg, boundary, item, provider, paths, epsg, mtl_path)

    cloud = item.properties.get("eo:cloud_cover")
    result = LandsatResult(
        scene_id=item.id,
        provider=provider,
        datetime=item_datetime_utc(item).isoformat(),
        cloud_cover=float(cloud) if cloud is not None else None,
        crs_epsg=epsg,
        resolution=cfg.landsat.resolution,
        scale_mul=cfg.landsat.scale_mul,
        scale_add=cfg.landsat.scale_add,
        bands=paths,
        mtl_path=mtl_path,
        metadata_path=meta_path,
    )
    logger.info(
        "Download complete: %d band(s) from %s (scene %s, cloud %.1f%%)",
        len(paths), provider, item.id,
        float(cloud) if cloud is not None else -1.0,
    )
    return result


if __name__ == "__main__":  # pragma: no cover
    from utils import setup_logging

    cfg = Config.from_env()
    cfg.paths.ensure()
    setup_logging(cfg)
    result = download_landsat(cfg)
    print(f"\nScene: {result.scene_id} ({result.provider})")
    print(f"Acquisition: {result.datetime}")
    for band, path in result.bands.items():
        print(f"  {band}: {path}")
