"""
STEP 2 & 3 - Sentinel-2 Level-2A search and download
====================================================
Searches Microsoft Planetary Computer (preferred) for the latest Sentinel-2
Level-2A scene with < 10% cloud cover covering the whole boundary, then
downloads only B02 / B03 / B04 / B08 into ``data/raw/sentinel/``.

Falls back to Copernicus Data Space if Planetary Computer is unreachable or
returns no suitable scene. Downloads are resumable (`.part` files) and
completed bands are skipped on re-runs.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Union

import geopandas as gpd
import numpy as np
import rasterio
import rasterio.windows
import rioxarray  # noqa: F401  (registers the .rio accessor on xarray objects)

from config import Config
from utils import (
    PipelineError,
    atomic_write_geotiff,
    covers_boundary,
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

logger = logging.getLogger("sentinel.download")


@dataclass
class DownloadResult:
    """Everything the processing stage needs to know about the scene."""

    scene_id: str
    provider: str
    datetime: Optional[str]
    cloud_cover: Optional[float]
    crs_epsg: int
    resolution: int
    scale: float
    offset: float
    bands: Dict[str, Path] = field(default_factory=dict)
    metadata_path: Optional[Path] = None

    @classmethod
    def from_metadata(cls, meta: dict, cfg: Config) -> "DownloadResult":
        """Rebuild a result from a previously written metadata.json."""
        return cls(
            scene_id=meta.get("scene_id", "unknown"),
            provider=meta.get("provider", "unknown"),
            datetime=meta.get("datetime"),
            cloud_cover=meta.get("cloud_cover"),
            crs_epsg=int(meta.get("crs_epsg", 0) or 0),
            resolution=int(meta.get("resolution", cfg.sentinel.resolution)),
            scale=float(meta.get("scale", cfg.sentinel.scale)),
            offset=float(meta.get("offset", cfg.sentinel.offset)),
            bands={b: cfg.paths.raw_sentinel / f"{b}.tif" for b in cfg.sentinel.bands},
            metadata_path=cfg.paths.raw_sentinel / "metadata.json",
        )


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------
def search_planetary_computer(boundary: gpd.GeoDataFrame, cfg: Config) -> List[object]:
    """Search the Planetary Computer STAC catalog for S2 L2A scenes."""
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
    start = end - timedelta(days=cfg.sentinel.lookback_days)

    catalog = pystac_client.Client.open(
        cfg.sentinel.pc_stac_url, modifier=planetary_computer.sign_inplace
    )
    search = catalog.search(
        collections=[cfg.sentinel.collection],
        bbox=bbox,
        datetime=f"{start.isoformat()}/{end.isoformat()}",
        query={"eo:cloud_cover": {"lt": cfg.sentinel.max_cloud_cover}},
        max_items=cfg.sentinel.max_items * 2,
    )
    items = list(search.items())
    logger.info(
        "Planetary Computer: %d candidate scene(s) with cloud cover < %.0f%%",
        len(items), cfg.sentinel.max_cloud_cover,
    )
    return items


def _cdse_token(cfg: Config) -> str:
    """Obtain a bearer token from Copernicus Data Space (public client by default)."""
    from urllib.parse import urlencode
    from urllib.request import Request, urlopen

    client_id = cfg.sentinel.cdse_client_id or "cdse-public"
    client_secret = cfg.sentinel.cdse_client_secret or ""
    payload = urlencode({
        "grant_type": "client_credentials",
        "client_id": client_id,
        "client_secret": client_secret,
    }).encode("utf-8")
    req = Request(
        cfg.sentinel.cdse_token_url, data=payload, method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with urlopen(req, timeout=cfg.sentinel.timeout_seconds) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        raise PipelineError(f"Copernicus Data Space token request failed: {e}") from e
    token = data.get("access_token")
    if not token:
        raise PipelineError(
            f"Copernicus Data Space did not return an access token: {data}"
        )
    return token


def search_copernicus(boundary: gpd.GeoDataFrame, cfg: Config) -> List[object]:
    """Fallback search on Copernicus Data Space (STAC API, bearer token)."""
    import pystac
    from urllib.error import HTTPError
    from urllib.request import Request, urlopen

    token = _cdse_token(cfg)
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=cfg.sentinel.lookback_days)

    candidates: List[dict] = []
    for collection in ("SENTINEL-2", "sentinel-2-l2a"):
        body = {
            "collections": [collection],
            "bbox": [float(v) for v in boundary.total_bounds],
            "datetime": f"{start.isoformat()}/{end.isoformat()}",
            "query": {"eo:cloud_cover": {"lt": cfg.sentinel.max_cloud_cover}},
            "limit": cfg.sentinel.max_items,
        }
        req = Request(
            f"{cfg.sentinel.cdse_stac_url.rstrip('/')}/search",
            data=json.dumps(body).encode("utf-8"), method="POST",
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {token}"},
        )
        try:
            with urlopen(req, timeout=cfg.sentinel.timeout_seconds) as resp:
                features = json.loads(resp.read().decode("utf-8")).get("features", [])
        except HTTPError as e:
            if e.code in (400, 404):
                continue  # collection id not recognised; try the next one
            raise PipelineError(f"Copernicus Data Space search failed: HTTP {e.code}") from e
        except Exception as e:
            raise PipelineError(f"Copernicus Data Space search failed: {e}") from e
        if features:
            candidates = features
            break

    items: List[object] = []
    for feat in candidates:
        level = str(feat.get("properties", {}).get("s2:processing_level") or "")
        if level and "2A" not in level.upper():
            continue
        if "B02" not in feat.get("assets", {}):
            continue
        try:
            items.append(pystac.Item.from_dict(feat))
        except Exception:
            logger.debug("Skipping CDSE feature that is not a valid STAC item")
    logger.info(
        "Copernicus Data Space: %d Level-2A candidate scene(s)",
        len(items),
    )
    return items


# ---------------------------------------------------------------------------
# Band download
# ---------------------------------------------------------------------------
def _band_scale_offset(item, cfg: Config) -> tuple:
    """Read scale/offset from the STAC item's raster metadata if available."""
    scale, offset = cfg.sentinel.scale, cfg.sentinel.offset
    try:
        asset = item.assets[cfg.sentinel.bands[0]]
        bands_meta = asset.extra_fields.get("raster:bands") or []
        if bands_meta:
            scale = float(bands_meta[0].get("scale", scale))
            offset = float(bands_meta[0].get("offset", offset))
    except Exception:
        pass
    return scale, offset


def _download_bands_pc(
    boundary: gpd.GeoDataFrame, item, cfg: Config
) -> Dict[str, Path]:
    """
    Read the four bands clipped to the boundary bbox (at native 10 m) via
    stackstac and write each band into data/raw/sentinel/.
    """
    sign_pc_assets(item)
    epsg = cfg.sentinel.utm_epsg or utm_epsg_for(boundary)
    bounds_utm = [float(v) for v in boundary.to_crs(f"EPSG:{epsg}").total_bounds]

    da = read_stackstac_window(
        item, cfg.sentinel.bands, epsg, cfg.sentinel.resolution,
        bounds_utm, retries=cfg.sentinel.retries,
    )

    paths: Dict[str, Path] = {}
    for band in cfg.sentinel.bands:
        out = cfg.paths.raw_sentinel / f"{band}.tif"
        if out.exists() and cfg.pipeline.skip_existing and not cfg.pipeline.force:
            logger.info("%s already downloaded - skipping", band)
            paths[band] = out
            continue

        band_da = da.sel(band=band).squeeze()
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


def _download_bands_cdse(
    boundary: gpd.GeoDataFrame, item, cfg: Config
) -> Dict[str, Path]:
    """
    Fallback: download each band JP2 from Copernicus Data Space (resumable),
    then convert + crop to the boundary bbox as a GeoTIFF.
    """
    token = _cdse_token(cfg)
    headers = {"Authorization": f"Bearer {token}"}
    epsg = cfg.sentinel.utm_epsg or utm_epsg_for(boundary)
    bounds_utm = [float(v) for v in boundary.to_crs(f"EPSG:{epsg}").total_bounds]

    paths: Dict[str, Path] = {}
    for band in cfg.sentinel.bands:
        out = cfg.paths.raw_sentinel / f"{band}.tif"
        if out.exists() and cfg.pipeline.skip_existing and not cfg.pipeline.force:
            paths[band] = out
            continue

        asset = item.assets.get(band) or next(
            (a for k, a in item.assets.items() if band in k), None
        )
        if asset is None:
            raise PipelineError(f"Band {band} not found in Copernicus item assets")

        jp2 = cfg.paths.raw_sentinel / f"{band}.jp2"
        resumable_download(
            asset.href, jp2, headers=headers,
            chunk_size=cfg.sentinel.chunk_size_bytes,
            retries=cfg.sentinel.retries,
            timeout=cfg.sentinel.timeout_seconds,
            logger=logger,
        )
        _jp2_to_windowed_tif(jp2, out, bounds_utm)
        jp2.unlink(missing_ok=True)
        logger.info("Saved raw band %s -> %s", band, out)
        paths[band] = out
    return paths


def _jp2_to_windowed_tif(jp2: Path, out: Path, bounds_utm: tuple) -> None:
    """Convert a Sentinel-2 JP2 to a cropped (bbox) GeoTIFF."""
    with rasterio.open(jp2) as src:
        window = rasterio.windows.from_bounds(
            *bounds_utm, transform=src.transform
        )
        data = src.read(1, window=window)
        win_transform = rasterio.windows.transform(window, src.transform)
        meta = {
            "driver": "GTiff",
            "dtype": "uint16",
            "count": 1,
            "height": data.shape[0],
            "width": data.shape[1],
            "crs": src.crs,
            "transform": win_transform,
            "nodata": 0,
            "compress": "deflate",
            "tiled": True,
            "blockxsize": 256,
            "blockysize": 256,
        }
    atomic_write_geotiff(out, data, meta)


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------
def _write_metadata(
    cfg: Config, boundary: gpd.GeoDataFrame, item, provider: str,
    paths: Dict[str, Path], epsg: int,
) -> Path:
    scale, offset = _band_scale_offset(item, cfg)
    cloud = item.properties.get("eo:cloud_cover")
    meta = {
        "scene_id": item.id,
        "provider": provider,
        "collection": cfg.sentinel.collection,
        "datetime": item_datetime_utc(item).isoformat(),
        "cloud_cover": float(cloud) if cloud is not None else None,
        "crs_epsg": epsg,
        "resolution_m": cfg.sentinel.resolution,
        "scale": scale,
        "offset": offset,
        "bands": {b: str(p) for b, p in paths.items()},
        "bounds_4326": [float(v) for v in boundary.total_bounds],
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    meta_path = cfg.paths.raw_sentinel / "metadata.json"
    write_json(meta_path, meta)
    logger.info("Scene metadata written -> %s", meta_path)
    return meta_path


def download_sentinel(cfg: Config, boundary: Optional[gpd.GeoDataFrame] = None) -> DownloadResult:
    """
    Full STEP 2 + STEP 3 workflow: search, select, download, metadata.

    Skips cleanly when all raw bands + metadata already exist (unless forced).
    """
    boundary = boundary if boundary is not None else load_boundary(cfg.paths.boundary)
    epsg = cfg.sentinel.utm_epsg or utm_epsg_for(boundary)
    meta_path = cfg.paths.raw_sentinel / "metadata.json"

    # Resume check: everything present -> nothing to do.
    all_present = all(
        (cfg.paths.raw_sentinel / f"{b}.tif").exists() for b in cfg.sentinel.bands
    )
    if all_present and meta_path.exists() and cfg.pipeline.skip_existing and not cfg.pipeline.force:
        logger.info("All %d raw bands already downloaded - reusing scene (use --force to re-download)",
                    len(cfg.sentinel.bands))
        return DownloadResult.from_metadata(read_json(meta_path), cfg)

    # Search: Planetary Computer first, Copernicus Data Space as fallback.
    provider = "planetary-computer"
    try:
        items = search_planetary_computer(boundary, cfg)
    except PipelineError as e:
        logger.warning("Planetary Computer search unavailable (%s); trying Copernicus Data Space", e)
        items = []
    if not items:
        logger.warning("No scenes on Planetary Computer; trying Copernicus Data Space")
        provider = "copernicus-data-space"
        items = search_copernicus(boundary, cfg)

    item = select_best_scene(items, boundary, cfg.sentinel.max_cloud_cover)

    if provider == "planetary-computer":
        paths = _download_bands_pc(boundary, item, cfg)
    else:
        paths = _download_bands_cdse(boundary, item, cfg)

    scale, offset = _band_scale_offset(item, cfg)
    cloud = item.properties.get("eo:cloud_cover")
    meta_path = _write_metadata(cfg, boundary, item, provider, paths, epsg)

    result = DownloadResult(
        scene_id=item.id,
        provider=provider,
        datetime=item_datetime_utc(item).isoformat(),
        cloud_cover=float(cloud) if cloud is not None else None,
        crs_epsg=epsg,
        resolution=cfg.sentinel.resolution,
        scale=scale,
        offset=offset,
        bands=paths,
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
    result = download_sentinel(cfg)
    print(f"\nScene: {result.scene_id} ({result.provider})")
    print(f"Acquisition: {result.datetime}")
    for band, path in result.bands.items():
        print(f"  {band}: {path}")
