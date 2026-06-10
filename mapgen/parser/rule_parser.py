"""Offline keyword/regex parser. No API key, no network. Brittle on complex
phrasing but lets the whole pipeline run end-to-end for free and in tests."""

from __future__ import annotations

import re

from ..config import Config
from ..spec import (
    Direction, FeatureType, TerrainFeature, TerrainSpec, WorldStyle, WorldSpec, Size,
)
from .base import Parser

_DIRECTIONS = {
    "north": Direction.north, "northern": Direction.north,
    "south": Direction.south, "southern": Direction.south,
    "east": Direction.east, "eastern": Direction.east,
    "west": Direction.west, "western": Direction.west,
    "northeast": Direction.northeast, "north-east": Direction.northeast,
    "northwest": Direction.northwest, "north-west": Direction.northwest,
    "southeast": Direction.southeast, "south-east": Direction.southeast,
    "southwest": Direction.southwest, "south-west": Direction.southwest,
}

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

_STYLE_WORDS = {
    WorldStyle.urban: ["city", "urban", "downtown", "buildings", "skyline", "town", "village"],
    WorldStyle.alpine: ["alpine", "mountain", "mountains", "snow", "peak", "topographic"],
    WorldStyle.desert: ["desert", "dunes", "sand", "arid"],
    WorldStyle.schematic: ["schematic", "diagram", "abstract", "clean"],
    WorldStyle.fantasy: ["fantasy", "stylized", "epic", "rpg", "magic"],
    WorldStyle.minimal: ["minimal", "grayscale", "greyscale", "wireframe"],
    WorldStyle.lowpoly_nature: ["terrain", "relief", "natural", "landscape", "forest", "nature"],
}

_SIZE_WORDS = {
    Size.large: ["large", "huge", "massive", "towering", "vast", "tall", "big"],
    Size.small: ["small", "little", "tiny", "low", "gentle"],
}


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

    def _features(self, low: str) -> list[TerrainFeature]:
        found: list[TerrainFeature] = []
        for ftype, words in _FEATURE_WORDS.items():
            for w in words:
                for m in re.finditer(r"\b" + re.escape(w) + r"\b", low):
                    anchor = (m.start() + m.end()) // 2
                    window = low[max(0, m.start() - 30): m.end() + 30]
                    found.append(
                        TerrainFeature(
                            type=ftype,
                            direction=self._direction_near(low, anchor),
                            relative_size=self._size(window),
                        )
                    )
                    break  # one entry per word
        # De-duplicate by (type, direction)
        seen = set()
        unique = []
        for f in found:
            key = (f.type, f.direction)
            if key not in seen:
                seen.add(key)
                unique.append(f)
        return unique

    def _direction_near(self, text: str, anchor: int) -> Direction | None:
        """Pick the compass word closest to the feature mention (within 40 chars),
        so 'a forest to the west' beats an earlier 'north' belonging to something
        else. Longer words (northeast) are matched before shorter (north)."""
        # Strongest signal: a "<feature> ... to/toward/on the <dir>" phrase that
        # starts right after the feature mention binds the direction to it.
        tail = text[anchor: anchor + 35]
        m = re.search(r"\b(?:to|toward|towards|on|in|along)\s+the\s+([a-z-]+)", tail)
        if m and m.group(1) in _DIRECTIONS:
            return _DIRECTIONS[m.group(1)]

        best: Direction | None = None
        best_dist = 41
        for word in sorted(_DIRECTIONS, key=len, reverse=True):
            for m in re.finditer(r"\b" + re.escape(word) + r"\b", text):
                dist = abs(((m.start() + m.end()) // 2) - anchor)
                if dist < best_dist:
                    best_dist = dist
                    best = _DIRECTIONS[word]
        return best

    def _size(self, window: str) -> Size:
        for size, words in _SIZE_WORDS.items():
            if any(w in window for w in words):
                return size
        return Size.medium
