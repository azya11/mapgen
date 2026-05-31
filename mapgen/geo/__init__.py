"""Real-world geographic data acquisition (all from free, keyless OSM-based APIs).

If the network is unavailable or a location can't be resolved, callers fall
back to procedural generation — these functions return None rather than raise.
"""

from .geocode import BBox, GeoPoint, geocode
from .elevation import elevation_grid
from .osm import OSMData, fetch_osm

__all__ = [
    "geocode",
    "GeoPoint",
    "BBox",
    "elevation_grid",
    "fetch_osm",
    "OSMData",
]
