"""Generation worker — the heavy half of the split deployment.

Runs the full mapgen 3D pipeline (numpy/scipy/trimesh/shapely) which is far too
large and slow for Vercel's serverless functions. The Vercel app issues a
short-lived ticket signed with WORKER_SECRET; this worker verifies it before
doing any work, then serves the resulting GLB/OBJ/STL files directly to the
browser (so the large binaries never pass through Vercel's 4.5 MB limit).

Deploy on any always-on host with a real CPU: Hugging Face Spaces (Docker),
Render, Fly.io, Google Cloud Run, etc. See worker/README.md.

Required env:
  WORKER_SECRET     MUST equal the value set on the Vercel app (signs tickets).
Optional env:
  ALLOWED_ORIGINS   comma-separated browser origins for CORS (default "*").
  WORKER_OUTPUTS    output dir (default /tmp/mapgen-out).
  WORKER_TIMEOUT_S  hard per-job timeout (default 210).
  WORKER_GEN_RESOLUTION, WORKER_MAX_EXTENT_KM, WORKER_CONCURRENCY
  ANTHROPIC_API_KEY optional, enables the Claude parser.
"""

from __future__ import annotations

import asyncio
import os
import re
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

# ------------------------------------------------------------------ config ---
SECRET = os.environ.get("WORKER_SECRET", "")
ALLOWED_ORIGINS = [o.strip() for o in os.environ.get("ALLOWED_ORIGINS", "*").split(",") if o.strip()]
OUTPUTS = Path(os.environ.get("WORKER_OUTPUTS", "/tmp/mapgen-out"))
OUTPUTS.mkdir(parents=True, exist_ok=True)
TIMEOUT_S = int(os.environ.get("WORKER_TIMEOUT_S", "210"))
GEN_RESOLUTION = int(os.environ.get("WORKER_GEN_RESOLUTION", "80"))
MAX_EXTENT_KM = float(os.environ.get("WORKER_MAX_EXTENT_KM", "6"))
CONCURRENCY = int(os.environ.get("WORKER_CONCURRENCY", "2"))
FORMATS = ("glb", "obj", "stl")

_SALT = "mapgen-gen-ticket"  # MUST match web/tickets.py
_serializer = URLSafeTimedSerializer(SECRET, salt=_SALT)
_semaphore = asyncio.Semaphore(CONCURRENCY)

_FILENAME_RE = re.compile(r"^scene\.(glb|obj|stl|mtl)$")
_GENID_RE = re.compile(r"^[0-9a-f]{32}$")

app = FastAPI(title="mapgen-worker", docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS or ["*"],
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type"],
)


# ------------------------------------------------------------- generation ---
def _run_sync(prompt: str, gen_id: str, use_real: bool, extent_km: float) -> dict:
    from mapgen import Pipeline
    from mapgen.config import Config

    cfg = Config.from_env()
    cfg.terrain_resolution = GEN_RESOLUTION
    cfg.use_network = use_real
    cfg.parser_backend = "auto"  # Claude if ANTHROPIC_API_KEY is set, else rule

    pipe = Pipeline(config=cfg)
    overrides = {
        "extent_km": min(max(extent_km, 0.5), MAX_EXTENT_KM),
        # A "1:N" scale ratio in the prompt may override extent_km; cap it here.
        "max_extent_km": MAX_EXTENT_KM,
        "force_real": None if use_real else False,
    }
    result = pipe.run(
        prompt, out_dir=OUTPUTS / gen_id, formats=list(FORMATS),
        basename="scene", overrides=overrides,
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


# ----------------------------------------------------------------- routes ---
@app.get("/health")
def health():
    return {"ok": True, "configured": bool(SECRET)}


@app.post("/generate")
async def generate(request: Request):
    if not SECRET:
        return JSONResponse({"error": "Worker not configured."}, status_code=500)
    try:
        body = await request.json()
    except Exception:
        body = {}
    ticket = (body or {}).get("ticket", "")
    try:
        data = _serializer.loads(ticket, max_age=TIMEOUT_S + 120)
    except (BadSignature, SignatureExpired, Exception):
        return JSONResponse({"error": "Invalid or expired ticket."}, status_code=403)
    if not isinstance(data, dict) or not _GENID_RE.match(str(data.get("gid", ""))):
        return JSONResponse({"error": "Invalid ticket."}, status_code=403)

    gen_id = data["gid"]
    prompt = str(data.get("prompt", ""))[:400]
    use_real = bool(data.get("use_real", True))
    extent_km = float(data.get("extent_km", 4.0))

    async with _semaphore:
        loop = asyncio.get_running_loop()
        try:
            result = await asyncio.wait_for(
                loop.run_in_executor(None, _run_sync, prompt, gen_id, use_real, extent_km),
                timeout=TIMEOUT_S,
            )
        except asyncio.TimeoutError:
            return JSONResponse({"error": "Generation timed out. Try a smaller area."}, status_code=504)
        except Exception:
            return JSONResponse({"error": "Generation failed. Please try again."}, status_code=500)
    return JSONResponse(result)


@app.get("/files/{gen_id}/{name}")
def serve_file(gen_id: str, name: str):
    # The 128-bit gen_id acts as an unguessable capability for the file.
    if not _GENID_RE.match(gen_id) or not _FILENAME_RE.match(name):
        return JSONResponse({"error": "Not found."}, status_code=404)
    path = (OUTPUTS / gen_id / name).resolve()
    if not str(path).startswith(str(OUTPUTS.resolve())) or not path.is_file():
        return JSONResponse({"error": "Not found."}, status_code=404)
    return FileResponse(
        path,
        headers={
            "Content-Disposition": f'attachment; filename="{name}"',
            "Cache-Control": "private, max-age=3600",
        },
    )
