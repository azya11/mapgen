"""Assemble the final trimesh.Scene from terrain + water, applying a colour
palette chosen by the world style. The result is renderer-agnostic and
exported by the export layer."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import trimesh

from ..config import Config
from ..spec import WorldSpec, WorldStyle
from . import terrain as terr
from .terrain import Heightfield


@dataclass
class SceneBuildResult:
    scene: trimesh.Scene
    heightfield: Heightfield
    stats: dict = field(default_factory=dict)


# Named albedo colours (lighting/shadows are added by the renderer, so these
# are flat surface colours, not pre-shaded).
_C = {
    "water":   (54, 104, 150),
    "sand":    (210, 196, 150),
    "grass":   (96, 132, 74),
    "grass_hi":(120, 148, 92),
    "rock":    (122, 112, 99),
    "rock_dk": (92, 84, 75),
    "snow":    (240, 243, 250),
    "building":(206, 205, 200),
}

# Per-style water colours and a relief feel.
_STYLE = {
    WorldStyle.lowpoly_nature: dict(water=(54, 104, 150)),
    WorldStyle.alpine:         dict(water=(70, 120, 170), contours=True),
    WorldStyle.urban:          dict(water=(70, 110, 150)),
    WorldStyle.desert:         dict(water=(40, 86, 132)),
    WorldStyle.schematic:      dict(water=(170, 205, 235), flat=True),
    WorldStyle.fantasy:        dict(water=(40, 110, 150), vivid=True),
    WorldStyle.minimal:        dict(water=(185, 195, 205), gray=True),
}


def _style(style: WorldStyle) -> dict:
    return _STYLE.get(style, _STYLE[WorldStyle.lowpoly_nature])


def _terrain_colors(hf: Heightfield, style: WorldStyle) -> np.ndarray:
    """Natural elevation/slope-based albedo: beach near water, grass on gentle
    low land, rock on steep/high ground, snow on high gentle peaks, with optional
    contour banding for topographic and flat/gray treatments for other styles."""
    z = hf.z
    res = hf.res
    dx = hf.size_m / max(res - 1, 1)
    cfg = _style(style)

    dzdx, dzdy = np.gradient(z, dx)
    slope_deg = np.degrees(np.arctan(np.hypot(dzdx, dzdy)))
    zmin = float(z.min())
    relief = max(hf.relief, 1e-6)
    t = (z - zmin) / relief

    if cfg.get("gray"):
        v = (0.5 + 0.45 * t) * 255.0
        rgb = np.stack([v, v, v], axis=-1)
    elif cfg.get("flat"):
        lo = np.array([224, 226, 221], float)
        hi = np.array([196, 206, 188], float)
        rgb = lo[None, None] * (1 - t[..., None]) + hi[None, None] * t[..., None]
    else:
        grass = _blend(_C["grass"], _C["grass_hi"], np.clip(t / 0.5, 0, 1))
        rock = np.array(_C["rock"], float)
        snow = np.array(_C["snow"], float)

        # rockiness from slope and from altitude
        rockiness = np.clip((slope_deg - 24) / 26, 0, 1)
        rockiness = np.maximum(rockiness, np.clip((t - 0.55) / 0.3, 0, 1) * 0.75)
        rgb = grass * (1 - rockiness[..., None]) + rock[None, None] * rockiness[..., None]

        # snow on high, gentle ground — only for scenes with real relief
        if relief > 140:
            snow_amt = np.clip((t - 0.72) / 0.16, 0, 1) * np.clip(1 - (slope_deg - 40) / 30, 0, 1)
            rgb = rgb * (1 - snow_amt[..., None]) + snow[None, None] * snow_amt[..., None]

        # beach band just above the waterline
        if hf.sea_level is not None:
            beach = np.clip(1 - (z - hf.sea_level) / 6.0, 0, 1) * (z > hf.sea_level)
            sand = np.array(_C["sand"], float)
            rgb = rgb * (1 - beach[..., None]) + sand[None, None] * beach[..., None]

        if cfg.get("vivid"):
            rgb = np.clip((rgb - 128) * 1.18 + 128 + 6, 0, 255)

    # contour lines (albedo darkening) for topographic style
    if cfg.get("contours"):
        interval = max(5.0, round(relief / 14.0))
        phase = (z - zmin) / interval
        line = np.abs(phase - np.round(phase))
        on_line = np.clip(1 - line / 0.05, 0, 1)
        rgb = rgb * (1 - 0.4 * on_line[..., None])

    rgba = np.empty((res * res, 4))
    rgba[:, :3] = rgb.reshape(-1, 3)
    rgba[:, 3] = 255

    if hf.sea_level is not None:
        under = (z.ravel() <= hf.sea_level)
        rgba[under, :3] = np.array(cfg["water"], float)

    return np.clip(rgba, 0, 255).astype(np.uint8)


def _blend(a, b, t):
    a = np.array(a, float); b = np.array(b, float)
    return a[None, None] * (1 - t[..., None]) + b[None, None] * t[..., None]


def _ensure_normals(mesh: trimesh.Trimesh, crisp: bool = False) -> trimesh.Trimesh:
    """Compute and cache vertex normals so the exporters emit a NORMAL accessor.

    Without normals in the file, game engines and DCC tools (Unity, Unreal,
    Godot, Blender) import the mesh flat-/black-shaded or have to regenerate
    normals themselves — the exported model is the product here, so it must
    carry them. `crisp` unmerges shared vertices first so faceted geometry
    (buildings) keeps hard edges instead of being smoothed into blobs; smooth
    surfaces (terrain) keep shared vertices so hills shade continuously."""
    if crisp:
        mesh.unmerge_vertices()
    # Accessing the property triggers the (cached) computation that the GLB/OBJ
    # exporters then pick up.
    _ = mesh.vertex_normals
    return mesh


def _water_plane(hf: Heightfield, style: WorldStyle) -> trimesh.Trimesh | None:
    if hf.sea_level is None:
        return None
    plane = trimesh.creation.box(extents=[hf.size_m * 1.04, hf.size_m * 1.04, 0.1])
    plane.apply_translation([0, 0, hf.sea_level + 0.2])
    water_rgb = _style(style)["water"]
    plane.visual.face_colors = np.array([*water_rgb, 150], np.uint8)
    return plane


def build_scene(spec: WorldSpec, config: Config) -> SceneBuildResult:
    res = config.terrain_resolution
    hf = terr.procedural(spec, res, spec.seed)

    verts, faces = terr.heightfield_to_mesh(hf)
    ground = trimesh.Trimesh(vertices=verts, faces=faces, process=False)
    ground.visual.vertex_colors = _terrain_colors(hf, spec.world_style)
    _ensure_normals(ground)

    scene = trimesh.Scene()
    scene.add_geometry(ground, geom_name="terrain")

    stats = {
        "terrain_vertices": int(len(verts)),
        "terrain_faces": int(len(faces)),
        "relief_m": round(hf.relief, 1),
        "prop_intents": len(spec.props),  # placement lands props in M2
    }

    water = _water_plane(hf, spec.world_style)
    if water is not None:
        _ensure_normals(water)
        scene.add_geometry(water, geom_name="water")
        stats["water"] = True

    return SceneBuildResult(scene=scene, heightfield=hf, stats=stats)
