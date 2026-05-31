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
    if not config.use_network:
        return None

    s, w, n, e = bbox.south, bbox.west, bbox.north, bbox.east
    query = f"""
    [out:json][timeout:{config.request_timeout}];
    (
      way["building"]({s},{w},{n},{e});
      way["highway"]({s},{w},{n},{e});
    );
    out body geom;
    """
    elements = _query_with_mirrors(query, config)
    if elements is None:
        return None

    data = OSMData()
    for el in elements:
        geom = el.get("geometry")
        tags = el.get("tags", {})
        if not geom:
            continue
        pts = [(p["lon"], p["lat"]) for p in geom]
        if "building" in tags:
            if len(pts) >= 4:
                data.buildings.append(Building(ring=pts, height_m=_height(tags)))
        elif "highway" in tags:
            if len(pts) >= 2:
                data.roads.append(Road(line=pts, kind=tags.get("highway", "road")))

    return data if not data.is_empty else None


def _query_with_mirrors(query: str, config: Config) -> list | None:
    """Try each Overpass mirror in turn. The public instances frequently return
    rate-limit HTML or 504s, so we validate that the body is real JSON before
    trusting it and move on otherwise."""
    mirrors = config.overpass_mirrors or (config.overpass_url,)
    for url in mirrors:
        try:
            r = requests.post(
                url,
                data={"data": query},
                headers={"User-Agent": config.user_agent},
                timeout=config.request_timeout + 30,
            )
            if r.status_code != 200:
                continue
            if "json" not in r.headers.get("Content-Type", "") and not r.text.lstrip().startswith("{"):
                continue  # an error page, not data
            return r.json().get("elements", [])
        except Exception:
            continue
    return None
