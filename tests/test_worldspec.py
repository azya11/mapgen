import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mapgen.spec import (
    PropIntent,
    TerrainFeature,
    TerrainSpec,
    WorldSpec,
    WorldStyle,
)


def test_worldspec_minimal_defaults():
    w = WorldSpec(name="demo")
    assert w.world_style == WorldStyle.lowpoly_nature
    assert w.extent_m == 200.0
    assert w.seed == 1234
    assert w.props == []
    assert w.terrain.features == []


def test_worldspec_full_roundtrip():
    w = WorldSpec(
        name="village",
        world_style="fantasy",
        extent_m=400.0,
        seed=7,
        terrain=TerrainSpec(features=[TerrainFeature(type="hill", direction="north")]),
        props=[PropIntent(generator="tree.conifer", count=20, region="north", density="dense")],
    )
    assert w.terrain.features[0].type.value == "hill"
    assert w.props[0].count == 20
    # generator stays a plain string in the model (validated at build time)
    assert isinstance(w.props[0].generator, str)


def test_worldspec_extent_bounds():
    import pytest

    with pytest.raises(Exception):
        WorldSpec(name="x", extent_m=0.0)
