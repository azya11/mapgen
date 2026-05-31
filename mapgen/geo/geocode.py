"""Geocoding via OSM Nominatim, plus a small bounding-box helper that converts
an extent in km into a lon/lat box and provides metric local projection."""

from __future__ import annotations

import math
from dataclasses import dataclass

import requests

from ..config import Config

EARTH_R = 6_371_000.0  # m


@dataclass
class GeoPoint:
    lat: float
    lon: float
    display_name: str = ""


@dataclass
class BBox:
    """A square area around a centre point, sized in km."""

    center: GeoPoint
    extent_km: float

    @property
    def half_m(self) -> float:
        return self.extent_km * 1000.0 / 2.0

    @property
    def dlat(self) -> float:
        return (self.half_m / EARTH_R) * (180.0 / math.pi)

    @property
    def dlon(self) -> float:
        return self.dlat / max(0.01, math.cos(math.radians(self.center.lat)))

    @property
    def south(self) -> float:
        return self.center.lat - self.dlat

    @property
    def north(self) -> float:
        return self.center.lat + self.dlat

    @property
    def west(self) -> float:
        return self.center.lon - self.dlon

    @property
    def east(self) -> float:
        return self.center.lon + self.dlon

    def to_local_xy(self, lat: float, lon: float) -> tuple[float, float]:
        """Project lon/lat to local metres, centred on the box centre.
        x = east, y = north. Equirectangular — fine for a few km."""
        x = math.radians(lon - self.center.lon) * EARTH_R * math.cos(
            math.radians(self.center.lat)
        )
        y = math.radians(lat - self.center.lat) * EARTH_R
        return x, y


def geocode(query: str, config: Config) -> GeoPoint | None:
    if not config.use_network:
        return None
    try:
        r = requests.get(
            config.nominatim_url,
            params={"q": query, "format": "json", "limit": 1},
            headers={"User-Agent": config.user_agent},
            timeout=config.request_timeout,
        )
        r.raise_for_status()
        data = r.json()
        if not data:
            return None
        top = data[0]
        return GeoPoint(
            lat=float(top["lat"]),
            lon=float(top["lon"]),
            display_name=top.get("display_name", query),
        )
    except Exception:
        return None
