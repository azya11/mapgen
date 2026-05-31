"""Terminal styling — a cohesive cyan→violet theme that matches the 3D viewer,
with graceful degradation when the terminal has no truecolor/ANSI support."""

from __future__ import annotations

import os
import sys

# Enable ANSI on legacy Windows consoles.
if os.name == "nt":
    os.system("")  # noqa: S605 - turns on virtual terminal processing

_NO_COLOR = (
    not sys.stderr.isatty()
    or os.environ.get("NO_COLOR")
    or os.environ.get("MAPGEN_NO_COLOR")
)


def _rgb(r: int, g: int, b: int) -> str:
    return "" if _NO_COLOR else f"\x1b[38;2;{r};{g};{b}m"


RESET = "" if _NO_COLOR else "\x1b[0m"
BOLD = "" if _NO_COLOR else "\x1b[1m"
DIM = "" if _NO_COLOR else "\x1b[2m"

# Palette mirrors the viewer (--c1 aqua, --c2 periwinkle, --c3 violet).
AQUA = _rgb(52, 231, 228)
BLUE = _rgb(106, 141, 255)
VIOLET = _rgb(176, 108, 255)
TXT = _rgb(233, 238, 248)
MUTED = _rgb(138, 149, 173)
GOOD = _rgb(86, 214, 142)
WARN = _rgb(255, 180, 90)


def c(text: str, color: str, bold: bool = False) -> str:
    return f"{BOLD if bold else ''}{color}{text}{RESET}"


# Gradient sweep across the wordmark.
_GRAD = [(52, 231, 228), (84, 170, 244), (106, 141, 255), (150, 122, 255), (176, 108, 255)]


def _gradient(text: str) -> str:
    if _NO_COLOR or not text:
        return text
    out = []
    n = max(len(text) - 1, 1)
    for i, ch in enumerate(text):
        t = i / n * (len(_GRAD) - 1)
        lo = int(t)
        hi = min(lo + 1, len(_GRAD) - 1)
        f = t - lo
        r = int(_GRAD[lo][0] + (_GRAD[hi][0] - _GRAD[lo][0]) * f)
        g = int(_GRAD[lo][1] + (_GRAD[hi][1] - _GRAD[lo][1]) * f)
        b = int(_GRAD[lo][2] + (_GRAD[hi][2] - _GRAD[lo][2]) * f)
        out.append(f"{_rgb(r, g, b)}{ch}")
    return "".join(out) + RESET


def banner() -> str:
    art = [
        "                                            ",
        "   ███╗   ███╗ █████╗ ██████╗  ██████╗ ███████╗███╗   ██╗",
        "   ████╗ ████║██╔══██╗██╔══██╗██╔════╝ ██╔════╝████╗  ██║",
        "   ██╔████╔██║███████║██████╔╝██║  ███╗█████╗  ██╔██╗ ██║",
        "   ██║╚██╔╝██║██╔══██║██╔═══╝ ██║   ██║██╔══╝  ██║╚██╗██║",
        "   ██║ ╚═╝ ██║██║  ██║██║     ╚██████╔╝███████╗██║ ╚████║",
        "   ╚═╝     ╚═╝╚═╝  ╚═╝╚═╝      ╚═════╝ ╚══════╝╚═╝  ╚═══╝",
    ]
    lines = "\n".join(_gradient(line) for line in art)
    tag = c("   prompt → 3D map pipeline", MUTED)
    return f"\n{lines}\n{tag}\n"


# Cycle stage labels through the gradient colours.
_STAGE_COLORS = [AQUA, BLUE, VIOLET, GOOD]


def stage(text: str) -> str:
    """Colourise a '[n/4] ...' style log line and its indented sub-lines."""
    if _NO_COLOR:
        return text
    if text.lstrip().startswith("[") and "]" in text:
        head, _, rest = text.partition("]")
        try:
            n = int(head.strip()[1:].split("/")[0])
        except ValueError:
            n = 1
        col = _STAGE_COLORS[(n - 1) % len(_STAGE_COLORS)]
        return f"{col}{BOLD}{head}]{RESET}{TXT}{rest}{RESET}"
    # indented sub-step
    return f"{MUTED}{text}{RESET}"
