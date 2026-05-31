"""Elevation sampling. Uses Open-Meteo's free elevation API (no key), which
accepts batched lat/lon arrays and returns metres above sea level.

Returns a (res x res) numpy grid of elevations in metres, or None on failure."""

from __future__ import annotations

import time

import numpy as np
import requests

from ..config import Config
from .geocode import BBox

# Open-Meteo accepts up to ~100 points per GET request comfortably.
_MAX_PTS = 100
# Cap the number of *sampled* points so we stay within the free tier's rate
# limit (a handful of requests), then bilinearly upsample to the mesh grid.
# 24x24 = 576 points = 6 batches, which empirically clears the throttle.
_MAX_SAMPLE = 24
_RETRIES = 4


def elevation_grid(bbox: BBox, res: int, config: Config) -> np.ndarray | None:
    if not config.use_network:
        return None

    sres = min(res, _MAX_SAMPLE)
    lats = np.linspace(bbox.south, bbox.north, sres)
    lons = np.linspace(bbox.west, bbox.east, sres)
    grid_lat, grid_lon = np.meshgrid(lats, lons, indexing="ij")
    flat_lat = grid_lat.ravel()
    flat_lon = grid_lon.ravel()

    out = np.zeros(flat_lat.shape, dtype=float)
    for start in range(0, flat_lat.size, _MAX_PTS):
        sl = slice(start, start + _MAX_PTS)
        vals = _fetch_batch(flat_lat[sl], flat_lon[sl], config)
        if vals is None:
            return None
        out[sl] = vals

    grid = out.reshape(sres, sres)
    if sres != res:
        grid = _upsample(grid, res)
    # Guard against all-ocean (all zeros) — treat as valid flat terrain.
    return grid


def _fetch_batch(lat, lon, config: Config) -> np.ndarray | None:
    """One batch with retry+backoff on rate-limit (429) or transient errors."""
    params = {
        "latitude": ",".join(f"{v:.5f}" for v in lat),
        "longitude": ",".join(f"{v:.5f}" for v in lon),
    }
    delay = 1.0
    for attempt in range(_RETRIES):
        try:
            r = requests.get(
                config.elevation_url,
                params=params,
                headers={"User-Agent": config.user_agent},
                timeout=config.request_timeout,
            )
            if r.status_code == 429:
                time.sleep(delay)
                delay *= 2
                continue
            r.raise_for_status()
            vals = r.json().get("elevation")
            if not vals:
                return None
            return np.asarray(vals, dtype=float)
        except Exception:
            if attempt == _RETRIES - 1:
                return None
            time.sleep(delay)
            delay *= 2
    return None


def _upsample(grid: np.ndarray, res: int) -> np.ndarray:
    """Bilinear resize a (s x s) grid to (res x res) with pure numpy."""
    s = grid.shape[0]
    src = np.linspace(0, s - 1, res)
    x0 = np.floor(src).astype(int)
    x1 = np.minimum(x0 + 1, s - 1)
    fx = src - x0
    # interpolate rows then columns
    rows = grid[x0] * (1 - fx)[:, None] + grid[x1] * fx[:, None]
    cols = rows[:, x0] * (1 - fx)[None, :] + rows[:, x1] * fx[None, :]
    return cols
