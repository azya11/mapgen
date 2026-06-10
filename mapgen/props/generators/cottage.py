"""Low-poly cottage: a box body + a triangular-prism gable roof. ~16 tris."""

from __future__ import annotations

import numpy as np
import trimesh
from pydantic import BaseModel, Field

from ..base import PropMesh, from_trimesh
from ..registry import register


class CottageParams(BaseModel):
    width: float = Field(default=4.0, gt=0.5, le=40.0)   # X span
    depth: float = Field(default=3.0, gt=0.5, le=40.0)   # Y span
    wall_h: float = Field(default=2.5, gt=0.5, le=20.0)
    roof_h: float = Field(default=1.5, gt=0.1, le=15.0)


@register("house.cottage", params_model=CottageParams, poly_budget=40)
def cottage(p: CottageParams, rng: np.random.Generator) -> PropMesh:
    w, d, wh, rh = p.width, p.depth, p.wall_h, p.roof_h
    body = trimesh.creation.box(extents=[w, d, wh])
    body.apply_translation([0, 0, wh / 2.0])

    hx, hy = w / 2.0, d / 2.0
    # Gable prism: ridge runs along X at the top, eaves at wall height.
    roof_v = np.array([
        [-hx, -hy, wh], [hx, -hy, wh], [hx, hy, wh], [-hx, hy, wh],  # eaves 0..3
        [-hx, 0.0, wh + rh], [hx, 0.0, wh + rh],                      # ridge 4,5
    ], float)
    roof_f = np.array([
        [0, 1, 5], [0, 5, 4],   # front slope
        [3, 4, 5], [3, 5, 2],   # back slope
        [0, 4, 3],              # left gable
        [1, 2, 5],              # right gable
    ], int)
    roof = trimesh.Trimesh(vertices=roof_v, faces=roof_f, process=False)
    return from_trimesh(trimesh.util.concatenate([body, roof]), "building")
