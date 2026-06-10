"""Runtime configuration. Reads from environment, with sane defaults so the
pipeline runs offline (rule parser + procedural geometry) with zero setup."""

from __future__ import annotations

import os
from dataclasses import dataclass


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
