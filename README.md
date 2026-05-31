# mapgen — prompt → 3D map pipeline

An AI pipeline that turns a natural-language prompt describing a **location, its
surroundings, and the kind of map** you want into **3D models and files ready for
rendering** (glTF/GLB, OBJ+MTL, STL, and a runnable Blender script).

```
prompt ─▶ [1 Parse]  Claude tool-use ─▶ validated SceneSpec (JSON)
       ─▶ [2 Resolve] geocode → real? OSM buildings + elevation : procedural
       ─▶ [3 Build]   terrain mesh + water + buildings → trimesh.Scene
       ─▶ [4 Export]  GLB · OBJ+MTL · STL · Blender .py
```

It is **hybrid**: recognised real places are built from real OpenStreetMap
building footprints and Open-Meteo elevation data; fictional or unrecognised
places are generated procedurally from the parsed description.

## Install

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

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
