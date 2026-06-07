"""Procedural prop generators. The AI never produces geometry: it emits
PropIntents naming a generator key + params; code here owns every vertex,
so output is low-poly and deterministic."""

from .base import PropMesh, from_trimesh

__all__ = ["PropMesh", "from_trimesh"]
