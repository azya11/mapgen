# mapgen — prompt → 3D map pipeline

[![CI](https://github.com/azya11/mapgen/actions/workflows/ci.yml/badge.svg)](https://github.com/azya11/mapgen/actions/workflows/ci.yml)
[![License: Proprietary](https://img.shields.io/badge/License-Proprietary%20%C2%B7%20All%20rights%20reserved-red.svg)](LICENSE)

> © 2026 Aziz. All rights reserved. This source is public for viewing only —
> no use, copying, modification, or distribution is permitted without written consent.

An AI pipeline that turns a natural-language prompt describing a **location, its
surroundings, and the kind of map** you want into **3D models and files ready for
rendering** (glTF/GLB, OBJ+MTL, STL, and a runnable Blender script).

```
prompt ─▶ [1 Parse]  Claude tool-use ─▶ validated SceneSpec (JSON)
       ─▶ [2 Resolve] geocode → real? OSM buildings + elevation : procedural
       ─▶ [3 Build]   terrain mesh + water + buildings → trimesh.Scene
       ─▶ [4 Export]  GLB · OBJ+MTL · STL · Blender .py
```

It ships both as a **CLI** and as a **secure web app** with accounts and a free
2-generation quota (see [Web app](#web-app)).

It is **hybrid**: recognised real places are built from real OpenStreetMap
building footprints and Open-Meteo elevation data; fictional or unrecognised
places are generated procedurally from the parsed description.

## Live Demo And Walkthrough

Production link: https://mapgen-zeta.vercel.app/

The screenshots below show one real generation run from the live app, from the
empty studio state through the generated map views and the Google Maps
reference capture used for comparison.

1. [Empty app shell](01-empty-app-shell.png) — the studio before a run starts.
2. [Fetching real-world data](02-fetching-real-world-data.png) — the app is
pulling geocode, OSM, and elevation data.
3. [Loading model](03-loading-model.png) — the 3D model is being prepared for
display.
4. [Generated terrain overview](04-generated-terrain-overview.png) — first
oblique view of the finished map.
5. [Generated wireframe overview](05-generated-wireframe-overview.png) — a mesh
inspection view that makes the geometry easier to read.
6. [Generated colorized overview](06-generated-colorized-overview.png) — the
same map with the styled surface shading enabled.
7. [Red style overview](07-red-style-overview.png) — an alternate styled pass
showing the same area with a different color treatment.
8. [Measurement view](08-measurement-view.png) — a guided inspection view that
highlights a measured path across the map.
9. [Close-up inspection](09-close-up-inspection.png) — a tighter look at local
terrain and building detail.
10. [Guided line view](10-guided-line-view.png) — another measurement-oriented
angle from the run.
11. [Top-down wireframe](11-top-down-wireframe.png) — an overhead geometry
check.
12. [Google Maps reference](12-google-maps-reference.png) — the source
reference capture used alongside the generated result.

## Install

```powershell
python -m venv .venv
# CLI / full local app needs the heavy 3D pipeline deps too:
.\.venv\Scripts\python.exe -m pip install -r requirements.txt -r requirements-mapgen.txt
```

> Dependencies are split: `requirements.txt` is the light web/API set (kept
> small enough for serverless), and `requirements-mapgen.txt` is the heavy 3D
> pipeline (numpy/scipy/trimesh/shapely) used by the CLI and the generation
> worker. See [DEPLOY.md](DEPLOY.md) to host the web app **free** on Vercel +
> a free worker.

Set an Anthropic API key to enable the high-quality Claude parser (optional —
the pipeline runs fully offline with a rule-based fallback):

```powershell
$env:ANTHROPIC_API_KEY = "sk-ant-..."
```

## Usage

```powershell
# Real location — pulls real OSM buildings + elevation
python cli.py "downtown San Francisco with steep hills, city map"

# Fictional — fully procedural
python cli.py "a fantasy coastal town with towering mountains to the north and a forest to the west"

# Pick formats and force offline (no network, no API key)
python cli.py "a desert canyon with a river" --offline --formats glb stl

# Inspect the structured spec Claude/the parser produced
python cli.py "Kyoto temple district, schematic map" --json
```

Outputs land in `output/` (override with `--out`). Each run writes the requested
formats, e.g. `san-francisco.glb`, `.obj`, `.stl`, and `san-francisco_blender.py`.

### CLI options

| flag | meaning |
|------|---------|
| `--out DIR` | output directory (default `output`) |
| `--formats ...` | any of `glb obj stl blender` (default: all) |
| `--name NAME` | output basename (default: derived from location) |
| `--parser auto\|claude\|rule` | parser backend (default `auto`: Claude if key present, else rule) |
| `--model ID` | override Claude model (default `claude-sonnet-4-6`) |
| `--offline` | disable all network → rule parser + procedural geometry |
| `--resolution N` | terrain grid cells per side (default 96) |
| `--seed N` | procedural RNG seed |
| `--json` | also print the SceneSpec JSON |
| `--location "PLACE"` | **force** a real place to geocode (implies real-world data) |
| `--real` / `--procedural` | force real-world data / force procedural, overriding the prompt |
| `--extent KM` | override the modeled area side length in km |

### Forcing real-world data

The pipeline uses real OpenStreetMap buildings + elevation whenever the prompt
names a real, geocodable place. The offline **rule parser** recognises phrasings
like `map of <place>`, `in/near <place>`, and `city, country` (case-insensitive),
and treats `1:1`, `realistic`, `satellite`, etc. as real-world intent. If a prompt
is ambiguous, force it explicitly:

```powershell
python cli.py "1:1 map of uralsk, kazakhstan with terrain and building heights" --location "Uralsk, Kazakhstan" --extent 8
```

For the most reliable place/feature extraction, set `ANTHROPIC_API_KEY` to use the
Claude parser. Building heights come from OSM `height` / `building:levels` tags;
terrain comes from real elevation data.

## How each stage works

1. **Parse** (`mapgen/parser`). The `ClaudeParser` uses Anthropic **tool-use** to
   force the model to emit a structured `SceneSpec` (location, real-vs-fictional,
   map style, extent in km, and a list of directional features). The tool schema
   is kept in lock-step with the Pydantic model, and the system prompt is
   prompt-cached. An offline `RuleParser` provides a keyword/regex fallback.
2. **Resolve** (`mapgen/geo`). Real locations are geocoded (Nominatim), then a
   square bbox of the requested extent is used to fetch building footprints +
   roads (Overpass, with mirror fallback) and an elevation grid (Open-Meteo, with
   rate-limit backoff). Any failure degrades gracefully to procedural.
3. **Build** (`mapgen/generate`). A heightfield (real elevation or fBm noise
   shaped by the features and their compass directions) is triangulated; water
   planes, real OSM building extrusions, or procedural city blocks are added;
   the mesh is colour-graded by map style.
4. **Export** (`mapgen/export`). `trimesh` writes GLB / OBJ / STL; a standalone
   Blender script imports the GLB, frames a camera, adds a sun, and renders with
   Cycles.

## Output formats

| format | notes |
|--------|-------|
| **GLB** | self-contained, with colours; best for web/three.js, game engines, Windows 3D Viewer |
| **OBJ** | colours stored **per-vertex inline** (the correct representation for a colour-graded heightfield); a sibling `.mtl` is written when single-material meshes are present |
| **STL** | geometry only, single merged mesh — for 3D printing |
| **Blender** | `*_blender.py`; run `blender --background --python <file>` to render a PNG |

## Render the Blender output

```powershell
blender --background --python output\san-francisco_blender.py
# writes output\san-francisco_render.png
```

## Web app

A hardened FastAPI web app that lets registered users generate maps in the
browser, with a free **2-generations-per-account** quota (no payment system).

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt -r requirements-mapgen.txt
.\.venv\Scripts\python.exe run_web.py          # http://127.0.0.1:8000
```

To **host it for free**, the app can split into a Vercel frontend (free) + a
free always-on generation worker — see [DEPLOY.md](DEPLOY.md).

Open the URL, create an account, and generate from the in-browser studio with a
live three.js viewer (sky, sun shadows, reflections) and GLB/OBJ/STL downloads.

**Frontend** — aurora-glass design system (Space Grotesk / Inter / JetBrains
Mono), animated landing page, auth screens, and a generator with a real-time 3D
viewer and usage meter.

**Security (defense in depth)**

| Area | Measure |
|------|---------|
| Passwords | Argon2id hashing; constant-time verify with dummy hash to stop user-enumeration timing |
| Sessions | 256-bit random tokens stored **hashed** (SHA-256); httpOnly + `SameSite=Strict` cookies; server-side expiry |
| CSRF | Per-session token (synchronizer) required on state-changing requests + same-origin check |
| Brute force | Per-IP sliding-window rate limits + account lockout after repeated failures |
| Headers | Strict CSP with per-response **nonces** (no `unsafe-inline` scripts), HSTS, `frame-ancestors 'none'`, `nosniff`, Referrer-/Permissions-Policy, COOP/CORP |
| Quota | Enforced server-side with atomic reserve/refund (no race double-spend) |
| Injection | SQLAlchemy ORM (bound params) only; no string SQL |
| Files | Served owner-only by random UUID; filename whitelist; path-traversal guard |
| Abuse | Generation runs in a bounded threadpool with capped extent/resolution and a hard timeout |
| Errors | Generic client messages; internal details never leaked |

**Production notes** — run behind a TLS reverse proxy and set
`WEB_SECRET_KEY`, `WEB_COOKIE_SECURE=1` (enables Secure cookies + HSTS), and
`WEB_TRUST_PROXY=1`. Set `ANTHROPIC_API_KEY` to use the Claude parser. The free
quota and limits are configurable via `WEB_*` env vars (see `web/config.py`).

## Tests

```powershell
.\.venv\Scripts\python.exe tests\test_pipeline.py
```

## Notes & limits

- The **rule parser** is a best-effort offline heuristic; for accurate location
  and feature extraction (e.g. "Chamonix" vs "the French Alps") use the **Claude
  parser** by setting `ANTHROPIC_API_KEY`.
- Real-data APIs are free and keyless but rate-limited; large city extents pull
  many buildings (San Francisco at 12 km ≈ 85k footprints) and produce large
  files — lower `--resolution` or extent for quick iteration.
