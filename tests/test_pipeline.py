"""Smoke + contract tests. Run: python -m pytest -q  (or python tests/test_pipeline.py)."""

from __future__ import annotations

import json
import os
import struct
import sys
import tempfile

import numpy as np
import trimesh

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mapgen import Pipeline, SceneSpec
from mapgen.config import Config
from mapgen.parser.claude_parser import TOOL
from mapgen.parser.rule_parser import RuleParser
from mapgen.spec import Direction, FeatureType, MapStyle

# Prompts a level designer would actually type; the offline procedural path is
# the game-dev loop, so these must stay reliable.
GAMEDEV_PROMPTS = [
    "medieval village on a hill",
    "dense city grid",
    "canyon with a river",
]


def _offline_config(res: int = 64) -> Config:
    cfg = Config()
    cfg.use_network = False
    cfg.parser_backend = "rule"
    cfg.terrain_resolution = res
    return cfg


def _glb_primitive_attributes(path: str) -> list[list[str]]:
    """Return the attribute key lists of every mesh primitive in a .glb."""
    data = open(path, "rb").read()
    json_len = struct.unpack("<I", data[12:16])[0]
    gltf = json.loads(data[20 : 20 + json_len])
    return [
        list(prim["attributes"].keys())
        for mesh in gltf.get("meshes", [])
        for prim in mesh["primitives"]
    ]


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


def test_exported_files_carry_normals():
    """Every exported GLB/OBJ must include vertex normals — without them a game
    engine or DCC tool imports the mesh flat-/black-shaded. Regression guard for
    the silently normal-less exports."""
    cfg = _offline_config()
    for prompt in GAMEDEV_PROMPTS:
        with tempfile.TemporaryDirectory() as d:
            res = Pipeline(config=cfg).run(
                prompt, out_dir=d, formats=["glb", "obj"], basename="t"
            )
            attrs = _glb_primitive_attributes(res.files["glb"])
            assert attrs, f"{prompt!r}: GLB had no mesh primitives"
            assert all("NORMAL" in a for a in attrs), \
                f"{prompt!r}: a GLB primitive is missing NORMAL ({attrs})"
            obj = open(res.files["obj"]).read()
            assert "\nvn " in obj, f"{prompt!r}: OBJ has no vertex normals"


def test_river_prompt_produces_water():
    """A prompt naming a river must yield actual water geometry (the river used
    to parse but render nothing)."""
    cfg = _offline_config()
    for prompt in ("canyon with a river", "a valley with a wide river"):
        with tempfile.TemporaryDirectory() as d:
            res = Pipeline(config=cfg).run(prompt, out_dir=d, formats=["glb"], basename="t")
            assert res.build.stats.get("water"), f"{prompt!r}: no water generated"
            assert res.build.heightfield.sea_level is not None
            cov = float((res.build.heightfield.z <= res.build.heightfield.sea_level).mean())
            assert 0.02 <= cov <= 0.6, f"{prompt!r}: river coverage {cov:.0%} not a usable ribbon"


def test_settlement_prompt_produces_buildings():
    """Villages/towns must produce buildings — an empty settlement is unusable."""
    cfg = _offline_config()
    for prompt in ("medieval village on a hill", "a small medieval town with a market square"):
        with tempfile.TemporaryDirectory() as d:
            res = Pipeline(config=cfg).run(prompt, out_dir=d, formats=["glb"], basename="t")
            assert "buildings" in res.build.scene.geometry, f"{prompt!r}: no buildings"
            assert res.build.stats.get("buildings_source"), f"{prompt!r}: no buildings_source"


def test_meshes_are_clean():
    """No NaN vertices and no zero-area (degenerate) faces in any geometry, for
    every canonical prompt — these break collision/normals/import downstream."""
    cfg = _offline_config()
    for prompt in GAMEDEV_PROMPTS:
        res = Pipeline(config=cfg).run(prompt, out_dir=tempfile.mkdtemp(), basename="t")
        for name, g in res.build.scene.geometry.items():
            if not isinstance(g, trimesh.Trimesh):
                continue
            assert not np.isnan(g.vertices).any(), f"{prompt!r}/{name}: NaN vertices"
            tri = g.vertices[g.faces]
            area = 0.5 * np.linalg.norm(np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0]), axis=1)
            assert not (area < 1e-9).any(), f"{prompt!r}/{name}: degenerate faces"


if __name__ == "__main__":
    test_claude_tool_output_validates()
    test_rule_parser_directions()
    test_offline_pipeline_exports_all_formats()
    test_exported_files_carry_normals()
    test_river_prompt_produces_water()
    test_settlement_prompt_produces_buildings()
    test_meshes_are_clean()
    print("all tests passed")
