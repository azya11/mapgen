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


def test_claude_tool_schema_matches_worldspec_and_registry():
    from mapgen.parser.claude_parser import TOOL
    from mapgen.props import all_keys
    from mapgen.spec import WorldSpec, WorldStyle

    props = TOOL["input_schema"]["properties"]
    # every world_style enum value is a valid WorldStyle
    for v in props["world_style"]["enum"]:
        WorldStyle(v)
    # the prop generator enum is exactly the live registry keys
    gen_enum = props["props"]["items"]["properties"]["generator"]["enum"]
    assert set(gen_enum) == set(all_keys())

    # a representative tool payload validates against WorldSpec
    sample = {
        "name": "Riverside",
        "world_style": "lowpoly_nature",
        "extent_m": 400.0,
        "terrain": {"features": [{"type": "river", "direction": "east"}]},
        "props": [{"generator": "tree.conifer", "count": 30, "region": "north", "density": "dense"}],
    }
    w = WorldSpec.model_validate(sample)
    assert w.terrain.has_water and w.props[0].generator == "tree.conifer"
