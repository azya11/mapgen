"""Concrete exporters. trimesh handles GLB / OBJ / STL natively; the Blender
script is generated from the scene so it can be rebuilt with Cycles materials."""

from __future__ import annotations

from pathlib import Path

import trimesh

from .blender import write_blender_script

FORMATS = ("glb", "obj", "stl", "blender")


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
            scene.export(p.as_posix())
            written["glb"] = str(p)
        elif fmt == "obj":
            p = out_dir / f"{basename}.obj"
            # trimesh writes a sibling .mtl for the materials automatically.
            scene.export(p.as_posix())
            written["obj"] = str(p)
        elif fmt == "stl":
            p = out_dir / f"{basename}.stl"
            # STL has no scene graph or colour: merge to a single mesh.
            mesh = _to_single_mesh(scene)
            mesh.export(p.as_posix())
            written["stl"] = str(p)
        elif fmt == "blender":
            p = out_dir / f"{basename}_blender.py"
            glb = written.get("glb")
            if glb is None:
                glb_path = out_dir / f"{basename}.glb"
                scene.export(glb_path.as_posix())
                glb = str(glb_path)
                written["glb"] = glb
            write_blender_script(p, Path(glb).name, basename)
            written["blender"] = str(p)
        else:
            raise ValueError(f"Unknown format: {fmt!r}. Choose from {FORMATS}.")

    return written


def _to_single_mesh(scene: trimesh.Scene) -> trimesh.Trimesh:
    geoms = [g for g in scene.dump() if isinstance(g, trimesh.Trimesh)]
    if not geoms:
        raise RuntimeError("Scene has no mesh geometry to export.")
    return trimesh.util.concatenate(geoms)
