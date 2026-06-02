"""The end-to-end pipeline: prompt -> SceneSpec -> geo/procedural -> scene -> files."""

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
from .geo import BBox, elevation_grid, fetch_osm, geocode
from .parser import make_parser
from .scale import scale_to_extent_km
from .spec import SceneSpec


@dataclass
class PipelineResult:
    prompt: str
    spec: SceneSpec
    build: SceneBuildResult
    files: dict[str, str]
    timings: dict[str, float] = field(default_factory=dict)
    # Geocoded centre of the modelled area (real locations only); enables a
    # true sun position from date/time in the viewer.
    lat: float | None = None
    lon: float | None = None

    def summary(self) -> str:
        lines = [
            f"Prompt   : {self.prompt}",
            f"Location : {self.spec.location} "
            f"({'real' if self.spec.is_real_location else 'procedural'})",
            f"Style    : {self.spec.map_style.value}   extent: {self.spec.extent_km} km",
            f"Features : {', '.join(self._feat()) or '(none)'}",
            f"Terrain  : {'real elevation' if self.build.used_real_data else 'procedural'}",
            f"Buildings: {self.build.stats.get('buildings_source', 'none')}",
            f"Geometry : {self.build.stats}",
            "Files    :",
        ]
        for fmt, path in self.files.items():
            lines.append(f"           - {fmt:8s} {path}")
        return "\n".join(lines)

    def _feat(self) -> list[str]:
        out = []
        for f in self.spec.features:
            d = f.direction.value if f.direction else "-"
            out.append(f"{f.type.value}@{d}")
        return out


def _slugify(text: str) -> str:
    s = re.sub(r"[^\w\s-]", "", text.lower()).strip()
    s = re.sub(r"[\s_-]+", "-", s)
    return s[:48] or "scene"


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
        formats = formats or ["glb", "obj", "stl", "blender"]
        overrides = overrides or {}
        timings: dict[str, float] = {}

        # 1) PARSE -----------------------------------------------------
        t = time.time()
        parser = make_parser(self.config)
        self._log(f"[1/4] Parsing prompt with {parser.name} ...")
        try:
            spec = parser.parse(prompt)
        except Exception as e:
            # A parser backend failure (e.g. Claude API key/access/network)
            # must never crash generation — degrade to the offline rule parser.
            self._log(f"      {parser.name} parser failed ({e!r}); falling back to rule parser.")
            from .parser.rule_parser import RuleParser
            spec = RuleParser(self.config).parse(prompt)
        timings["parse"] = time.time() - t

        # Explicit user overrides win over whatever the parser inferred.
        if overrides.get("location"):
            spec.location = overrides["location"]
            spec.is_real_location = True
        if overrides.get("force_real") is not None:
            spec.is_real_location = bool(overrides["force_real"])
        # Extent precedence: a "1:N" scale ratio in the prompt (ground coverage)
        # beats an explicit km value (e.g. the web slider), which beats the
        # parser's inference.
        scale_extent = scale_to_extent_km(prompt)
        if scale_extent is not None:
            spec.extent_km = scale_extent
        elif overrides.get("extent_km"):
            spec.extent_km = float(overrides["extent_km"])
        # Host-imposed ceiling (the worker caps the modelled area for resources).
        cap = overrides.get("max_extent_km")
        if cap:
            spec.extent_km = min(spec.extent_km, float(cap))
        if overrides.get("map_style"):
            spec.map_style = overrides["map_style"]
        if overrides:
            self._log(f"      (applied overrides: {sorted(k for k,v in overrides.items() if v is not None)})")

        self._log(
            f"      -> {spec.location!r} | {spec.map_style.value} | "
            f"{len(spec.features)} features | real={spec.is_real_location}"
        )

        # 2) RESOLVE GEO ----------------------------------------------
        t = time.time()
        bbox, elevation, osm = self._resolve_geo(spec)
        timings["geo"] = time.time() - t
        lat = bbox.center.lat if bbox is not None else None
        lon = bbox.center.lon if bbox is not None else None

        # 3) BUILD -----------------------------------------------------
        t = time.time()
        self._log("[3/4] Building 3D geometry ...")
        build = build_scene(spec, self.config, bbox, elevation, osm)
        timings["build"] = time.time() - t
        self._log(f"      -> {build.stats}")

        # 4) EXPORT ----------------------------------------------------
        t = time.time()
        base = basename or _slugify(spec.location)
        self._log(f"[4/4] Exporting {formats} -> {out_dir}/ ...")
        files = export_all(build.scene, out_dir, base, formats)
        timings["export"] = time.time() - t

        return PipelineResult(
            prompt=prompt, spec=spec, build=build, files=files, timings=timings,
            lat=lat, lon=lon,
        )

    # ------------------------------------------------------------------ #
    def _resolve_geo(self, spec: SceneSpec):
        """Returns (bbox, elevation_grid, osm) — any of which may be None,
        in which case the build falls back to procedural generation."""
        if not spec.is_real_location or not self.config.use_network:
            self._log("[2/4] Procedural mode (no geo lookup).")
            return None, None, None

        self._log(f"[2/4] Geocoding {spec.location!r} ...")
        point = geocode(spec.location, self.config)
        if point is None:
            self._log("      -> not found; falling back to procedural.")
            return None, None, None
        self._log(f"      -> {point.display_name} ({point.lat:.4f}, {point.lon:.4f})")

        bbox = BBox(center=point, extent_km=spec.extent_km)

        self._log("      fetching elevation grid ...")
        elevation = elevation_grid(bbox, self.config.terrain_resolution, self.config)
        self._log("      " + ("got elevation." if elevation is not None
                              else "no elevation; procedural relief."))

        osm = None
        if spec.map_style.value in ("city", "satellite", "schematic") or spec.features_of():
            pass  # always try buildings; cheap to skip if empty
        self._log("      fetching OSM buildings/roads ...")
        osm = fetch_osm(bbox, self.config)
        self._log("      " + (f"got {len(osm.buildings)} buildings."
                              if osm else "no OSM vectors."))

        return bbox, elevation, osm
