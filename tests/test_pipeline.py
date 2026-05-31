"""Smoke + contract tests. Run: python -m pytest -q  (or python tests/test_pipeline.py)."""

from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mapgen import Pipeline, SceneSpec
from mapgen.config import Config
from mapgen.parser.claude_parser import TOOL
from mapgen.parser.rule_parser import RuleParser
from mapgen.spec import Direction, FeatureType, MapStyle


def test_claude_tool_output_validates():
    """A representative Claude tool payload must satisfy the SceneSpec schema,
    guaranteeing the tool schema and the pydantic model stay in sync."""
    sample = {
        "location": "Nice, France",
        "is_real_location": True,
        "map_style": "terrain",
        "extent_km": 6.0,
        "features": [
            {"type": "mountain", "direction": "north", "relative_size": "large"},
            {"type": "sea", "direction": "south"},
        ],
        "notes": "Coastal city.",
    }
    spec = SceneSpec.model_validate(sample)
    assert spec.is_real_location and spec.has_water
    assert spec.features[0].type == FeatureType.mountain
    # every enum used in the tool schema must be a valid model value
    for v in TOOL["input_schema"]["properties"]["map_style"]["enum"]:
        MapStyle(v)


def test_rule_parser_directions():
    cfg = Config()
    spec = RuleParser(cfg).parse(
        "a coastal town with mountains to the north and a forest to the west"
    )
    dirs = {f.type: f.direction for f in spec.features}
    assert dirs[FeatureType.mountain] == Direction.north
    assert dirs[FeatureType.forest] == Direction.west


def test_offline_pipeline_exports_all_formats():
    cfg = Config()
    cfg.use_network = False
    cfg.parser_backend = "rule"
    cfg.terrain_resolution = 48  # small + fast
    pipe = Pipeline(config=cfg)
    with tempfile.TemporaryDirectory() as d:
        res = pipe.run(
            "a fantasy valley between two volcanoes with a lake in the center",
            out_dir=d,
            formats=["glb", "obj", "stl", "blender"],
            basename="t",
        )
        for fmt in ("glb", "obj", "stl", "blender"):
            assert fmt in res.files and os.path.getsize(res.files[fmt]) > 0
        assert res.build.stats["terrain_faces"] > 0


if __name__ == "__main__":
    test_claude_tool_output_validates()
    test_rule_parser_directions()
    test_offline_pipeline_exports_all_formats()
    print("all tests passed")
