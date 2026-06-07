"""PropMesh: the value type every procedural prop generator returns.

Authored in the internal frame (Z-up, meters) with the pivot at the base center:
XY centroid at the origin and the lowest vertex at z=0, so placement (M2) can
drop a prop onto terrain by translating to (x, y, ground_z) with no offset math.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class PropMesh:
    verts: np.ndarray      # (N, 3) float meters, Z-up, pivot at base center
    faces: np.ndarray      # (M, 3) int
    material_id: str       # palette key, e.g. "rock", "foliage", "wood"

    @property
    def tri_count(self) -> int:
        return int(len(self.faces))

    @property
    def bbox(self) -> np.ndarray:
        return np.array([self.verts.min(axis=0), self.verts.max(axis=0)])


def from_trimesh(mesh, material_id: str) -> PropMesh:
    """Build a PropMesh from a trimesh.Trimesh, recentering to the base pivot."""
    verts = np.asarray(mesh.vertices, float).copy()
    faces = np.asarray(mesh.faces, int).copy()
    verts[:, 0] -= verts[:, 0].mean()
    verts[:, 1] -= verts[:, 1].mean()
    verts[:, 2] -= verts[:, 2].min()
    return PropMesh(verts=verts, faces=faces, material_id=material_id)
