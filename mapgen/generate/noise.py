"""Lightweight value-noise + fractal Brownian motion on a grid, implemented in
pure numpy so the package needs no native noise dependency. Deterministic for a
given seed."""

from __future__ import annotations

import numpy as np


def _smootherstep(t: np.ndarray) -> np.ndarray:
    return t * t * t * (t * (t * 6 - 15) + 10)


def value_noise(res: int, cells: int, seed: int) -> np.ndarray:
    """A res x res field of value noise with `cells` lattice cells per side,
    bilinearly interpolated with a smootherstep fade. Range ~[0,1]."""
    rng = np.random.default_rng(seed)
    lattice = rng.random((cells + 1, cells + 1))

    xs = np.linspace(0, cells, res, endpoint=False)
    ys = np.linspace(0, cells, res, endpoint=False)
    gx, gy = np.meshgrid(xs, ys, indexing="ij")

    x0 = np.floor(gx).astype(int)
    y0 = np.floor(gy).astype(int)
    x1 = np.minimum(x0 + 1, cells)
    y1 = np.minimum(y0 + 1, cells)

    fx = _smootherstep(gx - x0)
    fy = _smootherstep(gy - y0)

    v00 = lattice[x0, y0]
    v10 = lattice[x1, y0]
    v01 = lattice[x0, y1]
    v11 = lattice[x1, y1]

    top = v00 * (1 - fx) + v10 * fx
    bot = v01 * (1 - fx) + v11 * fx
    return top * (1 - fy) + bot * fy


def fbm(res: int, seed: int, octaves: int = 5, base_cells: int = 4,
        lacunarity: float = 2.0, gain: float = 0.5) -> np.ndarray:
    """Fractal Brownian motion. Returns a res x res array normalised to [0,1]."""
    field = np.zeros((res, res), dtype=float)
    amp = 1.0
    cells = base_cells
    total = 0.0
    for o in range(octaves):
        field += amp * value_noise(res, max(1, int(cells)), seed + o * 1013)
        total += amp
        amp *= gain
        cells *= lacunarity
    field /= total
    field -= field.min()
    rng = field.max() - field.min()
    if rng > 1e-9:
        field /= rng
    return field


def radial_falloff(res: int, power: float = 2.0) -> np.ndarray:
    """1 at centre -> 0 at edges, for island/basin shaping."""
    lin = np.linspace(-1, 1, res)
    gx, gy = np.meshgrid(lin, lin, indexing="ij")
    d = np.sqrt(gx**2 + gy**2) / np.sqrt(2)
    return np.clip(1.0 - d**power, 0.0, 1.0)


def directional_ramp(res: int, direction: str | None) -> np.ndarray:
    """A 0..1 field that is high toward the given compass direction, used to
    bias procedural features (e.g. mountains to the north). x=east, y=north."""
    lin = np.linspace(-1, 1, res)
    gx, gy = np.meshgrid(lin, lin, indexing="ij")  # gx east, gy north
    table = {
        "north": gy, "south": -gy, "east": gx, "west": -gx,
        "northeast": (gx + gy), "northwest": (-gx + gy),
        "southeast": (gx - gy), "southwest": (-gx - gy),
        "center": 1.0 - np.sqrt(gx**2 + gy**2),
    }
    field = table.get(direction or "", np.zeros((res, res)))
    field = np.asarray(field, dtype=float)
    field -= field.min()
    if field.max() > 1e-9:
        field /= field.max()
    return field
