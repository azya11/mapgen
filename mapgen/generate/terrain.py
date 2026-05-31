"""Terrain heightfields. Two producers — one from real elevation data, one
procedural from the parsed features — both yield a Heightfield, which is then
triangulated into a mesh. Keeps a consistent metric coordinate frame so real
and procedural scenes are interchangeable downstream."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..spec import FeatureType, GeoFeature, MapStyle, SceneSpec, Size
from . import noise


@dataclass
class Heightfield:
    """A regular grid of elevations over a square [size_m x size_m] patch.
    z is in metres; x/y span -size_m/2 .. +size_m/2 (x east, y north)."""

    z: np.ndarray          # (res, res) metres
    size_m: float
    sea_level: float | None = None  # metres, if a water plane applies

    @property
    def res(self) -> int:
        return self.z.shape[0]

    @property
    def relief(self) -> float:
        return float(self.z.max() - self.z.min())


_SIZE_GAIN = {Size.small: 0.45, Size.medium: 1.0, Size.large: 1.9}


def from_elevation(grid: np.ndarray, size_m: float, spec: SceneSpec) -> Heightfield:
    """Wrap a real elevation grid. Sets a sea level if the scene implies water
    and the data actually dips near/below zero."""
    z = grid.astype(float).copy()
    sea = None
    if spec.has_water:
        # Use a low percentile as waterline if terrain approaches sea level.
        lo = np.percentile(z, 8)
        if lo <= 5.0 or z.min() <= 0.5:
            sea = max(0.0, float(np.percentile(z, 5)))
    return Heightfield(z=z, size_m=size_m, sea_level=sea)


def procedural(spec: SceneSpec, res: int, seed: int) -> Heightfield:
    """Build a heightfield from the parsed features alone (no real data)."""
    size_m = spec.extent_km * 1000.0

    base = noise.fbm(res, seed, octaves=6, base_cells=3)
    height = base * 60.0  # gentle rolling base, metres

    mountains = spec.features_of(FeatureType.mountain, FeatureType.hill)
    valleys = spec.features_of(FeatureType.valley)
    waters = spec.features_of(
        FeatureType.water, FeatureType.lake, FeatureType.sea,
        FeatureType.river, FeatureType.coast,
    )

    # Relief amplitude scales with style.
    style_gain = {
        MapStyle.fantasy: 2.2, MapStyle.topographic: 1.5,
        MapStyle.terrain: 1.0, MapStyle.city: 0.35,
        MapStyle.schematic: 0.5, MapStyle.satellite: 1.0,
        MapStyle.minimal: 0.7,
    }.get(spec.map_style, 1.0)

    for f in mountains:
        ramp = noise.directional_ramp(res, f.direction.value if f.direction else "center")
        peak_noise = noise.fbm(res, seed + 700 + hash(f.type) % 100, octaves=5, base_cells=5)
        amp = (900.0 if f.type == FeatureType.mountain else 220.0) * _SIZE_GAIN[f.relative_size]
        height += ramp**1.6 * peak_noise * amp * style_gain

    for f in valleys:
        ramp = noise.directional_ramp(res, f.direction.value if f.direction else "center")
        height -= ramp**1.5 * 180.0 * _SIZE_GAIN[f.relative_size]

    sea = None
    for f in waters:
        if f.type in (FeatureType.sea, FeatureType.coast):
            ramp = noise.directional_ramp(res, f.direction.value if f.direction else "south")
            height -= ramp**1.3 * 140.0  # slope down toward the sea
            sea = 0.0
        elif f.type == FeatureType.lake:
            # carve a basin somewhere offset toward its direction
            fall = noise.radial_falloff(res, power=3.0)
            shifted = _shift_field(fall, f.direction.value if f.direction else "center")
            height -= shifted * 90.0 * _SIZE_GAIN[f.relative_size]
            sea = float(np.percentile(height, 12)) if sea is None else sea

    if sea is not None:
        sea = max(sea, float(height.min()) + 1.0)

    return Heightfield(z=height, size_m=size_m, sea_level=sea)


def _shift_field(field: np.ndarray, direction: str) -> np.ndarray:
    res = field.shape[0]
    off = res // 4
    shifts = {
        "north": (0, off), "south": (0, -off),
        "east": (off, 0), "west": (-off, 0),
        "northeast": (off, off), "northwest": (-off, off),
        "southeast": (off, -off), "southwest": (-off, -off),
        "center": (0, 0),
    }
    dx, dy = shifts.get(direction, (0, 0))
    return np.roll(np.roll(field, dx, axis=0), dy, axis=1)


def heightfield_to_mesh(hf: Heightfield):
    """Triangulate a heightfield into (vertices, faces) arrays."""
    res = hf.res
    half = hf.size_m / 2.0
    xs = np.linspace(-half, half, res)
    ys = np.linspace(-half, half, res)
    gx, gy = np.meshgrid(xs, ys, indexing="ij")  # gx east, gy north

    verts = np.column_stack([gx.ravel(), gy.ravel(), hf.z.ravel()])

    # Two triangles per grid quad.
    idx = np.arange(res * res).reshape(res, res)
    a = idx[:-1, :-1].ravel()
    b = idx[1:, :-1].ravel()
    c = idx[1:, 1:].ravel()
    d = idx[:-1, 1:].ravel()
    faces = np.vstack([
        np.column_stack([a, b, c]),
        np.column_stack([a, c, d]),
    ])
    return verts, faces
