# mapgen generation worker

The heavy half of the free split deployment (see [`../DEPLOY.md`](../DEPLOY.md)).
Runs the full mapgen 3D pipeline and serves the resulting files directly to the
browser. The Vercel web app authorizes each job with a ticket signed by a shared
`WORKER_SECRET`.

## Endpoints
- `GET  /health` — liveness + whether `WORKER_SECRET` is configured.
- `POST /generate` — body `{ "ticket": "<signed>" }`; verifies the ticket, runs
  the pipeline, returns the result metadata (`id`, `files`, `location`, …).
- `GET  /files/{gen_id}/{name}` — serves `scene.{glb,obj,stl,mtl}` (the 128-bit
  `gen_id` is an unguessable capability).

## Run locally
```bash
pip install -r requirements-mapgen.txt -r worker/requirements.txt
WORKER_SECRET=dev-secret uvicorn worker.app:app --port 7860
```

## Build the image
```bash
docker build -f worker/Dockerfile -t mapgen-worker .   # context = repo root
docker run -e WORKER_SECRET=dev-secret -p 7860:7860 mapgen-worker
```

## Environment
| Var | Required | Default | Notes |
|-----|----------|---------|-------|
| `WORKER_SECRET` | ✅ | — | Must equal the Vercel app's `WORKER_SECRET`. |
| `ALLOWED_ORIGINS` | recommended | `*` | Comma-separated browser origins for CORS. |
| `ANTHROPIC_API_KEY` | optional | — | Enables the Claude parser. |
| `WORKER_OUTPUTS` | optional | `/tmp/mapgen-out` | Where generated files are written. |
| `WORKER_TIMEOUT_S` | optional | `210` | Hard per-job timeout. |
| `WORKER_MAX_EXTENT_KM` | optional | `6` | Caps the modeled area. |
| `WORKER_GEN_RESOLUTION` | optional | `80` | Terrain grid resolution. |
| `WORKER_CONCURRENCY` | optional | `2` | Concurrent generations. |

See [`../DEPLOY.md`](../DEPLOY.md) for host-by-host deploy steps (Render / Hugging
Face Spaces / Fly / Cloud Run).
