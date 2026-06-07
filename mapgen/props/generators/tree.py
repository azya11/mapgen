"""Low-poly trees. Conifer = trunk cylinder + stacked cones; broadleaf = trunk +
low-subdivision icosphere canopy. Both author the trunk base at z=0."""

from __future__ import annotations

import numpy as np
import trimesh
from pydantic import BaseModel, Field

from ..base import PropMesh, from_trimesh
from ..registry import register


class ConiferParams(BaseModel):
    height: float = Field(default=4.0, gt=0.3, le=60.0)
    trunk_frac: float = Field(default=0.18, gt=0.02, le=0.5)


class BroadleafParams(BaseModel):
    height: float = Field(default=5.0, gt=0.3, le=60.0)
    trunk_frac: float = Field(default=0.45, gt=0.05, le=0.7)


def _stack(meshes: list[trimesh.Trimesh]) -> trimesh.Trimesh:
    return trimesh.util.concatenate(meshes)


@register("tree.conifer", params_model=ConiferParams, poly_budget=60)
def conifer(p: ConiferParams, rng: np.random.Generator) -> PropMesh:
    trunk_h = p.height * p.trunk_frac
    canopy_h = p.height - trunk_h
    trunk = trimesh.creation.cylinder(radius=p.height * 0.03, height=trunk_h, sections=5)
    trunk.apply_translation([0, 0, trunk_h / 2.0])
    # two stacked cones for a layered conifer silhouette
    c1 = trimesh.creation.cone(radius=p.height * 0.22, height=canopy_h * 0.7, sections=6)
    c1.apply_translation([0, 0, trunk_h])
    c2 = trimesh.creation.cone(radius=p.height * 0.15, height=canopy_h * 0.55, sections=6)
    c2.apply_translation([0, 0, trunk_h + canopy_h * 0.45])
    return from_trimesh(_stack([trunk, c1, c2]), "foliage")


@register("tree.broadleaf", params_model=BroadleafParams, poly_budget=120)
def broadleaf(p: BroadleafParams, rng: np.random.Generator) -> PropMesh:
    trunk_h = p.height * p.trunk_frac
    trunk = trimesh.creation.cylinder(radius=p.height * 0.04, height=trunk_h, sections=6)
    trunk.apply_translation([0, 0, trunk_h / 2.0])
    canopy_r = p.height * 0.28
    canopy = trimesh.creation.icosphere(subdivisions=1, radius=canopy_r)
    canopy.vertices[:, 2] *= 0.85
    canopy.apply_translation([0, 0, trunk_h + canopy_r * 0.7])
    return from_trimesh(_stack([trunk, canopy]), "foliage")
