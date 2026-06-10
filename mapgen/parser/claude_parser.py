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
                                "enum": ["sparse", "medium", "dense"],
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
