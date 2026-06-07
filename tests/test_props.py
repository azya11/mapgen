import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mapgen.props.base import PropMesh, from_trimesh


def test_propmesh_counts_and_bbox():
    verts = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], float)
    faces = np.array([[0, 1, 2]], int)
    pm = PropMesh(verts=verts, faces=faces, material_id="rock")
    assert pm.tri_count == 1
    assert pm.bbox.shape == (2, 3)
    np.testing.assert_allclose(pm.bbox[0], [0, 0, 0])
    np.testing.assert_allclose(pm.bbox[1], [1, 1, 0])


def test_from_trimesh_recenters_to_base_pivot():
    import trimesh

    box = trimesh.creation.box(extents=[2, 2, 2])  # centered at origin → spans z[-1,1]
    pm = from_trimesh(box, "wood")
    # pivot at base center: xy centroid ~0, lowest vertex at z~0
    assert abs(pm.verts[:, 0].mean()) < 1e-6
    assert abs(pm.verts[:, 1].mean()) < 1e-6
    assert abs(pm.verts[:, 2].min()) < 1e-6
    assert pm.material_id == "wood"
