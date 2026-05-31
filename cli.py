#!/usr/bin/env python
"""Command-line entry point for the mapgen pipeline.

Examples:
    python cli.py "a coastal town near Nice with mountains to the north, terrain map"
    python cli.py "downtown Manhattan, city map" --formats glb obj
    python cli.py "a fantasy valley between two volcanoes" --offline --out renders
"""

from __future__ import annotations

import argparse
import sys

from mapgen import Pipeline
from mapgen.config import Config
from mapgen.export import FORMATS

# The themed output uses Unicode glyphs; force UTF-8 so Windows' default
# cp1252 console encoding doesn't choke on them.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="mapgen",
        description="Turn a natural-language place description into 3D map files.",
    )
    ap.add_argument("prompt", help="Description of the location, surroundings, and map type.")
    ap.add_argument("--out", default="output", help="Output directory (default: output).")
    ap.add_argument(
        "--formats", nargs="+", default=["glb", "obj", "stl", "blender"],
        metavar="FMT", help=f"Any of: {', '.join(FORMATS)}.",
    )
    ap.add_argument("--name", default=None, help="Output basename (default: from location).")
    ap.add_argument("--parser", choices=["auto", "claude", "rule"], default=None,
                    help="Override parser backend (default: auto).")
    ap.add_argument("--model", default=None, help="Override Claude model id.")
    ap.add_argument("--offline", action="store_true",
                    help="Disable all network (rule parser + procedural geometry).")
    ap.add_argument("--resolution", type=int, default=None,
                    help="Terrain grid resolution per side (default 96).")
    ap.add_argument("--seed", type=int, default=None, help="Procedural seed.")
    ap.add_argument("--json", action="store_true", help="Also print the SceneSpec as JSON.")
    # --- explicit real-world overrides (win over prompt parsing) ---
    ap.add_argument("--location", default=None, metavar="PLACE",
                    help="Force a real place to geocode, e.g. --location \"Uralsk, Kazakhstan\". "
                         "Implies real-world data.")
    ap.add_argument("--real", dest="real", action="store_true", default=None,
                    help="Force real-world data (geocode + OSM buildings + elevation).")
    ap.add_argument("--procedural", dest="real", action="store_false",
                    help="Force procedural generation, ignoring any real place.")
    ap.add_argument("--extent", type=float, default=None, metavar="KM",
                    help="Override the area side length in km (e.g. --extent 6).")
    args = ap.parse_args(argv)

    bad = [f for f in args.formats if f.lower() not in FORMATS]
    if bad:
        ap.error(f"unknown format(s): {bad}. Choose from {FORMATS}.")

    config = Config.from_env()
    if args.parser:
        config.parser_backend = args.parser
    if args.model:
        config.model = args.model
    if args.offline:
        config.use_network = False
        if config.parser_backend == "auto":
            config.parser_backend = "rule"
    if args.resolution:
        config.terrain_resolution = args.resolution
    if args.seed is not None:
        config.seed = args.seed

    from mapgen import style as S

    print(S.banner(), file=sys.stderr)
    pipe = Pipeline(config=config, log=lambda m: print(S.stage(m), file=sys.stderr))

    overrides = {
        "location": args.location,
        "force_real": args.real,
        "extent_km": args.extent,
    }
    try:
        result = pipe.run(
            args.prompt, out_dir=args.out, formats=args.formats,
            basename=args.name, overrides=overrides,
        )
    except Exception as exc:  # noqa: BLE001
        print(S.c(f"\n✗ ERROR: {exc}", S.WARN, bold=True), file=sys.stderr)
        return 1

    print(_styled_summary(result, S))
    if args.json:
        print(S.c("\nSceneSpec JSON:", S.VIOLET, bold=True))
        print(S.DIM + result.spec.model_dump_json(indent=2) + S.RESET)
    return 0


def _styled_summary(result, S) -> str:
    """Render the run summary with the cyan→violet theme."""
    spec, build = result.spec, result.build
    bar = S.c("─" * 52, S.MUTED)
    rows = [
        ("Prompt", result.prompt),
        ("Location", f"{spec.location}  ({'real' if spec.is_real_location else 'procedural'})"),
        ("Style", f"{spec.map_style.value}   ·   extent {spec.extent_km} km"),
        ("Features", ", ".join(result._feat()) or "(none)"),
        ("Terrain", "real elevation" if build.used_real_data else "procedural"),
        ("Buildings", str(build.stats.get("buildings_source", "none"))),
    ]
    if build.stats.get("trees"):
        rows.append(("Forest", f"{build.stats['trees']} trees"))

    out = ["", S.c("  ✦ scene generated", S.AQUA, bold=True), bar]
    for k, v in rows:
        out.append(f"  {S.c(f'{k:9}', S.BLUE)} {S.c(str(v), S.TXT)}")
    out.append(bar)
    out.append(f"  {S.c('files', S.VIOLET, bold=True)}")
    for fmt, path in result.files.items():
        out.append(f"    {S.c('›', S.AQUA)} {S.c(f'{fmt:8}', S.MUTED)} {S.c(path, S.TXT)}")
    out.append("")
    out.append(S.c("  view → ", S.MUTED) + S.c("http://127.0.0.1:8000/viewer.html", S.AQUA))
    return "\n".join(out)


if __name__ == "__main__":
    raise SystemExit(main())
