"""Assemble the final trimesh.Scene from terrain + water + buildings, applying
a colour palette chosen by the map style. The result is renderer-agnostic and
exported by the export layer."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import trimesh

from ..config import Config
from ..geo.geocode import BBox
from ..geo.osm import OSMData
from ..spec import MapStyle, SceneSpec
from . import buildings as bld
from . import terrain as terr
from . import vegetation as veg
from .terrain import Heightfield


@dataclass
class SceneBuildResult:
    scene: trimesh.Scene
    heightfield: Heightfield
    used_real_data: bool
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

# Per-style water + building base colours and a relief feel.
_STYLE = {
    MapStyle.terrain:     dict(building=(208, 206, 200), water=(54, 104, 150)),
    MapStyle.topographic: dict(building=(214, 214, 214), water=(70, 120, 170), contours=True),
    MapStyle.satellite:   dict(building=(168, 166, 160), water=(40, 86, 132)),
    MapStyle.city:        dict(building=(224, 226, 230), water=(70, 110, 150)),
    MapStyle.schematic:   dict(building=(124, 134, 150), water=(170, 205, 235), flat=True),
    MapStyle.fantasy:     dict(building=(186, 166, 134), water=(40, 110, 150), vivid=True),
    MapStyle.minimal:     dict(building=(165, 165, 165), water=(185, 195, 205), gray=True),
}


def _style(style: MapStyle) -> dict:
    return _STYLE.get(style, _STYLE[MapStyle.terrain])


def _terrain_colors(hf: Heightfield, style: MapStyle) -> np.ndarray:
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


def _water_plane(hf: Heightfield, style: MapStyle) -> trimesh.Trimesh | None:
    if hf.sea_level is None:
        return None
    plane = trimesh.creation.box(extents=[hf.size_m * 1.04, hf.size_m * 1.04, 0.1])
    plane.apply_translation([0, 0, hf.sea_level + 0.2])
    water_rgb = _style(style)["water"]
    plane.visual.face_colors = np.array([*water_rgb, 150], np.uint8)
    return plane


def _building_colors(mesh: trimesh.Trimesh, base_rgb) -> np.ndarray:
    """Grade building faces by height so roofs read lighter than walls, with a
    little per-face jitter so a dense city isn't one flat slab of colour."""
    base = np.array(base_rgb, float)
    zc = mesh.triangles_center[:, 2]
    z0, z1 = float(zc.min()), float(zc.max())
    t = (zc - z0) / max(z1 - z0, 1e-6)
    shade = (0.78 + 0.32 * t)[:, None]          # taller -> lighter
    rng = np.random.default_rng(12345)
    jitter = rng.uniform(-10, 10, (len(zc), 1))
    cols = np.clip(base[None, :] * shade + jitter, 30, 255)
    rgba = np.empty((len(zc), 4))
    rgba[:, :3] = cols
    rgba[:, 3] = 255
    return rgba.astype(np.uint8)


def build_scene(
    spec: SceneSpec,
    config: Config,
    bbox: BBox | None,
    elevation: np.ndarray | None,
    osm: OSMData | None,
) -> SceneBuildResult:
    res = config.terrain_resolution
    used_real = False

    # ---- terrain heightfield ----
    if elevation is not None and bbox is not None:
        hf = terr.from_elevation(elevation, bbox.extent_km * 1000.0, spec)
        used_real = True
    else:
        hf = terr.procedural(spec, res, config.seed)

    verts, faces = terr.heightfield_to_mesh(hf)
    ground = trimesh.Trimesh(vertices=verts, faces=faces, process=False)
    ground.visual.vertex_colors = _terrain_colors(hf, spec.map_style)

    scene = trimesh.Scene()
    scene.add_geometry(ground, geom_name="terrain")

    stats = {
        "terrain_vertices": int(len(verts)),
        "terrain_faces": int(len(faces)),
        "relief_m": round(hf.relief, 1),
    }

    # ---- water ----
    water = _water_plane(hf, spec.map_style)
    if water is not None:
        scene.add_geometry(water, geom_name="water")
        stats["water"] = True

    # ---- buildings ----
    building_mesh = None
    if osm is not None and bbox is not None and osm.buildings:
        building_mesh = bld.from_osm(osm, bbox, hf)
        if building_mesh is not None:
            stats["buildings_source"] = "osm"
            stats["building_count"] = len(osm.buildings)
            if osm.fetched_extent_km and osm.fetched_extent_km < spec.extent_km - 0.05:
                stats["buildings_extent_km"] = round(osm.fetched_extent_km, 1)
    if building_mesh is None:
        building_mesh = bld.procedural(spec, hf, config.seed)
        if building_mesh is not None:
            stats["buildings_source"] = "procedural"

    if building_mesh is not None:
        b_rgb = _style(spec.map_style)["building"]
        building_mesh.visual.face_colors = _building_colors(building_mesh, b_rgb)
        scene.add_geometry(building_mesh, geom_name="buildings")

    # ---- vegetation (procedural forests/parks) ----
    forest_mesh = veg.forests(spec, hf, config.seed)
    if forest_mesh is not None:
        scene.add_geometry(forest_mesh, geom_name="vegetation")
        stats["trees"] = int(len(forest_mesh.vertices) // 30)  # rough count

    return SceneBuildResult(
        scene=scene, heightfield=hf, used_real_data=used_real, stats=stats
    )
