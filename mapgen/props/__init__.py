"""Procedural prop generators. Importing this package registers every generator.

The AI never produces geometry: it emits PropIntents naming a generator key +
params; code here owns every vertex, so output is low-poly and deterministic."""

from .base import PropMesh, from_trimesh
from .registry import GeneratorEntry, all_keys, build, get, register

# Import the generator modules for their registration side effects.
from . import generators  # noqa: E402,F401

__all__ = [
    "PropMesh", "from_trimesh", "GeneratorEntry",
    "register", "get", "all_keys", "build",
]
