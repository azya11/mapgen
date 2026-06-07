# Design: Re-point mapgen into a game-dev 3D world + prop tool

**Date:** 2026-06-07
**Status:** Approved (design) — ready for implementation planning
**Author:** Aziz

## 1. Goal

Re-point the existing `mapgen` pipeline from an AI **geographic map** generator into
a **game-dev tool** that turns a natural-language prompt into a 3D world: a terrain
**plus placeable low-poly props**, all **game-ready, low-poly, fast, deterministic,
and precise**.

The four product goals, and how the design honors each:

| Goal | How it is achieved |
|------|--------------------|
| **Low polygonality** | Geometry is produced by procedural parametric generators with explicit per-generator **poly budgets**. The AI never makes geometry. |
| **High performance (runtime)** | Repeated props share one mesh + N transforms via glTF `EXT_mesh_gpu_instancing`. Flat-color PBR, no textures in v1. |
| **Fast (generation)** | Fully procedural — no rate-limited external APIs. Deterministic code paths only. |
| **Precise** | Code owns every vertex; a fixed `WorldSpec` + `seed` produces identical output byte-for-byte. |

## 2. Decisions (resolved during brainstorming)

1. **Scope:** Both terrain *and* placeable low-poly props (terrain = world layer, props = new layer on top).
2. **Model production:** Procedural **parametric generators** (params → mesh). Not AI mesh generation, not a hand-authored asset library. (A small curated kit may blend in later for hero props.)
3. **Output target:** **Engine-agnostic glTF/GLB first** (glTF 2.0 conventions: meters, Y-up, PBR). Godot/Unity import cleanly; Unreal path documented later.
4. **Real-world data:** **Dropped.** `mapgen/geo/` (geocode/osm/elevation) and real-vs-procedural branching are archived to `legacy/`, not deleted. The spec loses `is_real_location`.
5. **v1 "game-ready" line (YAGNI):** clean low-poly meshes, correct units (meters) + Y-up, sensible pivots/origins, deterministic seeds, and **GPU instancing metadata**. **Deferred to v2:** LOD chains, collision proxies, UV unwrap + texture atlasing.

## 3. Architecture

```
prompt ─▶ [Parse]    Claude tool-use / rule fallback ─▶ WorldSpec (JSON, validated)
        ─▶ [Plan]     deterministic placement: terrain + prop instances on a seed
        ─▶ [Build]    terrain mesh  +  procedural prop generators (parametric)
        ─▶ [Assemble] scene graph: meshes + instance transforms + materials
        ─▶ [Export]   glTF/GLB (meters, Y-up, instancing) + manifest.json
```

**Stays:** `parser/` (Claude + rule + tool-schema-in-lockstep pattern), the
single-validated-spec contract, `generate/terrain.py` + `noise.py`,
`generate/scene.py` (assembler), `export/` glTF/GLB writer, `style.py`, `scale.py`,
the CLI, and the entire web app + worker + security stack.

**Archived to `legacy/`:** `mapgen/geo/` (geocode, osm, elevation), real-vs-procedural
branching, and the Blender-render script (off the critical path).

**Net-new:** `mapgen/props/` (registry of parametric generators) and
`mapgen/generate/placement.py` (intents → deterministic transforms).

**Core invariant:** the AI never makes geometry. It emits a `WorldSpec`; code owns
every vertex. This is what keeps output low-poly, fast, deterministic, and precise.

## 4. Data model

`WorldSpec` evolves `SceneSpec`: drops `is_real_location`; renames `extent_km`→`extent_m`
and `map_style`→`world_style`; keeps `features` (now under `terrain`) and `notes`;
adds `seed` and `props`.

```python
class WorldSpec(BaseModel):
    name: str                  # output basename
    world_style: WorldStyle    # fantasy | lowpoly_nature | urban | desert | ...
    extent_m: float            # square side in meters (game-scale, e.g. 50–2000)
    seed: int                  # determinism: same spec → identical bytes
    terrain: TerrainSpec       # relief features (existing GeoFeature list)
    props: List[PropIntent]    # NEW
    notes: Optional[str]
```

`PropIntent` is the AI's *request*, not geometry:

```python
class PropIntent(BaseModel):
    generator: str                  # registry key: "tree.conifer", "barrel", "house.cottage", "rock"
    count: int = 1
    region: Direction | str         # compass zone | "scatter" | "edge" | "cluster"
    density: Size                   # sparse | medium | dense (placement, not poly count)
    params: dict                    # generator-specific overrides
    on: Literal["ground", "water"] = "ground"
```

## 5. Prop registry (`mapgen/props/`)

Each generator is one small, isolated, independently testable unit:

```python
@register("tree.conifer")
def conifer(p: ConiferParams, rng) -> PropMesh:
    # returns verts, faces, pivot at base-center, material_id; honors poly_budget
```

- `PropMesh` = tiny dataclass: `verts, faces, pivot, material_id, bbox`.
- Each generator declares a **poly budget** and a typed Pydantic params model.
- The AI's tool-schema is **generated from the registry** (same lockstep pattern as
  today's parser), so adding a generator file makes it immediately AI-usable.
- Instancing falls out for free: N props of identical `generator`+`params` → one
  mesh + N transforms.

## 6. Placement (`mapgen/generate/placement.py`)

Deterministic step turning `PropIntent`s into concrete transforms:

- Seeded RNG (`numpy.random.default_rng(seed)`) → reproducible byte-for-byte.
- Resolves `region` → a 2D mask over terrain (compass zones, edges, clusters, scatter).
- Poisson-disk / jittered-grid sampling → natural, non-overlapping scatter at `density`.
- Snaps each instance to terrain height (samples the heightfield), applies random yaw
  + slight scale jitter, rejects water unless `on="water"`.
- Output: flat list of `(generator, params_hash, transform)`, grouped by `params_hash`
  so identical props share a mesh.

## 7. Assembly & export

- **Assembly (`scene.py`)** builds the scene graph: terrain mesh as one node; each
  unique prop mesh once; instances as child transforms. Materials from `style.py`
  keyed by `material_id` (flat PBR colors; no textures in v1).
- **Export (`export/`)** glTF 2.0 / GLB, **meters, Y-up**, `EXT_mesh_gpu_instancing`
  for repeated props, plus a sibling **`manifest.json`**: resolved spec, seed,
  per-prop counts, total triangle count, poly-budget report. STL/OBJ remain secondary.

## 8. Error handling

- Generator params validated against their Pydantic models.
- Unknown `generator` key → spec validation error before any geometry runs.
- Placement that can't fit `count` in a region → "as many as fit" + manifest warning,
  never a crash. Same graceful-degradation philosophy as the current pipeline.

## 9. Testing

Extends the existing `tests/test_pipeline.py` pattern:

- **Per-generator unit tests:** poly budget respected; watertight where expected;
  pivot at declared origin; deterministic for fixed seed.
- **Placement tests:** no overlaps; correct count; instances on valid ground.
- **Golden-spec test:** fixed `WorldSpec` + seed → stable triangle count & bbox.
- **Export test:** GLB validates; instancing extension present; units/axis correct.

## 10. Staging (decomposition into milestones)

Each milestone is independently shippable and gets its own plan → implementation cycle.

- **M0 — Re-point the spine + prop registry (merged).** Archive `geo/` to `legacy/`;
  rename `SceneSpec`→`WorldSpec` (drop `is_real_location`, add `seed`/`props`); update
  the parser tool-schema, CLI, web/worker, and tests to the procedural-only path. In the
  same milestone, build `mapgen/props/` registry, `PropMesh`, poly-budget plumbing, and
  3–5 generators (rock, conifer, broadleaf tree, barrel, cottage), with the registry
  feeding the AI tool-schema. *Pipeline still emits terrain only (placement is M2), but
  generators are testable standalone and the spec already carries `props`.*
- **M2 — Placement + assembly + instanced export.** `placement.py`, scene assembly with
  shared meshes, `EXT_mesh_gpu_instancing` export, `manifest.json`. *First full
  prompt→world-with-props output.*
- **M3 — Breadth + polish.** More generators, more `world_style` palettes, web studio
  viewer support for instanced glTF, golden tests across styles.
- **v2 (deferred):** LOD chains, collision proxies, UV unwrap + texture atlas, optional
  curated-kit blending, optional engine-specific exporters (Godot `.tscn`, Unity prefab).

## 11. Out of scope (v1)

LOD; collision meshes; UV/texturing; AI mesh generation; real-world geographic import
(archived); engine-specific export formats; the Blender-render path.
