# M0 — Re-point the spine + prop registry — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert `mapgen` from a geographic map generator into a procedural-only game-world generator (`WorldSpec`), archive the real-world geo stack, and add a self-registering procedural **prop generator registry** with 5 starter props — without yet placing props in the scene (placement is M2).

**Architecture:** The `parser → spec → build → export` spine stays. We rename `SceneSpec`→`WorldSpec` (drop `is_real_location`, rename `map_style`→`world_style` / `extent_km`→`extent_m`, add `seed` + `props`), delete the geo-resolve branch from the pipeline, and move `mapgen/geo/` to `legacy/`. A new `mapgen/props/` package holds a `PropMesh` value type, a decorator-based registry with per-generator poly budgets, and 5 parametric generators. The Claude tool-schema's generator enum is generated from the registry so the AI can only request props that exist. Props are validated and unit-tested standalone; the scene still emits terrain only.

**Tech Stack:** Python 3.12, Pydantic v2, numpy, trimesh, pytest. Windows/PowerShell dev shell; run Python via `.\.venv\Scripts\python.exe`.

---

## Conventions for every task

- Run tests with: `.\.venv\Scripts\python.exe -m pytest tests\ -q`
- Run one test: `.\.venv\Scripts\python.exe -m pytest tests\test_props.py::test_name -v`
- The legacy self-runner `python tests\test_pipeline.py` is replaced by pytest; keep tests pytest-discoverable.
- Internal geometry frame is **Z-up, meters** (matches existing terrain). The glTF **Y-up** conversion is an *export* concern deferred to M2 — do **not** add axis conversion in this plan.
- Each prop is authored with its **pivot at the base center**: XY centroid ≈ origin, lowest vertex at `z ≈ 0`.

## Refinements made vs. the approved spec (flagged)

1. `PropIntent.generator` is a plain `str` in `WorldSpec` (validated at build time, not in the Pydantic model). Reason: `mapgen/spec.py` must stay import-light (no numpy) for the serverless web bundle; importing the registry would pull numpy in. The Claude tool-schema still constrains the enum to real generator keys.
2. `WorldStyle` members are: `lowpoly_nature` (default), `fantasy`, `urban`, `desert`, `alpine`, `schematic`, `minimal`. They map from the old `MapStyle` (`terrain→lowpoly_nature`, `city→urban`, `topographic→alpine`, plus new `desert`).
3. One `material_id` per `PropMesh` in v1 (multi-material props deferred to v2).

---

## File structure

**New files**
- `mapgen/props/__init__.py` — package; imports generator modules so they self-register; re-exports registry API + `PropMesh`.
- `mapgen/props/base.py` — `PropMesh` value type + `from_trimesh` helper.
- `mapgen/props/registry.py` — decorator registry, `GeneratorEntry`, `register`, `get`, `all_keys`, `build`.
- `mapgen/props/generators/__init__.py` — imports each generator module.
- `mapgen/props/generators/rock.py`, `tree.py` (conifer + broadleaf), `barrel.py`, `cottage.py`.
- `tests/test_props.py` — generator + registry unit tests.
- `tests/test_worldspec.py` — spec/tool-schema contract tests.
- `legacy/README.md` — note on archived geo stack.

**Modified files**
- `mapgen/spec.py` — `SceneSpec`→`WorldSpec`; field changes; `PropIntent`.
- `mapgen/parser/base.py`, `claude_parser.py`, `rule_parser.py`, `__init__.py` — emit `WorldSpec`; tool schema rebuilt with registry-driven `props`.
- `mapgen/pipeline.py` — drop geo resolve; procedural-only.
- `mapgen/generate/scene.py`, `terrain.py` — drop geo imports / real-data branch; rekey styles to `WorldStyle`.
- `mapgen/config.py` — drop geo network config; keep geometry config.
- `cli.py` — drop `--location/--real/--procedural/--offline`(geo) flags; `--extent` now meters.
- `web/generate.py`, `worker/app.py` — drop `use_real`/real-data fields.
- `tests/test_pipeline.py` — update to `WorldSpec` and procedural-only.

**Moved (archived)**
- `mapgen/geo/` → `legacy/geo/`.

---

## Task 1: Archive the geo stack

**Files:**
- Move: `mapgen/geo/` → `legacy/geo/`
- Create: `legacy/README.md`

- [ ] **Step 1: Move the geo package out of the import path**

```powershell
New-Item -ItemType Directory -Force legacy | Out-Null
git mv mapgen/geo legacy/geo
```

- [ ] **Step 2: Add an archive note**

Create `legacy/README.md`:

```markdown
# legacy/

Archived during the M0 game-dev re-point (2026-06-07). Not imported by `mapgen`.

- `geo/` — the real-world data stack (Nominatim geocode, Overpass OSM buildings,
  Open-Meteo elevation). Removed because the product is now fully procedural
  (fast, deterministic, low-poly). Kept for reference / a possible future
  "import real terrain" plugin.
```

- [ ] **Step 3: Verify mapgen no longer resolves the geo package**

Run: `.\.venv\Scripts\python.exe -c "import importlib.util; print(importlib.util.find_spec('mapgen.geo'))"`
Expected: `None`

- [ ] **Step 4: Commit**

```powershell
git add -A
git commit -m "refactor: archive geo stack to legacy/ for procedural-only pivot"
```

> Note: `mapgen` will not import until Tasks 2–7 remove the geo references. That is expected; the next commits restore a working tree.

---

## Task 2: WorldSpec data model

**Files:**
- Modify: `mapgen/spec.py`
- Test: `tests/test_worldspec.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_worldspec.py`:

```python
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mapgen.spec import (
    PropIntent,
    TerrainFeature,
    TerrainSpec,
    WorldSpec,
    WorldStyle,
)


def test_worldspec_minimal_defaults():
    w = WorldSpec(name="demo")
    assert w.world_style == WorldStyle.lowpoly_nature
    assert w.extent_m == 200.0
    assert w.seed == 1234
    assert w.props == []
    assert w.terrain.features == []


def test_worldspec_full_roundtrip():
    w = WorldSpec(
        name="village",
        world_style="fantasy",
        extent_m=400.0,
        seed=7,
        terrain=TerrainSpec(features=[TerrainFeature(type="hill", direction="north")]),
        props=[PropIntent(generator="tree.conifer", count=20, region="north", density="dense")],
    )
    assert w.terrain.features[0].type.value == "hill"
    assert w.props[0].count == 20
    # generator stays a plain string in the model (validated at build time)
    assert isinstance(w.props[0].generator, str)


def test_worldspec_extent_bounds():
    import pytest

    with pytest.raises(Exception):
        WorldSpec(name="x", extent_m=0.0)
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_worldspec.py -q`
Expected: FAIL with `ImportError`/`cannot import name 'WorldSpec'`.

- [ ] **Step 3: Rewrite the spec module**

Replace the entire contents of `mapgen/spec.py` with:

```python
"""The structured world specification — the contract between the AI parser and
the procedural geometry pipeline. Everything downstream depends only on this
schema, so the parser backend (Claude / rules / future) is fully swappable.

Kept import-light (no numpy/trimesh) so the serverless web bundle can import it.
"""

from __future__ import annotations

from enum import Enum
from typing import List, Literal, Optional

from pydantic import BaseModel, Field


class Direction(str, Enum):
    north = "north"
    south = "south"
    east = "east"
    west = "west"
    northeast = "northeast"
    northwest = "northwest"
    southeast = "southeast"
    southwest = "southwest"
    center = "center"


class FeatureType(str, Enum):
    mountain = "mountain"
    hill = "hill"
    valley = "valley"
    water = "water"
    river = "river"
    lake = "lake"
    sea = "sea"
    coast = "coast"
    forest = "forest"
    plain = "plain"
    desert = "desert"


class WorldStyle(str, Enum):
    lowpoly_nature = "lowpoly_nature"   # default natural relief, muted greens
    fantasy = "fantasy"                 # stylized, exaggerated relief
    urban = "urban"                     # flat-ish, built-up
    desert = "desert"                   # sandy palette, dunes
    alpine = "alpine"                   # high relief, rock + snow
    schematic = "schematic"             # clean, abstract, flat colors
    minimal = "minimal"                 # grayscale, geometry only


class Size(str, Enum):
    small = "small"
    medium = "medium"
    large = "large"


class TerrainFeature(BaseModel):
    """One relief element of the world (a hill to the north, a lake, etc.)."""

    type: FeatureType
    name: Optional[str] = Field(default=None, description="Proper name if given.")
    direction: Optional[Direction] = Field(
        default=None, description="Where it sits relative to the world centre."
    )
    relative_size: Size = Field(default=Size.medium)
    description: Optional[str] = Field(default=None)


class TerrainSpec(BaseModel):
    """The relief layer: a list of terrain features shaping the heightfield."""

    features: List[TerrainFeature] = Field(default_factory=list)

    def features_of(self, *types: FeatureType) -> List[TerrainFeature]:
        wanted = set(types)
        return [f for f in self.features if f.type in wanted]

    @property
    def has_water(self) -> bool:
        return bool(
            self.features_of(
                FeatureType.water,
                FeatureType.lake,
                FeatureType.sea,
                FeatureType.river,
                FeatureType.coast,
            )
        )


class PropIntent(BaseModel):
    """A request to place props of one kind. The AI emits intents, never geometry.

    `generator` is a registry key (e.g. "tree.conifer"); it is validated against
    the live registry at build time, not here, so this module stays import-light.
    """

    generator: str = Field(description="Prop generator registry key, e.g. 'rock'.")
    count: int = Field(default=1, ge=1, le=5000)
    region: str = Field(
        default="scatter",
        description="A compass direction, 'scatter', 'edge', or 'cluster'.",
    )
    density: Size = Field(default=Size.medium)
    params: dict = Field(default_factory=dict)
    on: Literal["ground", "water"] = "ground"


class WorldSpec(BaseModel):
    """Fully validated description of a procedural world. Produced by a Parser."""

    name: str = Field(default="world", description="Output basename / world name.")
    world_style: WorldStyle = WorldStyle.lowpoly_nature
    extent_m: float = Field(
        default=200.0,
        gt=1.0,
        le=20000.0,
        description="Side length of the square world to model, in meters.",
    )
    seed: int = Field(default=1234, description="RNG seed; fixes determinism.")
    terrain: TerrainSpec = Field(default_factory=TerrainSpec)
    props: List[PropIntent] = Field(default_factory=list)
    notes: Optional[str] = Field(default=None)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_worldspec.py -q`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```powershell
git add mapgen/spec.py tests/test_worldspec.py
git commit -m "feat: WorldSpec procedural contract (replaces SceneSpec)"
```

---

## Task 3: PropMesh value type

**Files:**
- Create: `mapgen/props/__init__.py`, `mapgen/props/base.py`
- Test: `tests/test_props.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_props.py`:

```python
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mapgen.props.base import PropMesh, from_trimesh


def test_propmesh_counts_and_bbox():
    verts = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], float)
    faces = np.array([[0, 1, 2]], int)
    pm = PropMesh(verts=verts, faces=faces, material_id="rock")
    assert pm.tri_count == 1
    assert pm.bbox.shape == (2, 3)
    np.testing.assert_allclose(pm.bbox[0], [0, 0, 0])
    np.testing.assert_allclose(pm.bbox[1], [1, 1, 0])


def test_from_trimesh_recenters_to_base_pivot():
    import trimesh

    box = trimesh.creation.box(extents=[2, 2, 2])  # centered at origin → spans z[-1,1]
    pm = from_trimesh(box, "wood")
    # pivot at base center: xy centroid ~0, lowest vertex at z~0
    assert abs(pm.verts[:, 0].mean()) < 1e-6
    assert abs(pm.verts[:, 1].mean()) < 1e-6
    assert abs(pm.verts[:, 2].min()) < 1e-6
    assert pm.material_id == "wood"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_props.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'mapgen.props'`.

- [ ] **Step 3: Implement `PropMesh`**

Create `mapgen/props/base.py`:

```python
"""PropMesh: the value type every procedural prop generator returns.

Authored in the internal frame (Z-up, meters) with the pivot at the base center:
XY centroid at the origin and the lowest vertex at z=0, so placement (M2) can
drop a prop onto terrain by translating to (x, y, ground_z) with no offset math.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class PropMesh:
    verts: np.ndarray      # (N, 3) float meters, Z-up, pivot at base center
    faces: np.ndarray      # (M, 3) int
    material_id: str       # palette key, e.g. "rock", "foliage", "wood"

    @property
    def tri_count(self) -> int:
        return int(len(self.faces))

    @property
    def bbox(self) -> np.ndarray:
        return np.array([self.verts.min(axis=0), self.verts.max(axis=0)])


def from_trimesh(mesh, material_id: str) -> PropMesh:
    """Build a PropMesh from a trimesh.Trimesh, recentering to the base pivot."""
    verts = np.asarray(mesh.vertices, float).copy()
    faces = np.asarray(mesh.faces, int).copy()
    verts[:, 0] -= verts[:, 0].mean()
    verts[:, 1] -= verts[:, 1].mean()
    verts[:, 2] -= verts[:, 2].min()
    return PropMesh(verts=verts, faces=faces, material_id=material_id)
```

Create `mapgen/props/__init__.py`:

```python
"""Procedural prop generators. Importing this package registers every generator.

The AI never produces geometry: it emits PropIntents naming a generator key +
params; code here owns every vertex, so output is low-poly and deterministic.
"""

from .base import PropMesh, from_trimesh
from .registry import GeneratorEntry, all_keys, build, get, register

# Import the generator modules for their registration side effects.
from . import generators  # noqa: E402,F401

__all__ = [
    "PropMesh",
    "from_trimesh",
    "GeneratorEntry",
    "register",
    "get",
    "all_keys",
    "build",
]
```

> `mapgen/props/registry.py` and `mapgen/props/generators/` do not exist yet, so the package import line will fail until Task 4. The unit test above imports `mapgen.props.base` directly, which works now.

- [ ] **Step 4: Run the test to verify it passes**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_props.py -q`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```powershell
git add mapgen/props/base.py mapgen/props/__init__.py tests/test_props.py
git commit -m "feat: PropMesh value type with base-pivot recentering"
```

---

## Task 4: Generator registry

**Files:**
- Create: `mapgen/props/registry.py`, `mapgen/props/generators/__init__.py`
- Test: `tests/test_props.py` (append)

- [ ] **Step 1: Write the failing test (append to `tests/test_props.py`)**

```python
def test_registry_register_build_and_budget():
    import numpy as np
    import pytest
    from pydantic import BaseModel

    from mapgen.props import registry
    from mapgen.props.base import PropMesh

    class _P(BaseModel):
        size: float = 1.0

    @registry.register("test.tri", params_model=_P, poly_budget=2)
    def _tri(p: _P, rng) -> PropMesh:
        v = np.array([[0, 0, 0], [p.size, 0, 0], [0, p.size, 0]], float)
        f = np.array([[0, 1, 2]], int)
        return PropMesh(verts=v, faces=f, material_id="rock")

    assert "test.tri" in registry.all_keys()
    pm = registry.build("test.tri", {"size": 2.0}, np.random.default_rng(0))
    assert pm.tri_count == 1
    assert pm.bbox[1][0] == 2.0

    # unknown key → KeyError
    with pytest.raises(KeyError):
        registry.build("nope", {}, np.random.default_rng(0))

    # bad params → validation error
    with pytest.raises(Exception):
        registry.build("test.tri", {"size": "huge"}, np.random.default_rng(0))


def test_registry_enforces_poly_budget():
    import numpy as np
    import pytest
    from pydantic import BaseModel

    from mapgen.props import registry
    from mapgen.props.base import PropMesh

    class _P(BaseModel):
        pass

    @registry.register("test.toomany", params_model=_P, poly_budget=1)
    def _big(p, rng) -> PropMesh:
        v = np.zeros((6, 3))
        f = np.array([[0, 1, 2], [3, 4, 5]], int)
        return PropMesh(verts=v, faces=f, material_id="rock")

    with pytest.raises(ValueError, match="poly budget"):
        registry.build("test.toomany", {}, np.random.default_rng(0))
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_props.py -k registry -q`
Expected: FAIL (`ModuleNotFoundError: No module named 'mapgen.props.registry'` or import error from `__init__`).

- [ ] **Step 3: Implement the registry**

Create `mapgen/props/registry.py`:

```python
"""Decorator-based registry of procedural prop generators.

Each generator: (validated params, numpy rng) -> PropMesh, with a declared
poly budget enforced at build time. The set of keys feeds the AI tool-schema,
so the model can only request props that exist.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import numpy as np
from pydantic import BaseModel

from .base import PropMesh

GeneratorFn = Callable[[BaseModel, np.random.Generator], PropMesh]


@dataclass
class GeneratorEntry:
    key: str
    fn: GeneratorFn
    params_model: type[BaseModel]
    poly_budget: int


_REGISTRY: dict[str, GeneratorEntry] = {}


def register(key: str, *, params_model: type[BaseModel], poly_budget: int):
    def deco(fn: GeneratorFn) -> GeneratorFn:
        if key in _REGISTRY:
            raise ValueError(f"Generator key already registered: {key!r}")
        _REGISTRY[key] = GeneratorEntry(key, fn, params_model, poly_budget)
        return fn

    return deco


def get(key: str) -> GeneratorEntry:
    if key not in _REGISTRY:
        raise KeyError(f"Unknown prop generator: {key!r}. Known: {all_keys()}")
    return _REGISTRY[key]


def all_keys() -> list[str]:
    return sorted(_REGISTRY)


def build(key: str, params: dict, rng: np.random.Generator) -> PropMesh:
    entry = get(key)
    validated = entry.params_model.model_validate(params or {})
    mesh = entry.fn(validated, rng)
    if mesh.tri_count > entry.poly_budget:
        raise ValueError(
            f"Generator {key!r} exceeded poly budget: "
            f"{mesh.tri_count} > {entry.poly_budget}"
        )
    return mesh
```

Create `mapgen/props/generators/__init__.py`:

```python
"""Importing this package registers every built-in generator."""

from . import barrel, cottage, rock, tree  # noqa: F401
```

> `rock`, `tree`, `barrel`, `cottage` modules are created in Tasks 5–8. Until then, import will fail. To keep the suite green between tasks, create empty placeholder modules now:

```powershell
New-Item -ItemType File mapgen/props/generators/rock.py
New-Item -ItemType File mapgen/props/generators/tree.py
New-Item -ItemType File mapgen/props/generators/barrel.py
New-Item -ItemType File mapgen/props/generators/cottage.py
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_props.py -q`
Expected: PASS (all prop tests).

- [ ] **Step 5: Commit**

```powershell
git add mapgen/props/registry.py mapgen/props/generators tests/test_props.py
git commit -m "feat: prop generator registry with poly-budget enforcement"
```

---

## Task 5: `rock` generator

**Files:**
- Modify: `mapgen/props/generators/rock.py`
- Test: `tests/test_props.py` (append)

- [ ] **Step 1: Write the failing test (append)**

```python
def test_rock_generator():
    import numpy as np

    from mapgen.props import registry

    rng = np.random.default_rng(42)
    pm = registry.build("rock", {"radius": 0.5}, rng)
    assert pm.material_id == "rock"
    assert pm.tri_count <= 40
    # base pivot: lowest vertex on the ground, centered in XY
    assert abs(pm.verts[:, 2].min()) < 1e-6
    assert abs(pm.verts[:, 0].mean()) < 0.2
    # deterministic for a fixed seed
    a = registry.build("rock", {"radius": 0.5}, np.random.default_rng(1))
    b = registry.build("rock", {"radius": 0.5}, np.random.default_rng(1))
    np.testing.assert_allclose(a.verts, b.verts)
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_props.py::test_rock_generator -q`
Expected: FAIL (`KeyError: "Unknown prop generator: 'rock'"`).

- [ ] **Step 3: Implement the rock generator**

Replace the contents of `mapgen/props/generators/rock.py`:

```python
"""Low-poly boulder: a jittered icosahedron (20 faces). Watertight, ~20 tris."""

from __future__ import annotations

import numpy as np
import trimesh
from pydantic import BaseModel, Field

from ..base import PropMesh, from_trimesh
from ..registry import register


class RockParams(BaseModel):
    radius: float = Field(default=0.5, gt=0.02, le=20.0)
    jitter: float = Field(default=0.25, ge=0.0, le=0.6)


@register("rock", params_model=RockParams, poly_budget=40)
def rock(p: RockParams, rng: np.random.Generator) -> PropMesh:
    mesh = trimesh.creation.icosahedron()
    mesh.apply_scale(p.radius)
    # Per-vertex radial jitter for an irregular boulder; flatten slightly in Z.
    offsets = 1.0 + rng.uniform(-p.jitter, p.jitter, size=len(mesh.vertices))
    mesh.vertices *= offsets[:, None]
    mesh.vertices[:, 2] *= 0.8
    return from_trimesh(mesh, "rock")
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_props.py::test_rock_generator -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add mapgen/props/generators/rock.py tests/test_props.py
git commit -m "feat: rock prop generator (jittered icosahedron, <=40 tris)"
```

---

## Task 6: `tree.conifer` + `tree.broadleaf` generators

**Files:**
- Modify: `mapgen/props/generators/tree.py`
- Test: `tests/test_props.py` (append)

- [ ] **Step 1: Write the failing test (append)**

```python
def test_tree_generators():
    import numpy as np

    from mapgen.props import registry

    conifer = registry.build("tree.conifer", {"height": 4.0}, np.random.default_rng(3))
    assert conifer.material_id == "foliage"
    assert conifer.tri_count <= 60
    assert abs(conifer.verts[:, 2].min()) < 1e-6
    assert conifer.verts[:, 2].max() <= 4.0 + 1e-6  # honors height

    broadleaf = registry.build("tree.broadleaf", {"height": 5.0}, np.random.default_rng(3))
    assert broadleaf.material_id == "foliage"
    assert broadleaf.tri_count <= 120
    assert abs(broadleaf.verts[:, 2].min()) < 1e-6
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_props.py::test_tree_generators -q`
Expected: FAIL (`KeyError: "Unknown prop generator: 'tree.conifer'"`).

- [ ] **Step 3: Implement the tree generators**

Replace the contents of `mapgen/props/generators/tree.py`:

```python
"""Low-poly trees. Conifer = trunk cylinder + stacked cones; broadleaf = trunk +
low-subdivision icosphere canopy. Both author the trunk base at z=0."""

from __future__ import annotations

import numpy as np
import trimesh
from pydantic import BaseModel, Field

from ..base import PropMesh, from_trimesh
from ..registry import register


class ConiferParams(BaseModel):
    height: float = Field(default=4.0, gt=0.3, le=60.0)
    trunk_frac: float = Field(default=0.18, gt=0.02, le=0.5)


class BroadleafParams(BaseModel):
    height: float = Field(default=5.0, gt=0.3, le=60.0)
    trunk_frac: float = Field(default=0.45, gt=0.05, le=0.7)


def _stack(meshes: list[trimesh.Trimesh]) -> trimesh.Trimesh:
    return trimesh.util.concatenate(meshes)


@register("tree.conifer", params_model=ConiferParams, poly_budget=60)
def conifer(p: ConiferParams, rng: np.random.Generator) -> PropMesh:
    trunk_h = p.height * p.trunk_frac
    canopy_h = p.height - trunk_h
    trunk = trimesh.creation.cylinder(radius=p.height * 0.03, height=trunk_h, sections=5)
    trunk.apply_translation([0, 0, trunk_h / 2.0])
    # two stacked cones for a layered conifer silhouette
    c1 = trimesh.creation.cone(radius=p.height * 0.22, height=canopy_h * 0.7, sections=6)
    c1.apply_translation([0, 0, trunk_h])
    c2 = trimesh.creation.cone(radius=p.height * 0.15, height=canopy_h * 0.55, sections=6)
    c2.apply_translation([0, 0, trunk_h + canopy_h * 0.45])
    return from_trimesh(_stack([trunk, c1, c2]), "foliage")


@register("tree.broadleaf", params_model=BroadleafParams, poly_budget=120)
def broadleaf(p: BroadleafParams, rng: np.random.Generator) -> PropMesh:
    trunk_h = p.height * p.trunk_frac
    trunk = trimesh.creation.cylinder(radius=p.height * 0.04, height=trunk_h, sections=6)
    trunk.apply_translation([0, 0, trunk_h / 2.0])
    canopy_r = p.height * 0.28
    canopy = trimesh.creation.icosphere(subdivisions=1, radius=canopy_r)
    canopy.vertices[:, 2] *= 0.85
    canopy.apply_translation([0, 0, trunk_h + canopy_r * 0.7])
    return from_trimesh(_stack([trunk, canopy]), "foliage")
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_props.py::test_tree_generators -q`
Expected: PASS.

> If `tree.broadleaf` exceeds 120 tris, lower `subdivisions` is already 1 (the minimum non-trivial icosphere = 80 faces) + trunk (~12) ≈ 92; budget has headroom. If `tree.conifer` exceeds 60, reduce cone `sections` from 6 to 5.

- [ ] **Step 5: Commit**

```powershell
git add mapgen/props/generators/tree.py tests/test_props.py
git commit -m "feat: conifer + broadleaf tree generators"
```

---

## Task 7: `barrel` generator

**Files:**
- Modify: `mapgen/props/generators/barrel.py`
- Test: `tests/test_props.py` (append)

- [ ] **Step 1: Write the failing test (append)**

```python
def test_barrel_generator():
    import numpy as np
    import trimesh

    from mapgen.props import registry

    pm = registry.build("barrel", {"height": 1.0, "radius": 0.35}, np.random.default_rng(9))
    assert pm.material_id == "wood"
    assert pm.tri_count <= 60
    assert abs(pm.verts[:, 2].min()) < 1e-6
    assert pm.verts[:, 2].max() <= 1.0 + 1e-6
    # watertight: a barrel is a closed solid
    tm = trimesh.Trimesh(vertices=pm.verts, faces=pm.faces, process=False)
    assert tm.is_watertight
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_props.py::test_barrel_generator -q`
Expected: FAIL (`KeyError: "Unknown prop generator: 'barrel'"`).

- [ ] **Step 3: Implement the barrel generator**

Replace the contents of `mapgen/props/generators/barrel.py`:

```python
"""Low-poly barrel: an octagonal cylinder. Watertight, ~28 tris."""

from __future__ import annotations

import numpy as np
import trimesh
from pydantic import BaseModel, Field

from ..base import PropMesh, from_trimesh
from ..registry import register


class BarrelParams(BaseModel):
    height: float = Field(default=1.0, gt=0.1, le=5.0)
    radius: float = Field(default=0.35, gt=0.05, le=3.0)


@register("barrel", params_model=BarrelParams, poly_budget=60)
def barrel(p: BarrelParams, rng: np.random.Generator) -> PropMesh:
    mesh = trimesh.creation.cylinder(radius=p.radius, height=p.height, sections=8)
    mesh.apply_translation([0, 0, p.height / 2.0])
    return from_trimesh(mesh, "wood")
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_props.py::test_barrel_generator -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add mapgen/props/generators/barrel.py tests/test_props.py
git commit -m "feat: barrel prop generator (octagonal, watertight)"
```

---

## Task 8: `house.cottage` generator

**Files:**
- Modify: `mapgen/props/generators/cottage.py`
- Test: `tests/test_props.py` (append)

- [ ] **Step 1: Write the failing test (append)**

```python
def test_cottage_generator():
    import numpy as np

    from mapgen.props import registry

    pm = registry.build(
        "house.cottage", {"width": 4.0, "depth": 3.0, "wall_h": 2.5}, np.random.default_rng(5)
    )
    assert pm.material_id == "building"
    assert pm.tri_count <= 40
    assert abs(pm.verts[:, 2].min()) < 1e-6
    # footprint roughly matches requested width/depth
    span = pm.bbox[1] - pm.bbox[0]
    assert abs(span[0] - 4.0) < 1e-6
    assert abs(span[1] - 3.0) < 1e-6
    # has a peaked roof taller than the walls
    assert pm.verts[:, 2].max() > 2.5
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_props.py::test_cottage_generator -q`
Expected: FAIL (`KeyError: "Unknown prop generator: 'house.cottage'"`).

- [ ] **Step 3: Implement the cottage generator**

Replace the contents of `mapgen/props/generators/cottage.py`:

```python
"""Low-poly cottage: a box body + a triangular-prism gable roof. ~16 tris."""

from __future__ import annotations

import numpy as np
import trimesh
from pydantic import BaseModel, Field

from ..base import PropMesh, from_trimesh
from ..registry import register


class CottageParams(BaseModel):
    width: float = Field(default=4.0, gt=0.5, le=40.0)   # X span
    depth: float = Field(default=3.0, gt=0.5, le=40.0)   # Y span
    wall_h: float = Field(default=2.5, gt=0.5, le=20.0)
    roof_h: float = Field(default=1.5, gt=0.1, le=15.0)


@register("house.cottage", params_model=CottageParams, poly_budget=40)
def cottage(p: CottageParams, rng: np.random.Generator) -> PropMesh:
    w, d, wh, rh = p.width, p.depth, p.wall_h, p.roof_h
    body = trimesh.creation.box(extents=[w, d, wh])
    body.apply_translation([0, 0, wh / 2.0])

    hx, hy = w / 2.0, d / 2.0
    # Gable prism: ridge runs along X at the top, eaves at wall height.
    roof_v = np.array([
        [-hx, -hy, wh], [hx, -hy, wh], [hx, hy, wh], [-hx, hy, wh],  # eaves 0..3
        [-hx, 0.0, wh + rh], [hx, 0.0, wh + rh],                      # ridge 4,5
    ], float)
    roof_f = np.array([
        [0, 1, 5], [0, 5, 4],   # front slope
        [3, 4, 5], [3, 5, 2],   # back slope
        [0, 4, 3],              # left gable
        [1, 2, 5],              # right gable
    ], int)
    roof = trimesh.Trimesh(vertices=roof_v, faces=roof_f, process=False)
    return from_trimesh(trimesh.util.concatenate([body, roof]), "building")
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_props.py::test_cottage_generator -q`
Expected: PASS.

- [ ] **Step 5: Run the full prop suite + verify registry keys**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_props.py -q`
Then: `.\.venv\Scripts\python.exe -c "import mapgen.props as P; print(P.all_keys())"`
Expected: tests pass; keys include `['barrel', 'house.cottage', 'rock', 'tree.broadleaf', 'tree.conifer', ...]` (test.* keys only appear under pytest).

- [ ] **Step 6: Commit**

```powershell
git add mapgen/props/generators/cottage.py tests/test_props.py
git commit -m "feat: cottage generator; complete 5-prop starter set"
```

---

## Task 9: De-geo the geometry layer (terrain + scene)

**Files:**
- Modify: `mapgen/generate/terrain.py`
- Modify: `mapgen/generate/scene.py`
- Modify: `mapgen/generate/__init__.py`

- [ ] **Step 1: Update `terrain.py` to WorldSpec/WorldStyle**

In `mapgen/generate/terrain.py`:

Change the import line:
```python
from ..spec import FeatureType, GeoFeature, MapStyle, SceneSpec, Size
```
to:
```python
from ..spec import FeatureType, TerrainFeature, WorldSpec, WorldStyle, Size
```

Delete the `from_elevation(...)` function entirely (real-data only).

Replace the `procedural(...)` signature and its first lines:
```python
def procedural(spec: SceneSpec, res: int, seed: int) -> Heightfield:
    """Build a heightfield from the parsed features alone (no real data)."""
    size_m = spec.extent_km * 1000.0
    ...
    mountains = spec.features_of(FeatureType.mountain, FeatureType.hill)
    valleys = spec.features_of(FeatureType.valley)
    waters = spec.features_of(...)
```
with:
```python
def procedural(spec: WorldSpec, res: int, seed: int) -> Heightfield:
    """Build a heightfield from the parsed features alone (no real data)."""
    size_m = spec.extent_m
    ...
    mountains = spec.terrain.features_of(FeatureType.mountain, FeatureType.hill)
    valleys = spec.terrain.features_of(FeatureType.valley)
    waters = spec.terrain.features_of(
        FeatureType.water, FeatureType.lake, FeatureType.sea,
        FeatureType.river, FeatureType.coast,
    )
```

Replace the `style_gain` dict (keyed on old `MapStyle`) with `WorldStyle` keys:
```python
    style_gain = {
        WorldStyle.fantasy: 2.2, WorldStyle.alpine: 1.6,
        WorldStyle.lowpoly_nature: 1.0, WorldStyle.urban: 0.35,
        WorldStyle.schematic: 0.5, WorldStyle.desert: 0.8,
        WorldStyle.minimal: 0.7,
    }.get(spec.world_style, 1.0)
```

- [ ] **Step 2: Update `scene.py` to procedural-only + WorldStyle**

In `mapgen/generate/scene.py`:

Remove the geo imports:
```python
from ..geo.geocode import BBox
from ..geo.osm import OSMData
from ..spec import MapStyle, SceneSpec
from . import buildings as bld
```
becomes:
```python
from ..spec import WorldSpec, WorldStyle
```
(Also delete `from . import buildings as bld` and `from . import vegetation as veg` — building/vegetation meshing depended on the old feature flow and is superseded by the M2 prop-placement layer.)

Rekey the `_STYLE` dict to `WorldStyle`:
```python
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
```

Replace `build_scene` with a procedural-only version (drops `bbox/elevation/osm`, buildings, vegetation; terrain + water only):
```python
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
```

In `SceneBuildResult`, delete the `used_real_data: bool` field.

In `_terrain_colors(hf, style)` and `_water_plane(hf, style)`, change the type hints `MapStyle`→`WorldStyle` (logic is unchanged; the cfg flag names `gray/flat/vivid/contours/water` are still produced by the new `_STYLE`).

- [ ] **Step 3: Run terrain/scene smoke check**

Run:
```powershell
.\.venv\Scripts\python.exe -c "from mapgen.generate import build_scene; from mapgen.spec import WorldSpec; from mapgen.config import Config; r=build_scene(WorldSpec(name='t', extent_m=300), Config(terrain_resolution=48)); print(r.stats)"
```
Expected: prints a stats dict with `terrain_faces > 0` and `prop_intents: 0`. No ImportError.

- [ ] **Step 4: Commit**

```powershell
git add mapgen/generate/terrain.py mapgen/generate/scene.py mapgen/generate/__init__.py
git commit -m "refactor: procedural-only terrain + scene on WorldSpec/WorldStyle"
```

---

## Task 10: Procedural-only pipeline

**Files:**
- Modify: `mapgen/pipeline.py`
- Modify: `mapgen/config.py`

- [ ] **Step 1: Trim `config.py`**

In `mapgen/config.py`, delete the geo-data block (the `nominatim_url`, `overpass_url`, `overpass_mirrors`, `elevation_url`, `user_agent`, `request_timeout`, `overpass_timeout`, `osm_max_extent_km` fields). Keep `use_network` removed too (no network left). Keep `anthropic_api_key`, `model`, `parser_backend`, `terrain_resolution`, `seed`, and `from_env` minus the `MAPGEN_OFFLINE` branch. Result:

```python
@dataclass
class Config:
    anthropic_api_key: str | None = None
    model: str = "claude-sonnet-4-6"
    parser_backend: str = "auto"   # auto | claude | rule

    terrain_resolution: int = 96
    seed: int = 1234

    @classmethod
    def from_env(cls) -> "Config":
        c = cls()
        c.anthropic_api_key = os.environ.get("ANTHROPIC_API_KEY")
        c.model = os.environ.get("MAPGEN_MODEL", c.model)
        c.parser_backend = os.environ.get("MAPGEN_PARSER", c.parser_backend)
        if os.environ.get("MAPGEN_RESOLUTION"):
            c.terrain_resolution = int(os.environ["MAPGEN_RESOLUTION"])
        if os.environ.get("MAPGEN_SEED"):
            c.seed = int(os.environ["MAPGEN_SEED"])
        return c
```

- [ ] **Step 2: Rewrite `pipeline.py` procedural-only**

Replace the entire contents of `mapgen/pipeline.py` with:

```python
"""The end-to-end pipeline: prompt -> WorldSpec -> procedural scene -> files."""

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
from .parser import make_parser
from .spec import WorldSpec


@dataclass
class PipelineResult:
    prompt: str
    spec: WorldSpec
    build: SceneBuildResult
    files: dict[str, str]
    timings: dict[str, float] = field(default_factory=dict)

    def summary(self) -> str:
        s = self.spec
        lines = [
            f"Prompt   : {self.prompt}",
            f"World    : {s.name}",
            f"Style    : {s.world_style.value}   extent: {s.extent_m} m",
            f"Features : {', '.join(self._feat()) or '(none)'}",
            f"Props    : {sum(p.count for p in s.props)} ({len(s.props)} intents)",
            f"Geometry : {self.build.stats}",
            "Files    :",
        ]
        for fmt, path in self.files.items():
            lines.append(f"           - {fmt:8s} {path}")
        return "\n".join(lines)

    def _feat(self) -> list[str]:
        out = []
        for f in self.spec.terrain.features:
            d = f.direction.value if f.direction else "-"
            out.append(f"{f.type.value}@{d}")
        return out


def _slugify(text: str) -> str:
    s = re.sub(r"[^\w\s-]", "", text.lower()).strip()
    s = re.sub(r"[\s_-]+", "-", s)
    return s[:48] or "world"


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
        formats = formats or ["glb", "obj", "stl"]
        overrides = overrides or {}
        timings: dict[str, float] = {}

        # 1) PARSE
        t = time.time()
        parser = make_parser(self.config)
        self._log(f"[1/3] Parsing prompt with {parser.name} ...")
        try:
            spec = parser.parse(prompt)
        except Exception as e:
            self._log(f"      {parser.name} failed ({e!r}); falling back to rule parser.")
            from .parser.rule_parser import RuleParser
            spec = RuleParser(self.config).parse(prompt)
        timings["parse"] = time.time() - t

        # Overrides (host caps / explicit values win over the parser).
        if overrides.get("extent_m"):
            spec.extent_m = float(overrides["extent_m"])
        cap = overrides.get("max_extent_m")
        if cap:
            spec.extent_m = min(spec.extent_m, float(cap))
        if overrides.get("world_style"):
            spec.world_style = overrides["world_style"]
        if overrides.get("seed") is not None:
            spec.seed = int(overrides["seed"])

        self._log(
            f"      -> {spec.name!r} | {spec.world_style.value} | "
            f"{len(spec.terrain.features)} features | {len(spec.props)} prop intents"
        )

        # 2) BUILD
        t = time.time()
        self._log("[2/3] Building 3D geometry ...")
        build = build_scene(spec, self.config)
        timings["build"] = time.time() - t
        self._log(f"      -> {build.stats}")

        # 3) EXPORT
        t = time.time()
        base = basename or _slugify(spec.name)
        self._log(f"[3/3] Exporting {formats} -> {out_dir}/ ...")
        files = export_all(build.scene, out_dir, base, formats)
        timings["export"] = time.time() - t

        return PipelineResult(
            prompt=prompt, spec=spec, build=build, files=files, timings=timings
        )
```

- [ ] **Step 3: Smoke-check the pipeline (rule parser, offline)**

Run:
```powershell
.\.venv\Scripts\python.exe -c "from mapgen import Pipeline; from mapgen.config import Config; c=Config(); c.parser_backend='rule'; c.terrain_resolution=48; r=Pipeline(config=c).run('a fantasy valley with a lake', out_dir='output/_smoke', formats=['glb']); print(r.summary())"
```
Expected: prints a summary; `output/_smoke/*.glb` exists; no geo imports.

- [ ] **Step 4: Commit**

```powershell
git add mapgen/pipeline.py mapgen/config.py
git commit -m "refactor: procedural-only pipeline; drop geo resolve + network config"
```

---

## Task 11: Update parsers (rule + Claude tool-schema with props)

**Files:**
- Modify: `mapgen/parser/rule_parser.py`
- Modify: `mapgen/parser/claude_parser.py`
- Modify: `mapgen/parser/base.py`, `mapgen/parser/__init__.py`
- Test: `tests/test_worldspec.py` (append a tool-schema contract test)

- [ ] **Step 1: Write the failing contract test (append to `tests/test_worldspec.py`)**

```python
def test_claude_tool_schema_matches_worldspec_and_registry():
    from mapgen.parser.claude_parser import TOOL
    from mapgen.props import all_keys
    from mapgen.spec import WorldSpec, WorldStyle

    props = TOOL["input_schema"]["properties"]
    # every world_style enum value is a valid WorldStyle
    for v in props["world_style"]["enum"]:
        WorldStyle(v)
    # the prop generator enum is exactly the live registry keys
    gen_enum = props["props"]["items"]["properties"]["generator"]["enum"]
    assert set(gen_enum) == set(all_keys())

    # a representative tool payload validates against WorldSpec
    sample = {
        "name": "Riverside",
        "world_style": "lowpoly_nature",
        "extent_m": 400.0,
        "terrain": {"features": [{"type": "river", "direction": "east"}]},
        "props": [{"generator": "tree.conifer", "count": 30, "region": "north", "density": "dense"}],
    }
    w = WorldSpec.model_validate(sample)
    assert w.terrain.has_water and w.props[0].generator == "tree.conifer"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_worldspec.py::test_claude_tool_schema_matches_worldspec_and_registry -q`
Expected: FAIL (old `TOOL` has `emit_scene_spec` / `is_real_location`, no `props`).

- [ ] **Step 3: Rewrite the rule parser to emit WorldSpec**

In `mapgen/parser/rule_parser.py`:

Update imports:
```python
from ..spec import (
    Direction, FeatureType, TerrainFeature, TerrainSpec, WorldStyle, WorldSpec, Size,
)
```

Replace `_STYLE_WORDS` keys with `WorldStyle`:
```python
_STYLE_WORDS = {
    WorldStyle.urban: ["city", "urban", "downtown", "buildings", "skyline", "town", "village"],
    WorldStyle.alpine: ["alpine", "mountain", "mountains", "snow", "peak", "topographic"],
    WorldStyle.desert: ["desert", "dunes", "sand", "arid"],
    WorldStyle.schematic: ["schematic", "diagram", "abstract", "clean"],
    WorldStyle.fantasy: ["fantasy", "stylized", "epic", "rpg", "magic"],
    WorldStyle.minimal: ["minimal", "grayscale", "greyscale", "wireframe"],
    WorldStyle.lowpoly_nature: ["terrain", "relief", "natural", "landscape", "forest", "nature"],
}
```

Trim `_FEATURE_WORDS` to the reduced `FeatureType` set (drop `park`, `building`, `district`, `road`, `landmark` — those become props in M2):
```python
_FEATURE_WORDS = {
    FeatureType.mountain: ["mountain", "mountains", "peak", "peaks", "summit", "alps", "volcano"],
    FeatureType.hill: ["hill", "hills", "ridge", "knoll"],
    FeatureType.valley: ["valley", "canyon", "gorge", "ravine"],
    FeatureType.lake: ["lake", "pond", "reservoir"],
    FeatureType.river: ["river", "stream", "creek", "brook"],
    FeatureType.sea: ["sea", "ocean"],
    FeatureType.coast: ["coast", "coastal", "shore", "beach", "seaside"],
    FeatureType.forest: ["forest", "woods", "woodland", "trees", "jungle"],
    FeatureType.desert: ["desert", "dunes", "sand"],
}
```

Replace the `parse` method body and helpers that referenced location/real/extent_km. The rule parser no longer geocodes; it produces a name + style + extent_m + terrain features (no props — the offline parser leaves `props=[]`; the Claude parser populates props):
```python
class RuleParser(Parser):
    def parse(self, prompt: str) -> WorldSpec:
        text = prompt.strip()
        low = text.lower()
        style = self._style(low)
        return WorldSpec(
            name=self._name(text),
            world_style=style,
            extent_m=self._extent_m(low, style),
            seed=self.config.seed,
            terrain=TerrainSpec(features=self._features(low)),
            props=[],
            notes="Parsed offline with the rule-based parser (heuristic).",
        )

    def _name(self, text: str) -> str:
        # first 6 words, title-cased, as a friendly world name
        words = re.findall(r"[A-Za-z][\w'-]*", text)[:6]
        return " ".join(w.capitalize() for w in words) or "World"

    def _style(self, low: str) -> WorldStyle:
        for style, words in _STYLE_WORDS.items():
            if any(w in low for w in words):
                return style
        return WorldStyle.lowpoly_nature

    def _extent_m(self, low: str, style: WorldStyle) -> float:
        m = re.search(r"(\d+(?:\.\d+)?)\s*m(?:eter|etre)?s?\b", low)
        if m:
            return max(10.0, min(20000.0, float(m.group(1))))
        km = re.search(r"(\d+(?:\.\d+)?)\s*km\b", low)
        if km:
            return max(10.0, min(20000.0, float(km.group(1)) * 1000.0))
        if style == WorldStyle.urban:
            return 600.0
        return 300.0
```

Keep `_features`, `_direction_near`, `_size` as-is but change the `GeoFeature(...)` construction inside `_features` to `TerrainFeature(...)`. Delete the now-unused location helpers (`_titlecase`, `_clean_loc`, `_is_placeish`, `_location`, the `_STRONG_LOC`/`_PREP_LOC`/`_MEASURE_RE` regexes, `_CAP_STOP`, `_FICTIONAL`, `_REAL_INTENT`, `_FEATURE_TOKENS`) and the `from ..scale import scale_to_extent_km` import.

- [ ] **Step 4: Rewrite the Claude parser tool schema (registry-driven props)**

Replace the contents of `mapgen/parser/claude_parser.py` with:

```python
"""Claude-backed parser: tool-use forces the model to emit a structured WorldSpec,
validated with Pydantic. The tool schema is derived from the model + the live prop
registry so the two never drift apart."""

from __future__ import annotations

import json

from ..config import Config
from ..props import all_keys
from ..spec import WorldSpec
from .base import Parser

SYSTEM_PROMPT = """You are a world-design extraction engine for a procedural 3D \
game-world generator. Given a user's natural-language prompt, call the \
`emit_world_spec` tool with a precise structured specification.

Rules:
- `name`: a short world/level name derived from the prompt.
- `world_style`: lowpoly_nature (default), fantasy, urban, desert, alpine, \
schematic, or minimal.
- `extent_m`: side length of the square world in METERS. A small scene ~150-300m, \
a village ~400-800m, a large region ~2000m+. Default 300.
- `terrain.features`: every relief element (mountain, hill, valley, lake, river, \
sea, coast, forest, desert) with its direction and relative size. Do not invent.
- `props`: discrete objects to scatter, each naming a `generator` from the allowed \
list, a `count`, a `region` (a compass direction, "scatter", "edge", or "cluster"), \
and a `density`. Use props for trees, rocks, barrels, houses — NOT for terrain relief.
- Put assumptions in `notes`.

Always respond by calling the tool exactly once."""


def _build_tool() -> dict:
    return {
        "name": "emit_world_spec",
        "description": "Emit the structured procedural 3D world specification.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "world_style": {
                    "type": "string",
                    "enum": [
                        "lowpoly_nature", "fantasy", "urban",
                        "desert", "alpine", "schematic", "minimal",
                    ],
                },
                "extent_m": {"type": "number", "description": "Square world side, meters."},
                "terrain": {
                    "type": "object",
                    "properties": {
                        "features": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "type": {
                                        "type": "string",
                                        "enum": [
                                            "mountain", "hill", "valley", "water",
                                            "river", "lake", "sea", "coast",
                                            "forest", "plain", "desert",
                                        ],
                                    },
                                    "name": {"type": "string"},
                                    "direction": {
                                        "type": "string",
                                        "enum": [
                                            "north", "south", "east", "west",
                                            "northeast", "northwest", "southeast",
                                            "southwest", "center",
                                        ],
                                    },
                                    "relative_size": {
                                        "type": "string",
                                        "enum": ["small", "medium", "large"],
                                    },
                                    "description": {"type": "string"},
                                },
                                "required": ["type"],
                            },
                        }
                    },
                },
                "props": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "generator": {"type": "string", "enum": all_keys()},
                            "count": {"type": "integer"},
                            "region": {"type": "string"},
                            "density": {
                                "type": "string",
                                "enum": ["small", "medium", "large"],
                            },
                            "params": {"type": "object"},
                            "on": {"type": "string", "enum": ["ground", "water"]},
                        },
                        "required": ["generator"],
                    },
                },
                "notes": {"type": "string"},
            },
            "required": ["name", "world_style", "extent_m"],
        },
    }


TOOL = _build_tool()


class ClaudeParser(Parser):
    def __init__(self, config: Config):
        super().__init__(config)
        if not config.anthropic_api_key:
            raise RuntimeError(
                "ClaudeParser requires ANTHROPIC_API_KEY. "
                "Set it, or use the 'rule' parser backend."
            )
        from anthropic import Anthropic

        self._client = Anthropic(api_key=config.anthropic_api_key)

    def parse(self, prompt: str) -> WorldSpec:
        resp = self._client.messages.create(
            model=self.config.model,
            max_tokens=2000,
            system=[{"type": "text", "text": SYSTEM_PROMPT,
                     "cache_control": {"type": "ephemeral"}}],
            tools=[TOOL],
            tool_choice={"type": "tool", "name": "emit_world_spec"},
            messages=[{"role": "user", "content": prompt}],
        )
        tool_input = None
        for block in resp.content:
            if getattr(block, "type", None) == "tool_use" and block.name == "emit_world_spec":
                tool_input = block.input
                break
        if tool_input is None:
            raise RuntimeError(
                "Claude did not return a tool call. Raw: "
                + json.dumps([b.model_dump() for b in resp.content])[:500]
            )
        return WorldSpec.model_validate(tool_input)
```

- [ ] **Step 5: Update parser base + package exports**

In `mapgen/parser/base.py`: change `from ..spec import SceneSpec` → `from ..spec import WorldSpec` and the abstract return type `-> SceneSpec` → `-> WorldSpec`.

In `mapgen/parser/__init__.py`: change `from ..spec import SceneSpec` → `from ..spec import WorldSpec`, drop `SceneSpec` from `__all__`, and update the docstring "Prompt -> WorldSpec parsing."

- [ ] **Step 6: Run the contract + rule-parser tests**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_worldspec.py -q`
Expected: PASS (including the tool-schema contract test).

- [ ] **Step 7: Commit**

```powershell
git add mapgen/parser tests/test_worldspec.py
git commit -m "feat: parsers emit WorldSpec; Claude tool-schema props enum from registry"
```

---

## Task 12: Update package root, exporters default, and CLI

**Files:**
- Modify: `mapgen/__init__.py`
- Modify: `mapgen/export/exporters.py`, `mapgen/export/__init__.py`
- Modify: `cli.py`

- [ ] **Step 1: Update `mapgen/__init__.py`**

Replace any `SceneSpec` export with `WorldSpec`:
```python
from .spec import WorldSpec
from .pipeline import Pipeline, PipelineResult
__all__ = ["Pipeline", "PipelineResult", "WorldSpec"]
```
(Match the existing file's structure; only the spec name changes.)

- [ ] **Step 2: Drop the Blender format from exporters**

In `mapgen/export/exporters.py`: change `FORMATS = ("glb", "obj", "stl", "blender")` → `FORMATS = ("glb", "obj", "stl")` and delete the `elif fmt == "blender":` branch and the `from .blender import write_blender_script` import. (Leave `mapgen/export/blender.py` on disk; it is simply no longer wired in. Optionally `git mv mapgen/export/blender.py legacy/blender_export.py` — do this only if it has no other importers, which a `grep write_blender_script` confirms.)

- [ ] **Step 3: Rewrite the CLI for the procedural-only world tool**

Replace `cli.py`'s argument parser and `main` wiring. Remove `--location`, `--real`, `--procedural`, `--offline`; change `--extent` to meters; default formats to `glb obj stl`:

```python
    ap.add_argument("prompt", help="Description of the world/level to generate.")
    ap.add_argument("--out", default="output", help="Output directory (default: output).")
    ap.add_argument("--formats", nargs="+", default=["glb", "obj", "stl"],
                    metavar="FMT", help=f"Any of: {', '.join(FORMATS)}.")
    ap.add_argument("--name", default=None, help="Output basename (default: from world name).")
    ap.add_argument("--parser", choices=["auto", "claude", "rule"], default=None,
                    help="Override parser backend (default: auto).")
    ap.add_argument("--model", default=None, help="Override Claude model id.")
    ap.add_argument("--resolution", type=int, default=None,
                    help="Terrain grid resolution per side (default 96).")
    ap.add_argument("--seed", type=int, default=None, help="Procedural seed.")
    ap.add_argument("--json", action="store_true", help="Also print the WorldSpec as JSON.")
    ap.add_argument("--extent", type=float, default=None, metavar="METERS",
                    help="Override the world side length in meters.")
    args = ap.parse_args(argv)
```

In the config/override wiring, remove the `--offline` block, and build overrides as:
```python
    overrides = {"extent_m": args.extent, "seed": args.seed}
```
In `_styled_summary`, replace the rows that referenced `spec.location`, `is_real_location`, `spec.map_style`, `spec.extent_km`, `build.used_real_data`, and `buildings` with:
```python
    rows = [
        ("Prompt", result.prompt),
        ("World", spec.name),
        ("Style", f"{spec.world_style.value}   ·   extent {spec.extent_m} m"),
        ("Features", ", ".join(result._feat()) or "(none)"),
        ("Props", f"{sum(p.count for p in spec.props)} ({len(spec.props)} intents)"),
    ]
```
(Delete the `if build.stats.get("trees")` block.)

- [ ] **Step 4: Smoke-test the CLI**

Run: `.\.venv\Scripts\python.exe cli.py "a fantasy valley with a lake, forest to the west" --parser rule --resolution 48 --out output/_cli`
Expected: exits 0; prints the styled summary; `output/_cli/*.glb/.obj/.stl` written.

- [ ] **Step 5: Commit**

```powershell
git add mapgen/__init__.py mapgen/export cli.py
git commit -m "refactor: CLI + exporters for procedural world tool (meters, no geo flags)"
```

---

## Task 13: Update the web app + worker

**Files:**
- Modify: `web/generate.py`
- Modify: `worker/app.py`

- [ ] **Step 1: Update `web/generate.py`**

Remove `use_network`/real-data usage. `_build_config` drops `cfg.use_network`. `_run_sync` drops `use_real`, switches `extent_km`→`extent_m`, and the returned dict drops `is_real`, `used_real_data`, `lat`, `lon`:

```python
def _build_config():
    from mapgen.config import Config
    cfg = Config.from_env()
    cfg.terrain_resolution = settings.GEN_RESOLUTION
    cfg.parser_backend = "auto"
    return cfg


def _run_sync(prompt: str, gen_id: str, extent_m: float) -> dict:
    from mapgen import Pipeline
    cfg = _build_config()
    pipe = Pipeline(config=cfg)
    overrides = {
        "extent_m": min(max(extent_m, 50.0), settings.GEN_MAX_EXTENT_M),
        "max_extent_m": settings.GEN_MAX_EXTENT_M,
    }
    out_dir = OUTPUTS_DIR / gen_id
    result = pipe.run(prompt, out_dir=out_dir,
                      formats=list(settings.GEN_FORMATS), basename="scene",
                      overrides=overrides)
    files = {fmt: Path(p).name for fmt, p in result.files.items()}
    return {
        "id": gen_id,
        "files": files,
        "name": result.spec.name,
        "style": result.spec.world_style.value,
        "extent_m": result.spec.extent_m,
        "stats": result.build.stats,
        "features": result._feat(),
    }


async def run_generation(prompt: str, extent_m: float) -> dict:
    gen_id = uuid.uuid4().hex
    async with _semaphore:
        loop = asyncio.get_running_loop()
        try:
            return await asyncio.wait_for(
                loop.run_in_executor(None, _run_sync, prompt, gen_id, extent_m),
                timeout=settings.GEN_TIMEOUT_S,
            )
        except asyncio.TimeoutError:
            raise TimeoutError("Generation timed out. Try a smaller world.")
```

> `settings.GEN_MAX_EXTENT_M` replaces `GEN_MAX_EXTENT_KM`, and `GEN_FORMATS` should no longer include `"blender"`. Update `web/config.py` accordingly (rename the env-backed field; default e.g. `6000.0` meters; formats `("glb","obj","stl")`). Update `worker/app.py`'s analogous `WORKER_MAX_EXTENT_KM`/extent handling and any `use_real`/`lat`/`lon` in its response the same way. Find callers:

Run: `.\.venv\Scripts\python.exe -m pytest -q` is not enough here — also grep:
`run_generation(`, `use_real`, `extent_km`, `GEN_MAX_EXTENT_KM`, `MAX_EXTENT_KM` across `web/` and `worker/`, and update each callsite to the meters API. (The viewer JS in `web/static/js/app.js` reads `is_real`/`lat`/`lon`/`style`; remove those references and read `name`/`style`/`extent_m` instead.)

- [ ] **Step 2: Update `worker/app.py` to the meters API**

Mirror the `web/generate.py` changes in `worker/app.py`: drop `use_real`, rename extent to meters, drop `lat`/`lon`/`is_real`/`used_real_data` from the response payload, and update the env var `WORKER_MAX_EXTENT_KM`→`WORKER_MAX_EXTENT_M` (default `6000`). Keep the ticket/secret/CORS logic unchanged.

- [ ] **Step 3: Verify the web app imports cleanly (no geo, no SceneSpec)**

Run: `.\.venv\Scripts\python.exe -c "import web.app; import worker.app; print('web+worker import ok')"`
Expected: prints `web+worker import ok` with no ImportError.

- [ ] **Step 4: Commit**

```powershell
git add web worker
git commit -m "refactor: web + worker to procedural meters API; drop real-data fields"
```

---

## Task 14: Rewrite the pipeline tests for the procedural world

**Files:**
- Modify: `tests/test_pipeline.py`

- [ ] **Step 1: Replace `tests/test_pipeline.py`**

```python
"""Smoke + contract tests for the procedural world pipeline.
Run: .\\.venv\\Scripts\\python.exe -m pytest tests -q
"""

from __future__ import annotations

import json
import os
import struct
import sys
import tempfile

import numpy as np
import trimesh

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mapgen import Pipeline, WorldSpec
from mapgen.config import Config
from mapgen.parser.rule_parser import RuleParser
from mapgen.spec import Direction, FeatureType, WorldStyle

GAMEDEV_PROMPTS = [
    "medieval village on a hill",
    "alpine valley with a river",
    "desert canyon",
]


def _offline_config(res: int = 64) -> Config:
    cfg = Config()
    cfg.parser_backend = "rule"
    cfg.terrain_resolution = res
    return cfg


def _glb_primitive_attributes(path: str) -> list[list[str]]:
    data = open(path, "rb").read()
    json_len = struct.unpack("<I", data[12:16])[0]
    gltf = json.loads(data[20 : 20 + json_len])
    return [
        list(prim["attributes"].keys())
        for mesh in gltf.get("meshes", [])
        for prim in mesh["primitives"]
    ]


def test_rule_parser_directions():
    spec = RuleParser(Config()).parse(
        "a coastal world with mountains to the north and a forest to the west"
    )
    dirs = {f.type: f.direction for f in spec.terrain.features}
    assert dirs[FeatureType.mountain] == Direction.north
    assert dirs[FeatureType.forest] == Direction.west


def test_offline_pipeline_exports_all_formats():
    cfg = _offline_config(48)
    with tempfile.TemporaryDirectory() as d:
        res = Pipeline(config=cfg).run(
            "a fantasy valley with a lake in the center",
            out_dir=d, formats=["glb", "obj", "stl"], basename="t",
        )
        for fmt in ("glb", "obj", "stl"):
            assert fmt in res.files and os.path.getsize(res.files[fmt]) > 0
        assert res.build.stats["terrain_faces"] > 0


def test_exported_files_carry_normals():
    cfg = _offline_config()
    for prompt in GAMEDEV_PROMPTS:
        with tempfile.TemporaryDirectory() as d:
            res = Pipeline(config=cfg).run(prompt, out_dir=d, formats=["glb", "obj"], basename="t")
            attrs = _glb_primitive_attributes(res.files["glb"])
            assert attrs, f"{prompt!r}: GLB had no mesh primitives"
            assert all("NORMAL" in a for a in attrs), f"{prompt!r}: missing NORMAL ({attrs})"
            assert "\nvn " in open(res.files["obj"]).read(), f"{prompt!r}: OBJ has no normals"


def test_river_prompt_produces_water():
    cfg = _offline_config()
    for prompt in ("alpine valley with a river", "a world with a wide river"):
        with tempfile.TemporaryDirectory() as d:
            res = Pipeline(config=cfg).run(prompt, out_dir=d, formats=["glb"], basename="t")
            assert res.build.stats.get("water"), f"{prompt!r}: no water generated"
            assert res.build.heightfield.sea_level is not None


def test_meshes_are_clean():
    cfg = _offline_config()
    for prompt in GAMEDEV_PROMPTS:
        res = Pipeline(config=cfg).run(prompt, out_dir=tempfile.mkdtemp(), basename="t")
        for name, g in res.build.scene.geometry.items():
            if not isinstance(g, trimesh.Trimesh):
                continue
            assert not np.isnan(g.vertices).any(), f"{prompt!r}/{name}: NaN vertices"
            tri = g.vertices[g.faces]
            area = 0.5 * np.linalg.norm(
                np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0]), axis=1
            )
            assert not (area < 1e-9).any(), f"{prompt!r}/{name}: degenerate faces"


def test_determinism_same_seed_same_geometry():
    cfg = _offline_config(48)
    a = Pipeline(config=cfg).run("a fantasy hill", out_dir=tempfile.mkdtemp(), basename="t")
    b = Pipeline(config=cfg).run("a fantasy hill", out_dir=tempfile.mkdtemp(), basename="t")
    ga = a.build.scene.geometry["terrain"]
    gb = b.build.scene.geometry["terrain"]
    np.testing.assert_allclose(ga.vertices, gb.vertices)
```

- [ ] **Step 2: Run the entire suite**

Run: `.\.venv\Scripts\python.exe -m pytest tests -q`
Expected: PASS — `tests/test_worldspec.py`, `tests/test_props.py`, `tests/test_pipeline.py` all green.

- [ ] **Step 3: Commit**

```powershell
git add tests/test_pipeline.py
git commit -m "test: procedural world pipeline suite (determinism, normals, water, clean meshes)"
```

---

## Task 15: Docs sync

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Update the README's product framing and usage**

Edit `README.md`:
- Change the title/intro from "prompt → 3D map pipeline" to "prompt → procedural 3D game world (terrain + low-poly props)".
- Replace the pipeline diagram with the 5-stage `Parse → Plan → Build → Assemble → Export` flow from the spec, marked "(placement = M2)".
- Remove the real-world / OSM / `--location` / `--real` / `--offline` sections.
- Replace CLI examples with meters-based procedural ones, e.g.
  `python cli.py "a fantasy valley with a lake, forest to the west" --extent 400`.
- Update the formats table (drop Blender) and the "How each stage works" section to procedural-only.
- Note that prop generators exist and are AI-selectable, but placement into the scene ships in M2.

- [ ] **Step 2: Verify no stale geo references remain in user docs**

Run: search for leftover terms.
`.\.venv\Scripts\python.exe -m pytest tests -q` (still green) and a grep for `is_real_location`, `extent_km`, `OSM`, `Nominatim`, `--location`, `blender` in `README.md` returns nothing (or only intentional mentions).

- [ ] **Step 3: Commit**

```powershell
git add README.md
git commit -m "docs: README for procedural game-world tool (M0)"
```

---

## Self-Review (completed)

**Spec coverage:**
- Archive geo → Task 1. ✓
- `SceneSpec`→`WorldSpec` (drop `is_real_location`, add `seed`/`props`, `extent_m`, `world_style`) → Task 2. ✓
- Procedural-only parser tool-schema, CLI, web/worker, tests → Tasks 10–14. ✓
- `mapgen/props/` registry + `PropMesh` + poly budgets → Tasks 3–4. ✓
- 3–5 generators (rock, conifer, broadleaf, barrel, cottage) → Tasks 5–8. ✓
- Registry → AI tool-schema → Task 11 (`all_keys()` feeds the props enum). ✓
- "Pipeline emits terrain only; placement is M2; props testable standalone" → Tasks 9–10 keep build terrain-only; `stats["prop_intents"]` records intent count. ✓

**Placeholder scan:** No "TBD/TODO". Generator and test code is complete. The only conditional guidance (Task 6 budget fallback, Task 12 optional `git mv`) is explicit with the actual change to make.

**Type consistency:** `WorldSpec`, `WorldStyle`, `TerrainSpec`, `TerrainFeature`, `PropIntent`, `PropMesh`, `GeneratorEntry`, `register/get/all_keys/build`, `build_scene(spec, config)`, `procedural(spec, res, seed)` are used identically across tasks. `material_id` values (`rock`, `foliage`, `wood`, `building`) are consistent; they will be consumed by the M2 material/palette mapping.

**Out-of-scope guardrails:** No placement, LOD, collision, UV, or Y-up conversion — all correctly deferred to M2/v2 per the spec.

---

## Open follow-ups for M2 (not in this plan)

- Y-up + meters export conversion (glTF axis).
- `placement.py` (regions → masks → Poisson-disk transforms, terrain snapping).
- Scene assembly with shared meshes + `EXT_mesh_gpu_instancing` + `manifest.json`.
- Material palette mapping `material_id` → per-`world_style` PBR colors.
