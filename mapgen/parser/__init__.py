"""Prompt -> SceneSpec parsing. Pluggable backends behind one interface."""

from __future__ import annotations

from ..config import Config
from ..spec import SceneSpec
from .base import Parser
from .claude_parser import ClaudeParser
from .rule_parser import RuleParser


def make_parser(config: Config) -> Parser:
    """Select a parser backend from config, falling back gracefully.

    auto:   use Claude if an API key is present, otherwise rule-based.
    claude: force Claude (raises if no key).
    rule:   force the offline rule parser.
    """
    backend = config.parser_backend
    if backend == "rule":
        return RuleParser(config)
    if backend == "claude":
        return ClaudeParser(config)
    # auto
    if config.anthropic_api_key:
        return ClaudeParser(config)
    return RuleParser(config)


__all__ = ["Parser", "ClaudeParser", "RuleParser", "make_parser", "SceneSpec"]
