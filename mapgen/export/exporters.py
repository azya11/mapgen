"""Concrete exporters. trimesh handles GLB / OBJ / STL natively."""

from __future__ import annotations

from pathlib import Path

import trimesh

FORMATS = ("glb", "obj", "stl")


def export_all(
    scene: trimesh.Scene,
    out_dir: str | Path,
    basename: str,
    formats: list[str],
) -> dict[str, str]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    written: dict[str, str] = {}

    for fmt in formats:
        fmt = fmt.lower()
        if fmt == "glb":
            p = out_dir / f"{basename}.glb"
            # include_normals=True forces the NORMAL accessor into the file so
            # downstream engines/DCC tools don't import flat-shaded geometry.
            scene.export(p.as_posix(), include_normals=True)
            written["glb"] = str(p)
        elif fmt == "obj":
            p = out_dir / f"{basename}.obj"
            # trimesh writes a sibling .mtl for the materials automatically;
            # include_normals=True emits `vn` lines so the OBJ shades correctly.
            scene.export(p.as_posix(), include_normals=True)
            written["obj"] = str(p)
        elif fmt == "stl":
            p = out_dir / f"{basename}.stl"
            # STL has no scene graph or colour: merge to a single mesh.
            mesh = _to_single_mesh(scene)
            mesh.export(p.as_posix())
            written["stl"] = str(p)
        else:
            raise ValueError(f"Unknown format: {fmt!r}. Choose from {FORMATS}.")

    return written


def _to_single_mesh(scene: trimesh.Scene) -> trimesh.Trimesh:
    geoms = [g for g in scene.dump() if isinstance(g, trimesh.Trimesh)]
    if not geoms:
        raise RuntimeError("Scene has no mesh geometry to export.")
    return trimesh.util.concatenate(geoms)
