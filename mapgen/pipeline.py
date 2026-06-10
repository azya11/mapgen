"""The end-to-end pipeline: prompt -> WorldSpec -> procedural scene -> files."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .config import Config
from .export import export_all
from .generate import build_scene
from .generate.scene import SceneBuildResult
from .parser import make_parser
from .spec import WorldSpec


@dataclass
class PipelineResult:
    prompt: str
    spec: WorldSpec
    build: SceneBuildResult
    files: dict[str, str]
    timings: dict[str, float] = field(default_factory=dict)

    def summary(self) -> str:
        s = self.spec
        lines = [
            f"Prompt   : {self.prompt}",
            f"World    : {s.name}",
            f"Style    : {s.world_style.value}   extent: {s.extent_m} m",
            f"Features : {', '.join(self._feat()) or '(none)'}",
            f"Props    : {sum(p.count for p in s.props)} ({len(s.props)} intents)",
            f"Geometry : {self.build.stats}",
            "Files    :",
        ]
        for fmt, path in self.files.items():
            lines.append(f"           - {fmt:8s} {path}")
        return "\n".join(lines)

    def _feat(self) -> list[str]:
        out = []
        for f in self.spec.terrain.features:
            d = f.direction.value if f.direction else "-"
            out.append(f"{f.type.value}@{d}")
        return out


def _slugify(text: str) -> str:
    s = re.sub(r"[^\w\s-]", "", text.lower()).strip()
    s = re.sub(r"[\s_-]+", "-", s)
    return s[:48] or "world"


class Pipeline:
    def __init__(self, config: Config | None = None,
                 log: Callable[[str], None] | None = None):
        self.config = config or Config.from_env()
        self._log = log or (lambda m: None)

    def run(
        self,
        prompt: str,
        out_dir: str | Path = "output",
        formats: list[str] | None = None,
        basename: str | None = None,
        overrides: dict | None = None,
    ) -> PipelineResult:
        formats = formats or ["glb", "obj", "stl"]
        overrides = overrides or {}
        timings: dict[str, float] = {}

        # 1) PARSE
        t = time.time()
        parser = make_parser(self.config)
        self._log(f"[1/3] Parsing prompt with {parser.name} ...")
        try:
            spec = parser.parse(prompt)
        except Exception as e:
            self._log(f"      {parser.name} failed ({e!r}); falling back to rule parser.")
            from .parser.rule_parser import RuleParser
            spec = RuleParser(self.config).parse(prompt)
        timings["parse"] = time.time() - t

        # Overrides (host caps / explicit values win over the parser).
        if overrides.get("extent_m"):
            spec.extent_m = float(overrides["extent_m"])
        cap = overrides.get("max_extent_m")
        if cap:
            spec.extent_m = min(spec.extent_m, float(cap))
        if overrides.get("world_style"):
            spec.world_style = overrides["world_style"]
        if overrides.get("seed") is not None:
            spec.seed = int(overrides["seed"])

        self._log(
            f"      -> {spec.name!r} | {spec.world_style.value} | "
            f"{len(spec.terrain.features)} features | {len(spec.props)} prop intents"
        )

        # 2) BUILD
        t = time.time()
        self._log("[2/3] Building 3D geometry ...")
        build = build_scene(spec, self.config)
        timings["build"] = time.time() - t
        self._log(f"      -> {build.stats}")

        # 3) EXPORT
        t = time.time()
        base = basename or _slugify(spec.name)
        self._log(f"[3/3] Exporting {formats} -> {out_dir}/ ...")
        files = export_all(build.scene, out_dir, base, formats)
        timings["export"] = time.time() - t

        return PipelineResult(
            prompt=prompt, spec=spec, build=build, files=files, timings=timings
        )
