"""Runs the mapgen pipeline IN-PROCESS for local single-host mode, with resource
bounds so a request can't exhaust the server: capped extent/resolution, a hard
timeout, and a global concurrency semaphore. Output goes to a per-generation
UUID directory.

In the split (Vercel) topology this module is never invoked — generation runs
on the separate worker (see worker/app.py). The heavy ``mapgen`` import is kept
lazy (inside the worker thread) so importing the web app on Vercel does not pull
numpy/scipy/trimesh into the serverless bundle.
"""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

from .config import OUTPUTS_DIR, settings

_semaphore = asyncio.Semaphore(settings.GEN_CONCURRENCY)


def _build_config():
    from mapgen.config import Config  # lazy: heavy import only when generating locally

    cfg = Config.from_env()
    cfg.terrain_resolution = settings.GEN_RESOLUTION
    cfg.parser_backend = "auto"
    return cfg


def _run_sync(prompt: str, gen_id: str, extent_m: float) -> dict:
    from mapgen import Pipeline  # lazy: heavy import only when generating locally

    cfg = _build_config()
    pipe = Pipeline(config=cfg)
    overrides = {
        "extent_m": min(max(extent_m, 50.0), settings.GEN_MAX_EXTENT_M),
        "max_extent_m": settings.GEN_MAX_EXTENT_M,
    }
    out_dir = OUTPUTS_DIR / gen_id
    result = pipe.run(
        prompt, out_dir=out_dir, formats=list(settings.GEN_FORMATS),
        basename="scene", overrides=overrides,
    )
    files = {fmt: Path(p).name for fmt, p in result.files.items()}
    return {
        "id": gen_id,
        "files": files,
        "name": result.spec.name,
        "style": result.spec.world_style.value,
        "extent_m": result.spec.extent_m,
        "stats": result.build.stats,
        "features": result._feat(),
    }


async def run_generation(prompt: str, extent_m: float) -> dict:
    """Async wrapper: bounded concurrency + timeout around the blocking build."""
    gen_id = uuid.uuid4().hex
    async with _semaphore:
        loop = asyncio.get_running_loop()
        try:
            return await asyncio.wait_for(
                loop.run_in_executor(None, _run_sync, prompt, gen_id, extent_m),
                timeout=settings.GEN_TIMEOUT_S,
            )
        except asyncio.TimeoutError:
            raise TimeoutError(
                "Generation timed out. Try a smaller world."
            )
