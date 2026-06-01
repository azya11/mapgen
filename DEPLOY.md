# Deploying for free: Vercel (web) + a free worker (generation)

The 3D generation pipeline (numpy/scipy/trimesh/shapely) is far too large and
slow for Vercel's serverless functions (250 MB bundle, 60 s, 4.5 MB response
limits). So the app is split:

```
        ┌─────────────────────────┐         ┌──────────────────────────────┐
Browser │  Vercel (free)          │         │  Worker (free, always-on)    │
  │     │  • pages / login        │         │  • runs the mapgen pipeline  │
  │     │  • quota + history      │         │  • serves GLB/OBJ/STL files  │
  │     │  • Postgres (Neon)      │         └──────────────────────────────┘
  │     └─────────────────────────┘                      ▲
  │ 1. POST /api/generate  ───────────▶ signed ticket    │
  │ 2. POST {worker}/generate (ticket) ──────────────────┘  (long job, direct)
  │ 3. load GLB direct from worker ──────────────────────┘
  └ 4. POST /api/generate/confirm ────▶ commits / refunds quota
```

The browser talks to the worker **directly** for the long generation call and
for downloads, so neither Vercel limit is ever hit. A short-lived ticket signed
with a shared secret authorizes that cross-origin call.

---

## 1. Database — Neon Postgres (free)

Vercel's filesystem is read-only/ephemeral, so SQLite won't persist. Use a free
Postgres:

1. Create a free project at https://neon.tech (or Supabase).
2. Copy the **pooled** connection string, e.g.
   `postgresql://user:pass@ep-xxx-pooler.region.aws.neon.tech/dbname?sslmode=require`

You'll set this as `DATABASE_URL` on Vercel. The app auto-creates its tables on
first boot.

## 2. Deploy the worker (free, always-on)

The worker is a small Docker service (`worker/Dockerfile`). Recommended free host:

### Render (Docker, deploys straight from this repo)
1. https://render.com → **New → Web Service** → connect this GitHub repo.
2. **Runtime:** Docker · **Dockerfile Path:** `worker/Dockerfile` · **Docker Build Context:** `.` (repo root).
3. **Instance Type:** Free.
4. **Environment** variables:
   - `WORKER_SECRET` — a long random string (you'll reuse it on Vercel).
   - `ALLOWED_ORIGINS` — your Vercel URL, e.g. `https://your-app.vercel.app`
     (you can set this after step 3 once you know the URL; `*` works to start).
   - `ANTHROPIC_API_KEY` — optional (Claude parser).
5. Deploy. Note the URL, e.g. `https://mapgen-worker.onrender.com`. Check
   `https://…/health` returns `{"ok":true,"configured":true}`.

> **Heads-up (Render free):** spins down after 15 min idle (first request after
> is slow), and 512 MB RAM may OOM on large real-city builds — keep the extent
> small. For more memory free, use **Hugging Face Spaces** (Docker SDK, ~16 GB
> RAM): create a Docker Space, add this repo's files with `worker/Dockerfile`
> contents as the Space's root `Dockerfile`, and set the same env vars
> (`app_port: 7860`). Fly.io and Google Cloud Run also have free allowances.

## 3. Deploy the web app on Vercel (free)

1. https://vercel.com → **Add New → Project** → import this GitHub repo.
2. Framework preset: **Other** (the included `vercel.json` + `api/index.py`
   handle routing). Leave build/output settings default.
3. **Environment Variables:**

   | Key | Value |
   |-----|-------|
   | `DATABASE_URL` | your Neon pooled connection string |
   | `WEB_SECRET_KEY` | a fixed random 48+ char string |
   | `WORKER_URL` | your worker URL (no trailing slash) |
   | `WORKER_SECRET` | **same** value as on the worker |
   | `WEB_COOKIE_SECURE` | `1` |
   | `WEB_TRUST_PROXY` | `1` |
   | `WEB_DATA_DIR` | `/tmp` |

4. Deploy. Open the URL, register, and generate.
5. Go back to the worker and set `ALLOWED_ORIGINS` to your exact Vercel URL
   (tightens CORS), then redeploy the worker.

`WORKER_SECRET` **must be identical** on both sides — it signs and verifies the
generation tickets.

---

## Known free-tier limitations (by design)

- **Generated files are ephemeral.** The worker stores GLB/OBJ/STL on its local
  disk; when the free worker restarts/sleeps they're cleared, so old "My maps"
  entries may fail to load (the account/history rows persist in Postgres). For
  durable files, add object storage (S3/R2) to the worker.
- **File access is by unguessable URL**, not session-checked, since the worker
  is a separate origin. The 128-bit generation id acts as a capability.
- **Rate limiting is per-instance/in-memory**, so it's weak on serverless;
  account lockout (DB-backed) still works. Add Redis if you need real limits.
- **First worker request may be slow** if the free host spun down.

## Local development (unchanged)

With `WORKER_URL` unset the app runs everything in-process on SQLite:

```powershell
pip install -r requirements.txt -r requirements-mapgen.txt
python run_web.py        # http://127.0.0.1:8000
```
