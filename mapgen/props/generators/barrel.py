"""Low-poly barrel: an octagonal cylinder. Watertight, ~28 tris."""

from __future__ import annotations

import numpy as np
import trimesh
from pydantic import BaseModel, Field

from ..base import PropMesh, from_trimesh
from ..registry import register


class BarrelParams(BaseModel):
    height: float = Field(default=1.0, gt=0.1, le=5.0)
    radius: float = Field(default=0.35, gt=0.05, le=3.0)


@register("barrel", params_model=BarrelParams, poly_budget=60)
def barrel(p: BarrelParams, rng: np.random.Generator) -> PropMesh:
    mesh = trimesh.creation.cylinder(radius=p.radius, height=p.height, sections=8)
    mesh.apply_translation([0, 0, p.height / 2.0])
    return from_trimesh(mesh, "wood")
