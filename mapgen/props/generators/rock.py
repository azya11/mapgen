"""Low-poly boulder: a jittered icosahedron (20 faces). Watertight, ~20 tris."""

from __future__ import annotations

import numpy as np
import trimesh
from pydantic import BaseModel, Field

from ..base import PropMesh, from_trimesh
from ..registry import register


class RockParams(BaseModel):
    radius: float = Field(default=0.5, gt=0.02, le=20.0)
    jitter: float = Field(default=0.25, ge=0.0, le=0.6)


@register("rock", params_model=RockParams, poly_budget=40)
def rock(p: RockParams, rng: np.random.Generator) -> PropMesh:
    mesh = trimesh.creation.icosahedron()
    mesh.apply_scale(p.radius)
    # Per-vertex radial jitter for an irregular boulder; flatten slightly in Z.
    offsets = 1.0 + rng.uniform(-p.jitter, p.jitter, size=len(mesh.vertices))
    mesh.vertices *= offsets[:, None]
    mesh.vertices[:, 2] *= 0.8
    return from_trimesh(mesh, "rock")
