"""Smoke + contract tests for the procedural world pipeline.
Run: .\\.venv\\Scripts\\python.exe -m pytest tests -q
"""

from __future__ import annotations

import json
import os
import struct
import sys
import tempfile

import numpy as np
import trimesh

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mapgen import Pipeline, WorldSpec
from mapgen.config import Config
from mapgen.parser.rule_parser import RuleParser
from mapgen.spec import Direction, FeatureType, WorldStyle

GAMEDEV_PROMPTS = [
    "medieval village on a hill",
    "alpine valley with a river",
    "desert canyon",
]


def _offline_config(res: int = 64) -> Config:
    cfg = Config()
    cfg.parser_backend = "rule"
    cfg.terrain_resolution = res
    return cfg


def _glb_primitive_attributes(path: str) -> list[list[str]]:
    data = open(path, "rb").read()
    json_len = struct.unpack("<I", data[12:16])[0]
    gltf = json.loads(data[20 : 20 + json_len])
    return [
        list(prim["attributes"].keys())
        for mesh in gltf.get("meshes", [])
        for prim in mesh["primitives"]
    ]


def test_rule_parser_directions():
    spec = RuleParser(Config()).parse(
        "a coastal world with mountains to the north and a forest to the west"
    )
    dirs = {f.type: f.direction for f in spec.terrain.features}
    assert dirs[FeatureType.mountain] == Direction.north
    assert dirs[FeatureType.forest] == Direction.west


def test_offline_pipeline_exports_all_formats():
    cfg = _offline_config(48)
    with tempfile.TemporaryDirectory() as d:
        res = Pipeline(config=cfg).run(
            "a fantasy valley with a lake in the center",
            out_dir=d, formats=["glb", "obj", "stl"], basename="t",
        )
        for fmt in ("glb", "obj", "stl"):
            assert fmt in res.files and os.path.getsize(res.files[fmt]) > 0
        assert res.build.stats["terrain_faces"] > 0


def test_exported_files_carry_normals():
    cfg = _offline_config()
    for prompt in GAMEDEV_PROMPTS:
        with tempfile.TemporaryDirectory() as d:
            res = Pipeline(config=cfg).run(prompt, out_dir=d, formats=["glb", "obj"], basename="t")
            attrs = _glb_primitive_attributes(res.files["glb"])
            assert attrs, f"{prompt!r}: GLB had no mesh primitives"
            assert all("NORMAL" in a for a in attrs), f"{prompt!r}: missing NORMAL ({attrs})"
            assert "\nvn " in open(res.files["obj"]).read(), f"{prompt!r}: OBJ has no normals"


def test_river_prompt_produces_water():
    cfg = _offline_config()
    for prompt in ("alpine valley with a river", "a world with a wide river"):
        with tempfile.TemporaryDirectory() as d:
            res = Pipeline(config=cfg).run(prompt, out_dir=d, formats=["glb"], basename="t")
            assert res.build.stats.get("water"), f"{prompt!r}: no water generated"
            assert res.build.heightfield.sea_level is not None


def test_meshes_are_clean():
    cfg = _offline_config()
    for prompt in GAMEDEV_PROMPTS:
        res = Pipeline(config=cfg).run(prompt, out_dir=tempfile.mkdtemp(), basename="t")
        for name, g in res.build.scene.geometry.items():
            if not isinstance(g, trimesh.Trimesh):
                continue
            assert not np.isnan(g.vertices).any(), f"{prompt!r}/{name}: NaN vertices"
            tri = g.vertices[g.faces]
            area = 0.5 * np.linalg.norm(
                np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0]), axis=1
            )
            assert not (area < 1e-9).any(), f"{prompt!r}/{name}: degenerate faces"


def test_determinism_same_seed_same_geometry():
    cfg = _offline_config(48)
    a = Pipeline(config=cfg).run("a fantasy hill", out_dir=tempfile.mkdtemp(), basename="t")
    b = Pipeline(config=cfg).run("a fantasy hill", out_dir=tempfile.mkdtemp(), basename="t")
    ga = a.build.scene.geometry["terrain"]
    gb = b.build.scene.geometry["terrain"]
    np.testing.assert_allclose(ga.vertices, gb.vertices)
