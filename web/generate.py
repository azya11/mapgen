"""Runs the mapgen pipeline for the web, with resource bounds so a request can't
exhaust the server: capped extent/resolution, a hard timeout, and a global
concurrency semaphore. Output goes to a per-generation UUID directory."""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

from mapgen import Pipeline
from mapgen.config import Config

from .config import OUTPUTS_DIR, settings

_semaphore = asyncio.Semaphore(settings.GEN_CONCURRENCY)


def _build_config(use_network: bool) -> Config:
    cfg = Config.from_env()
    cfg.terrain_resolution = settings.GEN_RESOLUTION
    cfg.use_network = use_network
    # Parser: Claude if a server-side key exists, else the offline rule parser.
    cfg.parser_backend = "auto"
    return cfg


def _run_sync(prompt: str, gen_id: str, use_real: bool, extent_km: float) -> dict:
    cfg = _build_config(use_network=use_real)
    pipe = Pipeline(config=cfg)
    overrides = {
        "extent_km": min(max(extent_km, 0.5), settings.GEN_MAX_EXTENT_KM),
        # If the user did not ask for real data, force procedural generation.
        "force_real": None if use_real else False,
    }
    out_dir = OUTPUTS_DIR / gen_id
    result = pipe.run(
        prompt,
        out_dir=out_dir,
        formats=list(settings.GEN_FORMATS),
        basename="scene",
        overrides=overrides,
    )
    files = {fmt: Path(p).name for fmt, p in result.files.items()}
    return {
        "id": gen_id,
        "files": files,
        "location": result.spec.location,
        "is_real": result.spec.is_real_location,
        "used_real_data": result.build.used_real_data,
        "style": result.spec.map_style.value,
        "extent_km": result.spec.extent_km,
        "stats": result.build.stats,
        "features": result._feat(),
    }


async def run_generation(prompt: str, use_real: bool, extent_km: float) -> dict:
    """Async wrapper: bounded concurrency + timeout around the blocking build."""
    gen_id = uuid.uuid4().hex
    async with _semaphore:
        loop = asyncio.get_running_loop()
        try:
            return await asyncio.wait_for(
                loop.run_in_executor(None, _run_sync, prompt, gen_id, use_real, extent_km),
                timeout=settings.GEN_TIMEOUT_S,
            )
        except asyncio.TimeoutError:
            raise TimeoutError(
                "Generation timed out. Try a smaller area or procedural mode."
            )
