"""Offline keyword/regex parser. No API key, no network. Brittle on complex
phrasing but lets the whole pipeline run end-to-end for free and in tests."""

from __future__ import annotations

import re

from ..config import Config
from ..scale import scale_to_extent_km
from ..spec import (
    Direction,
    FeatureType,
    GeoFeature,
    MapStyle,
    SceneSpec,
    Size,
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
    FeatureType.park: ["park", "garden"],
    FeatureType.desert: ["desert", "dunes", "sand"],
    FeatureType.district: ["downtown", "district", "neighbourhood", "neighborhood", "suburb"],
    FeatureType.building: ["building", "skyscraper", "tower", "house", "houses"],
    FeatureType.road: ["road", "roads", "street", "streets", "highway", "avenue"],
    FeatureType.landmark: ["landmark", "monument", "cathedral", "castle", "bridge"],
}

_STYLE_WORDS = {
    MapStyle.city: ["city", "urban", "downtown", "buildings", "skyline", "metropolis"],
    MapStyle.topographic: ["topographic", "topo", "contour", "contours", "elevation lines"],
    MapStyle.satellite: ["satellite", "aerial", "orthophoto"],
    MapStyle.schematic: ["schematic", "diagram", "abstract", "clean", "minimalist diagram"],
    MapStyle.fantasy: ["fantasy", "stylized", "epic", "game", "rpg"],
    MapStyle.minimal: ["minimal", "grayscale", "greyscale", "wireframe"],
    MapStyle.terrain: ["terrain", "relief", "natural", "landscape"],
}

_SIZE_WORDS = {
    Size.large: ["large", "huge", "massive", "towering", "vast", "tall", "big"],
    Size.small: ["small", "little", "tiny", "low", "gentle"],
}

# Words that, if present, mark the scene as imaginary -> procedural generation.
_FICTIONAL = (
    "fantasy", "fictional", "fictitious", "imaginary", "made-up", "made up",
    "mythical", "alien", "sci-fi", "procedural", "invented", "dream", "fairy-tale",
)
# Words that signal the user wants a faithful, real-world reconstruction.
_REAL_INTENT = (
    "1:1", "1 to 1", "real", "realistic", "actual", "true to life",
    "true-to-life", "accurate", "real-world", "real world", "satellite",
)

# Capture the place phrase after an explicit "map/model/... of" (keeps "city, country").
_STRONG_LOC = re.compile(
    r"\b(?:3d\s+)?(?:map|model|render|rendering|scene|view|reconstruction)\s+of\s+(.+?)"
    r"(?=$|[.;!?]|\bwith\b|\bthat\b|\btak(?:e|ing)\b|\bsurround\w*|\bfeatur\w*"
    r"|\binclud\w*|\bshow\w*|\bhaving\b|\bconsider\w*|\baccount\w*)",
    re.IGNORECASE,
)
# Fallback: a place after a locational preposition.
_PREP_LOC = re.compile(
    r"\b(?:in|near|around|at|over)\s+(.+?)"
    r"(?=$|[.;!?]|\bwith\b|\band\b|\bthat\b|\btak(?:e|ing)\b|\bsurround\w*"
    r"|\bfeatur\w*|\binclud\w*|\bshow\w*|\bhaving\b|\bconsider\w*|\baccount\w*)",
    re.IGNORECASE,
)

# Capitalised tokens that are command verbs / filler, not place names.
_CAP_STOP = {
    "a", "an", "the", "take", "create", "make", "generate", "build", "render",
    "show", "model", "map", "i", "please", "into", "account", "give", "produce",
}
# Common geographic nouns — a phrase made only of these isn't a real place name.
_FEATURE_TOKENS = {w for words in _FEATURE_WORDS.values() for w in words}
_FEATURE_TOKENS |= set(_DIRECTIONS) | {
    "land", "area", "place", "region", "terrain", "surroundings", "stone", "wood",
}


def _titlecase(loc: str) -> str:
    return " ".join(w[:1].upper() + w[1:] if w else w for w in loc.split())


# Measurement / scale tokens that sometimes get swept into a captured place
# phrase (e.g. "Kyoto 3km", "Tokyo 1:8") and would wreck geocoding precision.
_MEASURE_RE = re.compile(r"\b\d+(?:\.\d+)?\s*k(?:m|ilomet\w*)\b|\b1\s*:\s*\d+\b", re.IGNORECASE)


def _clean_loc(loc: str) -> str:
    """Reduce a captured phrase to a clean place name for the geocoder: cut at
    hard separators that never belong inside a place name (arrows, dashes,
    pipes, colons, semicolons, newlines), drop extent/scale tokens, and keep at
    most the first two comma groups (e.g. "City, Country")."""
    loc = re.split(r"\s*(?:→|->|—|–|\||;|:|\n)\s*", loc, maxsplit=1)[0]
    loc = _MEASURE_RE.sub(" ", loc)
    loc = re.sub(r"\s+", " ", loc).strip(" ,.;")
    parts = [p.strip() for p in loc.split(",") if p.strip()]
    if len(parts) > 2:
        parts = parts[:2]
    return ", ".join(parts)


def _is_placeish(loc: str) -> bool:
    """True unless the phrase is built only from generic geographic nouns."""
    tokens = re.findall(r"[a-z']+", loc.lower())
    tokens = [t for t in tokens if t not in ("of", "the", "a", "an", "and")]
    return any(t not in _FEATURE_TOKENS for t in tokens)


class RuleParser(Parser):
    def parse(self, prompt: str) -> SceneSpec:
        text = prompt.strip()
        low = text.lower()

        location, is_real = self._location(text)
        style = self._style(low)
        extent = self._extent(low, style)
        features = self._features(low)

        return SceneSpec(
            location=location,
            is_real_location=is_real,
            map_style=style,
            extent_km=extent,
            features=features,
            notes="Parsed offline with the rule-based parser (heuristic).",
        )

    # ------------------------------------------------------------------ #
    def _location(self, text: str) -> tuple[str, bool]:
        low = text.lower()
        fictional = any(w in low for w in _FICTIONAL)
        real_intent = any(w in low for w in _REAL_INTENT)

        # 1) explicit "<map/model/...> of <place>" or "<prep> <place>"
        for rx in (_STRONG_LOC, _PREP_LOC):
            m = rx.search(text)
            if not m:
                continue
            loc = _clean_loc(m.group(1))
            if loc and _is_placeish(loc):
                is_real = real_intent or not fictional
                return _titlecase(loc), is_real

        # 2) fallback: longest run of capitalised words that isn't a command verb
        caps = re.findall(r"\b([A-Z][\w'’-]+(?:[ ,]+[A-Z][\w'’-]+)*)", text)
        caps = [c.strip(" ,") for c in caps if c.split()[0].lower() not in _CAP_STOP]
        caps = [c for c in caps if _is_placeish(c)]
        if caps:
            best = max(caps, key=len)
            return best, (real_intent or (not fictional and len(best) > 3))

        return "an unnamed place", False

    def _style(self, low: str) -> MapStyle:
        for style, words in _STYLE_WORDS.items():
            if any(w in low for w in words):
                return style
        return MapStyle.terrain

    def _extent(self, low: str, style: MapStyle) -> float:
        # A "1:N" scale ratio (ground coverage) takes precedence over everything.
        scale_extent = scale_to_extent_km(low)
        if scale_extent is not None:
            return scale_extent
        m = re.search(r"(\d+(?:\.\d+)?)\s*(km|kilomet)", low)
        if m:
            return max(0.1, min(200.0, float(m.group(1))))
        if "range" in low or "region" in low:
            return 40.0
        if style == MapStyle.city or "city" in low:
            return 12.0
        if "town" in low or "village" in low:
            return 5.0
        return 2.0

    def _features(self, low: str) -> list[GeoFeature]:
        found: list[GeoFeature] = []
        for ftype, words in _FEATURE_WORDS.items():
            for w in words:
                for m in re.finditer(r"\b" + re.escape(w) + r"\b", low):
                    anchor = (m.start() + m.end()) // 2
                    window = low[max(0, m.start() - 30): m.end() + 30]
                    found.append(
                        GeoFeature(
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
