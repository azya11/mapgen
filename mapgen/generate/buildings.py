"""Building geometry — extruded from real OSM footprints when available, or
procedurally placed blocks for city/district scenes without real data."""

from __future__ import annotations

import numpy as np
import trimesh
from shapely.geometry import Polygon

from ..geo.geocode import BBox
from ..geo.osm import OSMData
from ..spec import FeatureType, MapStyle, SceneSpec, Size
from . import noise
from .terrain import Heightfield


def _sample_height(hf: Heightfield, x: float, y: float) -> float:
    """Bilinear-ish nearest sample of terrain z at local (x, y) metres."""
    res = hf.res
    half = hf.size_m / 2.0
    fx = np.clip((x + half) / hf.size_m, 0, 1) * (res - 1)
    fy = np.clip((y + half) / hf.size_m, 0, 1) * (res - 1)
    return float(hf.z[int(round(fx)), int(round(fy))])


def from_osm(osm: OSMData, bbox: BBox, hf: Heightfield) -> trimesh.Trimesh | None:
    meshes = []
    for b in osm.buildings:
        xy = [bbox.to_local_xy(lat, lon) for lon, lat in b.ring]
        try:
            poly = Polygon(xy)
            if not poly.is_valid or poly.area < 4.0:  # skip slivers (<4 m²)
                continue
            base = _sample_height(hf, poly.centroid.x, poly.centroid.y)
            mesh = trimesh.creation.extrude_polygon(poly, height=b.height_m)
            mesh.apply_translation([0, 0, base])
            meshes.append(mesh)
        except Exception:
            continue
    if not meshes:
        return None
    return trimesh.util.concatenate(meshes)


def procedural(spec: SceneSpec, hf: Heightfield, seed: int) -> trimesh.Trimesh | None:
    """Scatter blocks for city/district scenes. Density and height respond to
    style and to any 'district'/'building' features and their direction."""
    districts = spec.features_of(FeatureType.district, FeatureType.building)
    if spec.map_style != MapStyle.city and not districts:
        return None

    rng = np.random.default_rng(seed + 99)
    size = hf.size_m
    half = size / 2.0

    # City core density field — biased toward district directions, else centre.
    res = hf.res
    field = np.zeros((res, res))
    if districts:
        for d in districts:
            field += noise.directional_ramp(res, d.direction.value if d.direction else "center")
    else:
        field += noise.radial_falloff(res, power=2.5)
    field /= max(field.max(), 1e-9)

    # Pick a building count proportional to area, capped for performance.
    n_target = int(np.clip(spec.extent_km * 120, 40, 600))
    max_h = {Size.small: 18, Size.medium: 45, Size.large: 120}
    base_h = 30.0
    if districts:
        base_h = max(max_h[d.relative_size] for d in districts)

    meshes = []
    attempts = 0
    while len(meshes) < n_target and attempts < n_target * 6:
        attempts += 1
        x = rng.uniform(-half * 0.95, half * 0.95)
        y = rng.uniform(-half * 0.95, half * 0.95)
        gx = int(np.clip((x + half) / size * (res - 1), 0, res - 1))
        gy = int(np.clip((y + half) / size * (res - 1), 0, res - 1))
        if rng.random() > field[gx, gy] ** 1.5 + 0.04:
            continue
        if hf.sea_level is not None and _sample_height(hf, x, y) <= hf.sea_level:
            continue
        fw = rng.uniform(8, 22)
        fd = rng.uniform(8, 22)
        h = float(rng.uniform(8, base_h) * (0.4 + field[gx, gy]))
        box = trimesh.creation.box(extents=[fw, fd, h])
        base = _sample_height(hf, x, y)
        box.apply_translation([x, y, base + h / 2.0])
        meshes.append(box)

    if not meshes:
        return None
    return trimesh.util.concatenate(meshes)
