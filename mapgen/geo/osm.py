"""OpenStreetMap vector data via the Overpass API: building footprints (with
height/levels) and roads. Footprints come back as lon/lat rings which we keep
raw; the geometry stage projects them to local metres."""

from __future__ import annotations

from dataclasses import dataclass, field

import requests

from ..config import Config
from .geocode import BBox


@dataclass
class Building:
    ring: list[tuple[float, float]]  # (lon, lat) outer ring
    height_m: float


@dataclass
class Road:
    line: list[tuple[float, float]]  # (lon, lat) polyline
    kind: str


@dataclass
class OSMData:
    buildings: list[Building] = field(default_factory=list)
    roads: list[Road] = field(default_factory=list)
    fetched_extent_km: float = 0.0   # the area actually covered (may be shrunk)

    @property
    def is_empty(self) -> bool:
        return not self.buildings and not self.roads


_LEVEL_M = 3.2  # metres per storey


def _height(tags: dict) -> float:
    h = tags.get("height")
    if h:
        try:
            return float(str(h).split()[0].replace(",", "."))
        except ValueError:
            pass
    lv = tags.get("building:levels")
    if lv:
        try:
            return float(lv) * _LEVEL_M
        except ValueError:
            pass
    return _LEVEL_M * 2  # default 2 storeys


def fetch_osm(bbox: BBox, config: Config) -> OSMData | None:
    """Fetch real building footprints. Dense/large cities (e.g. NYC) overwhelm
    the free Overpass mirrors, so we try the requested area and, if that fails,
    fall back to progressively smaller *centred* areas — that way a real
    location still gets real buildings (covering its core) instead of silently
    dropping to procedural. Roads are intentionally not fetched (not rendered)."""
    if not config.use_network:
        return None

    requested = bbox.extent_km
    # Try the full requested area first so buildings fill the whole plain, then
    # step down gracefully (≈75% each time) if the free mirrors choke on a big/
    # dense query, ending at a small core that reliably succeeds.
    top = min(requested, config.osm_max_extent_km)
    sizes: list[float] = []
    for s in (top, top * 0.75, top * 0.5, 2.0):
        s = round(min(s, requested), 2)
        if s >= 0.5 and s not in sizes:
            sizes.append(s)

    for ext in sizes:
        sub = bbox if ext >= requested else BBox(center=bbox.center, extent_km=ext)
        elements = _query_buildings(sub, config)
        if not elements:
            continue
        data = _parse_buildings(elements)
        if not data.is_empty:
            data.fetched_extent_km = ext
            return data
    return None


def _parse_buildings(elements: list) -> OSMData:
    data = OSMData()
    for el in elements:
        geom = el.get("geometry")
        tags = el.get("tags", {})
        if not geom or "building" not in tags:
            continue
        pts = [(p["lon"], p["lat"]) for p in geom]
        if len(pts) >= 4:
            data.buildings.append(Building(ring=pts, height_m=_height(tags)))
    return data


def _query_buildings(bbox: BBox, config: Config) -> list | None:
    s, w, n, e = bbox.south, bbox.west, bbox.north, bbox.east
    t = config.overpass_timeout
    query = (
        f"[out:json][timeout:{t}];"
        f'(way["building"]({s},{w},{n},{e});'
        f'relation["building"]({s},{w},{n},{e}););'
        "out body geom;"
    )
    return _query_with_mirrors(query, config)


def _query_with_mirrors(query: str, config: Config) -> list | None:
    """Try each Overpass mirror in turn. The public instances frequently return
    rate-limit HTML (406/429), 504s, or forbid us (403), so we validate that the
    body is real JSON before trusting it and move on otherwise."""
    mirrors = config.overpass_mirrors or (config.overpass_url,)
    for url in mirrors:
        try:
            r = requests.post(
                url,
                data={"data": query},
                headers={"User-Agent": config.user_agent, "Accept": "application/json"},
                timeout=config.overpass_timeout + 15,
            )
            if r.status_code != 200:
                continue
            ctype = r.headers.get("Content-Type", "")
            if "json" not in ctype and not r.text.lstrip().startswith("{"):
                continue  # an error page, not data
            return r.json().get("elements", [])
        except Exception:
            continue
    return None
