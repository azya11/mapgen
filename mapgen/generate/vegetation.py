"""Procedural low-poly forests. Trees are scattered inside the directional
footprint of any forest/park feature, on land above the waterline and not on
the steepest slopes, then merged into a single coloured mesh for cheap export."""

from __future__ import annotations

import numpy as np
import trimesh

from ..spec import FeatureType, SceneSpec, Size
from . import noise
from .buildings import _sample_height
from .terrain import Heightfield

_SIZE_SCALE = {Size.small: 0.7, Size.medium: 1.0, Size.large: 1.4}
_TRUNK = np.array([95, 70, 48], np.uint8)
_FOLIAGE = [  # a little palette so the canopy isn't a flat green
    (58, 94, 50), (70, 110, 58), (84, 124, 64), (50, 84, 46), (96, 132, 72),
]


def _make_tree(rng: np.random.Generator, height: float) -> trimesh.Trimesh:
    trunk_h = height * 0.32
    trunk = trimesh.creation.cylinder(radius=height * 0.05, height=trunk_h, sections=5)
    trunk.apply_translation([0, 0, trunk_h / 2])
    trunk.visual.face_colors = np.array([*_TRUNK, 255], np.uint8)

    parts = [trunk]
    n_cones = rng.integers(2, 4)
    canopy_rgb = _FOLIAGE[rng.integers(len(_FOLIAGE))]
    cz = trunk_h
    crad = height * rng.uniform(0.34, 0.46)
    for i in range(n_cones):
        ch = height * 0.5 / n_cones * rng.uniform(1.4, 1.8)
        cone = trimesh.creation.cone(radius=crad, height=ch, sections=7)
        cone.apply_translation([0, 0, cz])
        # tint each tier slightly for depth
        tint = np.clip(np.array(canopy_rgb) + rng.integers(-12, 12, 3), 30, 200)
        cone.visual.face_colors = np.array([*tint, 255], np.uint8)
        parts.append(cone)
        cz += ch * 0.55
        crad *= 0.7
    return trimesh.util.concatenate(parts)


def forests(spec: SceneSpec, hf: Heightfield, seed: int) -> trimesh.Trimesh | None:
    feats = spec.features_of(FeatureType.forest, FeatureType.park)
    if not feats:
        return None

    rng = np.random.default_rng(seed + 555)
    res = hf.res
    size = hf.size_m
    half = size / 2.0

    field = np.zeros((res, res))
    scale = 1.0
    for f in feats:
        field += noise.directional_ramp(res, f.direction.value if f.direction else "center")
        scale = max(scale, _SIZE_SCALE[f.relative_size])
    field /= max(field.max(), 1e-9)
    # break up the edge with a little noise so forests don't look like discs
    field = np.clip(field * (0.7 + 0.6 * noise.fbm(res, seed + 9, octaves=4, base_cells=6)), 0, 1)

    n_target = int(np.clip(spec.extent_km * 220, 120, 1400))
    dx = size / max(res - 1, 1)

    meshes = []
    attempts = 0
    while len(meshes) < n_target and attempts < n_target * 8:
        attempts += 1
        x = rng.uniform(-half * 0.97, half * 0.97)
        y = rng.uniform(-half * 0.97, half * 0.97)
        gx = int(np.clip((x + half) / size * (res - 1), 0, res - 1))
        gy = int(np.clip((y + half) / size * (res - 1), 0, res - 1))
        if rng.random() > field[gx, gy] ** 1.3:
            continue
        base = _sample_height(hf, x, y)
        if hf.sea_level is not None and base <= hf.sea_level + 0.5:
            continue
        # avoid very steep ground (sample the local slope cheaply)
        if gx + 1 < res and gy + 1 < res:
            slope = abs(hf.z[gx + 1, gy] - hf.z[gx, gy]) + abs(hf.z[gx, gy + 1] - hf.z[gx, gy])
            if slope / dx > 1.2:  # ~50 deg
                continue
        h = float(rng.uniform(7, 15) * scale)
        tree = _make_tree(rng, h)
        tree.apply_translation([x, y, base])
        meshes.append(tree)

    if not meshes:
        return None
    return trimesh.util.concatenate(meshes)
