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
