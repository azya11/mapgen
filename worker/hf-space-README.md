---
title: Mapgen Worker
emoji: 🗺️
colorFrom: blue
colorTo: green
sdk: docker
app_port: 7860
pinned: false
---

# mapgen generation worker

The heavy half of the [mapgen](https://github.com/azya11/mapgen) free split
deployment. Runs the full 3D pipeline (numpy/scipy/trimesh/shapely) and serves
the resulting GLB/OBJ/STL files directly to the browser. The Vercel web app
authorizes each job with a ticket signed by a shared `WORKER_SECRET`.

This Space is built from the root `Dockerfile`. Set these in
**Settings → Variables and secrets**:

| Name | Kind | Value |
|------|------|-------|
| `WORKER_SECRET` | secret | must equal the Vercel app's `WORKER_SECRET` |
| `ALLOWED_ORIGINS` | variable | your Vercel origin, e.g. `https://your-app.vercel.app` |
| `ANTHROPIC_API_KEY` | secret | optional, enables the Claude parser |

Health check: `GET /health` → `{"ok":true,"configured":true}`.
