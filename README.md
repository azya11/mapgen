# mapgen — prompt → procedural 3D game world

[![CI](https://github.com/azya11/mapgen/actions/workflows/ci.yml/badge.svg)](https://github.com/azya11/mapgen/actions/workflows/ci.yml)
[![License: Proprietary](https://img.shields.io/badge/License-Proprietary%20%C2%B7%20All%20rights%20reserved-red.svg)](LICENSE)

> © 2026 Aziz. All rights reserved. This source is public for viewing only —
> no use, copying, modification, or distribution is permitted without written consent.

An AI pipeline that turns a natural-language prompt into a **low-poly procedural
3D game world** — terrain, water, and prop layout — exported to **glTF/GLB,
OBJ+MTL, and STL**, ready for rendering or import into any game engine.

```
prompt ─▶ [1 Parse]    Claude tool-use / RuleParser ─▶ validated WorldSpec (JSON)
       ─▶ [2 Build]    procedural heightfield + water plane ─▶ trimesh.Scene
       ─▶ [3 Export]   GLB · OBJ+MTL · STL

  Full M0–M4 design (5-stage):
  Parse → Plan → Build → Assemble → Export
         └─ prop placement ─────────────┘  ← M2 (not yet in scene)
```

It ships as both a **CLI** and a **secure web app** with accounts and a free
2-generation quota (see [Web app](#web-app)).

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
# Fantasy terrain with a lake — Claude parser if key is set, rule parser otherwise
python cli.py "a fantasy valley with a lake, forest to the west" --extent 400

# Alpine valley, GLB + STL only, custom terrain resolution
python cli.py "alpine valley with a river" --formats glb stl --resolution 80

# Force the offline rule parser and print the WorldSpec JSON
python cli.py "desert canyon" --parser rule --json

# Fix the RNG seed for reproducible output
python cli.py "snowy mountain pass" --seed 42 --out renders
```

Outputs land in `output/` (override with `--out`). Each run writes the
requested formats, e.g. `fantasy-valley.glb`, `.obj`, `.stl`.

### CLI options

| flag | meaning |
|------|---------|
| `--out DIR` | output directory (default `output`) |
| `--formats ...` | any of `glb obj stl` (default: all three) |
| `--name NAME` | output basename (default: derived from world name) |
| `--parser auto\|claude\|rule` | parser backend (default `auto`: Claude if key present, else rule) |
| `--model ID` | override Claude model (default `claude-sonnet-4-6`) |
| `--resolution N` | terrain grid cells per side (default 96) |
| `--seed N` | procedural RNG seed |
| `--json` | also print the WorldSpec JSON |
| `--extent METERS` | override the world side length in meters |

## How each stage works

1. **Parse** (`mapgen/parser`). The `ClaudeParser` uses Anthropic **tool-use** to
   force the model to emit a structured `WorldSpec` (world name, style, extent in
   meters, a list of terrain features, and prop intents). The tool schema is kept
   in lock-step with the Pydantic model, and the system prompt is prompt-cached.
   An offline `RuleParser` provides a keyword/regex fallback when no API key is
   set (or when `--parser rule` is given explicitly).

2. **Build** (`mapgen/generate`). A heightfield is constructed from fBm noise
   shaped by the terrain features and their compass directions, then triangulated.
   Water planes are added where the spec calls for lakes, rivers, seas, or coast.
   Colour-grading follows the `WorldStyle` (lowpoly_nature, fantasy, alpine,
   desert, etc.).

3. **Export** (`mapgen/export`). `trimesh` writes GLB / OBJ+MTL / STL. The GLB
   and OBJ include per-vertex normals so downstream tools shade correctly.

### Prop registry (AI-selectable; placement ships in M2)

`mapgen/props/` contains a decorator-based registry of procedural prop
generators. Available generators and their poly budgets:

| key | description |
|-----|-------------|
| `rock` | jittered icosahedron, ≤ 40 tris |
| `tree.conifer` | low-poly conifer (cone stack), ≤ 80 tris |
| `tree.broadleaf` | low-poly broadleaf (sphere-ish canopy), ≤ 80 tris |
| `barrel` | low-poly barrel mesh |
| `house.cottage` | simple cottage form |

The Claude parser's tool schema enumerates only keys that exist in the live
registry, so the model can **request** props by name. Props are testable in
isolation today (`mapgen/props/`). **Scattering them into the 3D scene is a
Milestone 2 deliverable** (see Roadmap below).

## Output formats

| format | notes |
|--------|-------|
| **GLB** | self-contained binary glTF with vertex colours and normals; best for web/three.js, game engines, Windows 3D Viewer |
| **OBJ** | colours stored **per-vertex inline** (correct for a colour-graded heightfield); a sibling `.mtl` is written for any single-material meshes |
| **STL** | geometry only, single merged mesh — for 3D printing or quick mesh inspection |

## Web app

A hardened FastAPI web app that lets registered users generate procedural worlds
in the browser, with a free **2-generations-per-account** quota (no payment
system). Extent is specified in **meters**.

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt -r requirements-mapgen.txt
.\.venv\Scripts\python.exe run_web.py          # http://127.0.0.1:8000
```

To **host it for free**, the app can split into a Vercel frontend (free) + a
free always-on generation worker — see [DEPLOY.md](DEPLOY.md).

Open the URL, create an account, and generate from the in-browser studio with a
live three.js viewer and GLB/OBJ/STL downloads.

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

## Environment variables

| variable | purpose |
|----------|---------|
| `ANTHROPIC_API_KEY` | enables the Claude parser (optional; rule parser used otherwise) |
| `MAPGEN_MODEL` | override the Claude model id |
| `MAPGEN_PARSER` | default parser backend (`auto`, `claude`, or `rule`) |
| `MAPGEN_RESOLUTION` | default terrain grid resolution |
| `MAPGEN_SEED` | default procedural seed |

## Tests

```powershell
.\.venv\Scripts\python.exe -m pytest tests -q
```

18 tests covering the pipeline, WorldSpec validation, and the prop generators.

## Roadmap (M2 and beyond)

The 5-stage pipeline design (`Parse → Plan → Build → Assemble → Export`) is
implemented through **Build** today. Planned milestones:

- **M2** — prop placement + GPU instancing: scatter registered prop generators
  into the scene mesh according to the `PropIntent` list in the `WorldSpec`;
  GPU-instanced rendering path for the web viewer.
- **M3** — glTF Y-up / meters export conventions; UV unwrap; per-material
  textures; LOD levels; collision mesh export.
- **M4** — streaming generation; large-extent chunking; web worker concurrency
  improvements.

## Notes & limits

- The **rule parser** is a best-effort offline heuristic; for accurate feature
  extraction use the **Claude parser** by setting `ANTHROPIC_API_KEY`.
- Lower `--resolution` or `--extent` for fast iteration; the default 96-cell
  grid at 200 m produces ~18 k triangles.
- The real-world data pipeline (OSM buildings, elevation, geocoding) has been
  archived to `legacy/` — this tool is procedural-only as of M0.
