"""
STEP 2 - Digital Elevation Model download
=========================================
Preferred: Copernicus DEM GLO-30 (~30 m) 1x1 degree tiles from the public
AWS Open Data bucket (no authentication required).

Fallback:  NASA SRTM 30 m (SRTMGL1) via the OpenTopography API - requires a
free API key in the ``OPENTOPOGRAPHY_API_KEY`` environment variable.

Downloads are resumable (``.part`` files with HTTP Range) and completed tiles
are skipped on re-runs. Tiles land in ``data/raw/dem/``.
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

import geopandas as gpd
import requests
from tqdm import tqdm

from config import Config
from utils import PipelineError, load_boundary, read_json, write_json

logger = logging.getLogger("sentinel.dem.download")


@dataclass
class DemResult:
    """What the processing stage needs to know about the downloaded DEM."""

    provider: str
    tiles: Dict[str, Path] = field(default_factory=dict)   # tile name -> path
    single_path: Optional[Path] = None                      # SRTM single GeoTIFF
    metadata_path: Optional[Path] = None

    @classmethod
    def from_metadata(cls, meta: dict, cfg: Config) -> "DemResult":
        tiles = {
            name: cfg.paths.raw_dem / f"{name}.tif"
            for name in meta.get("tiles", {}).keys()
        }
        single = cfg.paths.raw_dem / "srtm_30m.tif"
        return cls(
            provider=meta.get("provider", "unknown"),
            tiles=tiles,
            single_path=single if single.exists() else None,
            metadata_path=cfg.paths.raw_dem / "dem_metadata.json",
        )


# ---------------------------------------------------------------------------
# Resumable download (requests)
# ---------------------------------------------------------------------------
def resumable_download(
    url: str,
    dest: Path,
    headers: Optional[Dict[str, str]] = None,
    chunk_size: int = 1 << 20,
    retries: int = 3,
    timeout: int = 300,
) -> Path:
    """
    Download ``url`` to ``dest``, resuming interrupted transfers via Range.

    Writes to ``dest.part`` and atomically renames on success; retries with
    exponential backoff. Re-running the pipeline resumes partial downloads.
    """
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(str(dest) + ".part")
    base_headers = dict(headers or {})

    for attempt in range(retries + 1):
        try:
            existing = tmp.stat().st_size if tmp.exists() else 0
            req_headers = dict(base_headers)
            if existing > 0:
                req_headers["Range"] = f"bytes={existing}-"

            with requests.get(url, headers=req_headers, stream=True,
                              timeout=timeout) as resp:
                resp.raise_for_status()
                if resp.status_code == 206 and existing > 0:
                    total = int(resp.headers.get("Content-Range", "/0").split("/")[-1] or 0)
                    mode, initial = "ab", existing
                else:
                    if existing > 0:
                        logger.warning("Server ignored Range request; restarting %s", dest.name)
                    total = int(resp.headers.get("Content-Length") or 0)
                    mode, initial = "wb", 0

                with open(tmp, mode) as fh, tqdm(
                    total=total, initial=initial, unit="B", unit_scale=True,
                    desc=f"downloading {dest.name}", leave=False,
                ) as pbar:
                    for chunk in resp.iter_content(chunk_size=chunk_size):
                        if not chunk:
                            continue
                        fh.write(chunk)
                        pbar.update(len(chunk))
            os.replace(tmp, dest)
            logger.info("Downloaded %s -> %s", dest.name, dest)
            return dest

        except requests.HTTPError as e:
            if e.response is not None and e.response.status_code == 416 and tmp.exists():
                logger.warning("Server returned 416 for %s; restarting file", dest.name)
                tmp.unlink(missing_ok=True)
                continue
            if attempt < retries:
                logger.warning("HTTP error %s on %s (attempt %d/%d)",
                               e.response.status_code if e.response else "?",
                               dest.name, attempt + 1, retries + 1)
            else:
                raise PipelineError(f"Download failed for {url}: {e}") from e
        except requests.RequestException as e:
            if attempt < retries:
                logger.warning("Network error on %s (attempt %d/%d): %s",
                               dest.name, attempt + 1, retries + 1, e)
            else:
                raise PipelineError(f"Download failed for {url}: {e}") from e

        time.sleep(min(2 ** attempt, 30))

    raise PipelineError(f"Download failed after {retries + 1} attempts: {url}")


# ---------------------------------------------------------------------------
# Copernicus DEM GLO-30 (preferred)
# ---------------------------------------------------------------------------
def tile_corners(boundary: gpd.GeoDataFrame, tile_size: float) -> List[tuple]:
    """SW corners (lat0, lon0) of the 1x1 degree tiles covering the boundary."""
    minx, miny, maxx, maxy = boundary.total_bounds
    lats = range(int(miny // tile_size), int(maxy // tile_size) + 1)
    lons = range(int(minx // tile_size), int(maxx // tile_size) + 1)
    return [(lat * tile_size, lon * tile_size) for lat in lats for lon in lons]


def copernicus_tile_name(lat0: float, lon0: float) -> str:
    """AWS tile name, e.g. Copernicus_DSM_COG_10_N20_00_E085_00_DEM."""
    lat_tag = f"N{abs(int(lat0)):02d}_00" if lat0 >= 0 else f"S{abs(int(lat0)):02d}_00"
    lon_tag = f"E{abs(int(lon0)):03d}_00" if lon0 >= 0 else f"W{abs(int(lon0)):03d}_00"
    return f"Copernicus_DSM_COG_10_{lat_tag}_{lon_tag}_DEM"


def copernicus_tile_url(cfg: Config, name: str) -> str:
    return f"{cfg.dem.copernicus_base_url.rstrip('/')}/{name}/{name}.tif"


def download_copernicus_tiles(boundary: gpd.GeoDataFrame, cfg: Config) -> Dict[str, Path]:
    """Download every GLO-30 tile covering the boundary into data/raw/dem/."""
    corners = tile_corners(boundary, cfg.dem.tile_size_deg)
    tiles: Dict[str, Path] = {}
    for lat0, lon0 in corners:
        name = copernicus_tile_name(lat0, lon0)
        out = cfg.paths.raw_dem / f"{name}.tif"
        if out.exists() and cfg.pipeline.skip_existing and not cfg.pipeline.force:
            logger.info("%s already downloaded - skipping", name)
            tiles[name] = out
            continue
        url = copernicus_tile_url(cfg, name)
        logger.info("Tile %s (%dN, %dE) -> %s", name, int(lat0), int(lon0), url)
        resumable_download(
            url, out, chunk_size=cfg.dem.chunk_size_bytes,
            retries=cfg.dem.retries, timeout=cfg.dem.timeout_seconds,
        )
        tiles[name] = out
    return tiles


# ---------------------------------------------------------------------------
# NASA SRTM 30 m fallback (OpenTopography)
# ---------------------------------------------------------------------------
def download_srtm(boundary: gpd.GeoDataFrame, cfg: Config) -> Path:
    """Download SRTMGL1 (30 m) as a single GeoTIFF via the OpenTopography API."""
    api_key = os.environ.get(cfg.dem.api_key_env)
    if not api_key:
        raise PipelineError(
            f"SRTM fallback requires an OpenTopography API key. Get a free key at "
            f"https://opentopography.org and set the {cfg.dem.api_key_env} "
            f"environment variable."
        )
    minx, miny, maxx, maxy = boundary.total_bounds
    params = {
        "demtype": cfg.dem.srtm_dem_type,
        "south": miny, "north": maxy, "west": minx, "east": maxx,
        "outputFormat": "GTiff",
        "API_Key": api_key,
    }
    out = cfg.paths.raw_dem / "srtm_30m.tif"
    if out.exists() and cfg.pipeline.skip_existing and not cfg.pipeline.force:
        logger.info("SRTM DEM already downloaded - skipping")
        return out

    logger.info("Requesting %s from OpenTopography (%s)", cfg.dem.srtm_dem_type,
                cfg.dem.opentopography_url)
    tmp = Path(str(out) + ".part")
    for attempt in range(cfg.dem.retries + 1):
        try:
            with requests.get(cfg.dem.opentopography_url, params=params,
                              stream=True, timeout=cfg.dem.timeout_seconds) as resp:
                resp.raise_for_status()
                total = int(resp.headers.get("Content-Length") or 0)
                with open(tmp, "wb") as fh, tqdm(
                    total=total, unit="B", unit_scale=True,
                    desc=f"downloading {out.name}", leave=False,
                ) as pbar:
                    for chunk in resp.iter_content(chunk_size=cfg.dem.chunk_size_bytes):
                        if chunk:
                            fh.write(chunk)
                            pbar.update(len(chunk))
            os.replace(tmp, out)
            logger.info("SRTM DEM saved -> %s", out)
            return out
        except requests.RequestException as e:
            if attempt < cfg.dem.retries:
                logger.warning("SRTM request failed (attempt %d/%d): %s",
                               attempt + 1, cfg.dem.retries + 1, e)
            else:
                raise PipelineError(f"SRTM download failed: {e}") from e
            time.sleep(min(2 ** attempt, 30))
    raise PipelineError("SRTM download failed")  # pragma: no cover


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------
def download_dem(cfg: Config, boundary: Optional[gpd.GeoDataFrame] = None) -> DemResult:
    """
    STEP 2: download the DEM covering the boundary.

    Tries Copernicus DEM GLO-30 first; falls back to NASA SRTM 30 m on failure.
    """
    boundary = boundary if boundary is not None else load_boundary(cfg.paths.boundary)
    meta_path = cfg.paths.raw_dem / "dem_metadata.json"

    # Resume check: metadata present + tiles present -> reuse.
    meta = read_json(meta_path)
    if meta and cfg.pipeline.skip_existing and not cfg.pipeline.force:
        tiles = meta.get("tiles", {})
        if tiles and all((cfg.paths.raw_dem / f"{name}.tif").exists() for name in tiles):
            logger.info("DEM tiles already downloaded - reusing (use --force to re-download)")
            return DemResult.from_metadata(meta, cfg)

    provider = "copernicus-dem-glo30"
    try:
        tiles = download_copernicus_tiles(boundary, cfg)
        single = None
    except PipelineError as e:
        logger.warning("Copernicus DEM download failed (%s); trying SRTM 30m fallback", e)
        provider = "srtm-30m"
        tiles = {}
        single = download_srtm(boundary, cfg)

    record = {
        "provider": provider,
        "tiles": {name: str(p) for name, p in tiles.items()},
        "single": str(single) if single else None,
        "bounds_4326": [float(v) for v in boundary.total_bounds],
        "resolution_note": "Copernicus GLO-30 ~30m (1/3600 deg) | SRTMGL1 1 arc-sec",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    meta_path = write_json(cfg.paths.raw_dem / "dem_metadata.json", record)
    logger.info("DEM download complete (%s)", provider)
    return DemResult(provider=provider, tiles=tiles, single_path=single,
                     metadata_path=meta_path)


if __name__ == "__main__":  # pragma: no cover
    from utils import setup_logging

    cfg = Config.from_env()
    cfg.paths.ensure()
    setup_logging(cfg)
    result = download_dem(cfg)
    print(f"\nProvider: {result.provider}")
    for name, path in result.tiles.items():
        print(f"  {name}: {path}")
