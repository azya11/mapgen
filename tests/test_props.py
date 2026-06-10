import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mapgen.props.base import PropMesh, from_trimesh


@pytest.fixture(autouse=True)
def _isolate_registry():
    """Remove any throwaway generators a test registers, so the global registry
    stays clean for order-dependent tests in other modules (e.g. the tool-schema
    contract test that asserts the generator enum equals the real registry keys)."""
    from mapgen.props import registry

    before = set(registry._REGISTRY)
    yield
    for key in set(registry._REGISTRY) - before:
        registry._REGISTRY.pop(key, None)


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


def test_registry_register_build_and_budget():
    import numpy as np
    import pytest
    from pydantic import BaseModel

    from mapgen.props import registry
    from mapgen.props.base import PropMesh

    class _P(BaseModel):
        size: float = 1.0

    @registry.register("test.tri", params_model=_P, poly_budget=2)
    def _tri(p: _P, rng) -> PropMesh:
        v = np.array([[0, 0, 0], [p.size, 0, 0], [0, p.size, 0]], float)
        f = np.array([[0, 1, 2]], int)
        return PropMesh(verts=v, faces=f, material_id="rock")

    assert "test.tri" in registry.all_keys()
    pm = registry.build("test.tri", {"size": 2.0}, np.random.default_rng(0))
    assert pm.tri_count == 1
    assert pm.bbox[1][0] == 2.0

    # unknown key → KeyError
    with pytest.raises(KeyError):
        registry.build("nope", {}, np.random.default_rng(0))

    # bad params → validation error
    with pytest.raises(Exception):
        registry.build("test.tri", {"size": "huge"}, np.random.default_rng(0))


def test_registry_enforces_poly_budget():

    import numpy as np
    import pytest
    from pydantic import BaseModel

    from mapgen.props import registry
    from mapgen.props.base import PropMesh

    class _P(BaseModel):
        pass

    @registry.register("test.toomany", params_model=_P, poly_budget=1)
    def _big(p, rng) -> PropMesh:
        v = np.zeros((6, 3))
        f = np.array([[0, 1, 2], [3, 4, 5]], int)
        return PropMesh(verts=v, faces=f, material_id="rock")

    with pytest.raises(ValueError, match="poly budget"):
        registry.build("test.toomany", {}, np.random.default_rng(0))


def test_rock_generator():
    import numpy as np

    from mapgen.props import registry

    rng = np.random.default_rng(42)
    pm = registry.build("rock", {"radius": 0.5}, rng)
    assert pm.material_id == "rock"
    assert pm.tri_count <= 40
    # base pivot: lowest vertex on the ground, centered in XY
    assert abs(pm.verts[:, 2].min()) < 1e-6
    assert abs(pm.verts[:, 0].mean()) < 0.2
    # deterministic for a fixed seed
    a = registry.build("rock", {"radius": 0.5}, np.random.default_rng(1))
    b = registry.build("rock", {"radius": 0.5}, np.random.default_rng(1))
    np.testing.assert_allclose(a.verts, b.verts)


def test_tree_generators():
    import numpy as np

    from mapgen.props import registry

    conifer = registry.build("tree.conifer", {"height": 4.0}, np.random.default_rng(3))
    assert conifer.material_id == "foliage"
    assert conifer.tri_count <= 60
    assert abs(conifer.verts[:, 2].min()) < 1e-6
    assert conifer.verts[:, 2].max() <= 4.0 + 1e-6  # honors height

    broadleaf = registry.build("tree.broadleaf", {"height": 5.0}, np.random.default_rng(3))
    assert broadleaf.material_id == "foliage"
    assert broadleaf.tri_count <= 120
    assert abs(broadleaf.verts[:, 2].min()) < 1e-6
    assert broadleaf.verts[:, 2].max() <= 5.0 + 1e-6  # canopy honors height


def test_barrel_generator():
    import numpy as np
    import trimesh

    from mapgen.props import registry

    pm = registry.build("barrel", {"height": 1.0, "radius": 0.35}, np.random.default_rng(9))
    assert pm.material_id == "wood"
    assert pm.tri_count <= 60
    assert abs(pm.verts[:, 2].min()) < 1e-6
    assert pm.verts[:, 2].max() <= 1.0 + 1e-6
    # watertight: a barrel is a closed solid
    tm = trimesh.Trimesh(vertices=pm.verts, faces=pm.faces, process=False)
    assert tm.is_watertight


def test_cottage_generator():
    import numpy as np

    from mapgen.props import registry

    pm = registry.build(
        "house.cottage", {"width": 4.0, "depth": 3.0, "wall_h": 2.5}, np.random.default_rng(5)
    )
    assert pm.material_id == "building"
    assert pm.tri_count <= 40
    assert abs(pm.verts[:, 2].min()) < 1e-6
    # footprint roughly matches requested width/depth
    span = pm.bbox[1] - pm.bbox[0]
    assert abs(span[0] - 4.0) < 1e-6
    assert abs(span[1] - 3.0) < 1e-6
    # has a peaked roof taller than the walls
    assert pm.verts[:, 2].max() > 2.5
