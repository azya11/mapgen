"""Map-scale ratios in a prompt control *ground coverage* (zoom).

A phrase like ``1:4`` or ``1:8`` sets how much ground the square map spans:
roughly ``denominator * 0.75`` km per side (1:4 ≈ 3 km, 1:8 ≈ 6 km). Heights
stay true-to-life — only the modelled extent changes. When a ratio is present
it overrides any km value (e.g. the web slider).

``1:1`` is *not* a zoom: it is the conventional "real scale / true-to-life"
marker, handled by the parser's real-world-intent detection, so it is ignored
here.
"""

from __future__ import annotations

import re

# km of ground per unit of the scale denominator.
KM_PER_UNIT = 0.75

# Matches 1:4, 1 : 8, "1:16", etc. Requires the leading 1 so we don't grab
# unrelated numbers, time stamps, or odds like "3:1".
_RATIO_RE = re.compile(r"\b1\s*:\s*(\d{1,3})\b")


def scale_to_extent_km(prompt: str) -> float | None:
    """Return the modelled side length in km implied by a ``1:N`` ratio in the
    prompt, or ``None`` if there is no (zoom) ratio. ``1:1`` returns ``None``."""
    if not prompt:
        return None
    m = _RATIO_RE.search(prompt)
    if not m:
        return None
    denom = int(m.group(1))
    if denom <= 1:  # 1:1 is "true scale", not a zoom level
        return None
    return round(denom * KM_PER_UNIT, 2)
