"""Claude-backed parser: uses tool-use to force the model to emit a structured
SceneSpec, which we then validate with Pydantic. The tool schema is derived
from the Pydantic model so the two never drift apart."""

from __future__ import annotations

import json

from ..config import Config
from ..spec import SceneSpec
from .base import Parser

SYSTEM_PROMPT = """You are a geospatial scene-extraction engine for a 3D map \
generation pipeline. Given a user's natural-language prompt describing a place, \
its surroundings, and the kind of map they want, extract a precise structured \
specification by calling the `emit_scene_spec` tool.

Rules:
- `location` is the core place: copy the user's place name/phrase faithfully.
- `is_real_location` is true ONLY for places that exist on Earth and could be \
geocoded (cities, mountains, real addresses, regions). Fictional, abstract, or \
purely-described places ("a valley between two volcanoes") are false.
- Infer `map_style` from intent words: "city/urban/buildings" -> city, \
"contour/topo/elevation lines" -> topographic, "satellite/aerial" -> satellite, \
"diagram/clean/abstract" -> schematic, "stylized/epic/game" -> fantasy, \
otherwise terrain.
- `extent_km`: estimate the area to model. A neighbourhood ~1-2km, a town ~5km, \
a city ~10-20km, a mountain range ~30-60km. Default 2 if unclear.
- Decompose every described surrounding into one `features` entry with its \
direction and relative size. Capture mountains, water, forests, districts, \
roads, landmarks. Do not invent features the user did not imply.
- Put any assumptions you made into `notes`.

Always respond by calling the tool exactly once."""

TOOL = {
    "name": "emit_scene_spec",
    "description": "Emit the structured 3D scene specification.",
    "input_schema": {
        "type": "object",
        "properties": {
            "location": {
                "type": "string",
                "description": "Raw location phrase from the prompt.",
            },
            "is_real_location": {
                "type": "boolean",
                "description": "True only if a real, geocodable place on Earth.",
            },
            "map_style": {
                "type": "string",
                "enum": [
                    "topographic", "terrain", "satellite",
                    "city", "schematic", "fantasy", "minimal",
                ],
            },
            "extent_km": {
                "type": "number",
                "description": "Side length of the square area to model, in km.",
            },
            "features": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "type": {
                            "type": "string",
                            "enum": [
                                "mountain", "hill", "valley", "water", "river",
                                "lake", "sea", "coast", "forest", "park",
                                "desert", "plain", "building", "district",
                                "road", "landmark",
                            ],
                        },
                        "name": {"type": "string"},
                        "direction": {
                            "type": "string",
                            "enum": [
                                "north", "south", "east", "west", "northeast",
                                "northwest", "southeast", "southwest", "center",
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
            },
            "notes": {"type": "string"},
        },
        "required": ["location", "is_real_location", "map_style", "features"],
    },
}


class ClaudeParser(Parser):
    def __init__(self, config: Config):
        super().__init__(config)
        if not config.anthropic_api_key:
            raise RuntimeError(
                "ClaudeParser requires ANTHROPIC_API_KEY. "
                "Set it, or use the 'rule' parser backend."
            )
        # Imported lazily so the package works without the SDK installed.
        from anthropic import Anthropic

        self._client = Anthropic(api_key=config.anthropic_api_key)

    def parse(self, prompt: str) -> SceneSpec:
        resp = self._client.messages.create(
            model=self.config.model,
            max_tokens=2000,
            system=[
                {
                    "type": "text",
                    "text": SYSTEM_PROMPT,
                    # Cache the long static system prompt across calls.
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            tools=[TOOL],
            tool_choice={"type": "tool", "name": "emit_scene_spec"},
            messages=[{"role": "user", "content": prompt}],
        )

        tool_input = None
        for block in resp.content:
            if getattr(block, "type", None) == "tool_use" and block.name == "emit_scene_spec":
                tool_input = block.input
                break
        if tool_input is None:
            raise RuntimeError(
                "Claude did not return a tool call. Raw: "
                + json.dumps([b.model_dump() for b in resp.content])[:500]
            )

        return SceneSpec.model_validate(tool_input)
