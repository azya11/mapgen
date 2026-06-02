"""Runtime configuration. Reads from environment, with sane defaults so the
pipeline runs offline (rule parser + procedural geometry) with zero setup."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass
class Config:
    # --- AI parser ---
    anthropic_api_key: str | None = None
    model: str = "claude-sonnet-4-6"   # fast + cheap for structured extraction
    parser_backend: str = "auto"        # auto | claude | rule

    # --- geo data sources (all free, no key) ---
    nominatim_url: str = "https://nominatim.openstreetmap.org/search"
    overpass_url: str = "https://overpass-api.de/api/interpreter"
    overpass_mirrors: tuple[str, ...] = (
        "https://overpass-api.de/api/interpreter",
        "https://overpass.kumi.systems/api/interpreter",
        "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
    )
    elevation_url: str = "https://api.open-meteo.com/v1/elevation"
    user_agent: str = "mapgen/0.1 (3D map generator; https://github.com/azya11/mapgen)"
    request_timeout: int = 30
    overpass_timeout: int = 75          # Overpass is slow for dense cities
    osm_max_extent_km: float = 6.0      # cap the building query; shrinks on failure
    use_network: bool = True            # set False to force procedural

    # --- geometry ---
    terrain_resolution: int = 96        # grid cells per side
    seed: int = 1234

    @classmethod
    def from_env(cls) -> "Config":
        c = cls()
        c.anthropic_api_key = os.environ.get("ANTHROPIC_API_KEY")
        c.model = os.environ.get("MAPGEN_MODEL", c.model)
        c.parser_backend = os.environ.get("MAPGEN_PARSER", c.parser_backend)
        if os.environ.get("MAPGEN_OFFLINE", "").lower() in ("1", "true", "yes"):
            c.use_network = False
        if os.environ.get("MAPGEN_RESOLUTION"):
            c.terrain_resolution = int(os.environ["MAPGEN_RESOLUTION"])
        if os.environ.get("MAPGEN_SEED"):
            c.seed = int(os.environ["MAPGEN_SEED"])
        return c
