"""Vercel serverless entrypoint — exposes the FastAPI ASGI app.

Vercel's Python runtime serves the module-level ``app``. All routes are
rewritten to this function via vercel.json. Generation is delegated to the
worker (set WORKER_URL), so this function never imports the heavy mapgen
pipeline and stays within Vercel's serverless bundle limit.

Required Vercel env vars (Settings -> Environment Variables):
  DATABASE_URL       external Postgres, e.g. Neon (SQLite does NOT persist here)
  WEB_SECRET_KEY     fixed random 48+ char string (stable session signing)
  WORKER_URL         https URL of the deployed worker (see worker/README.md)
  WORKER_SECRET      MUST equal the worker's WORKER_SECRET (signs gen tickets)
  WEB_COOKIE_SECURE  1
  WEB_TRUST_PROXY    1
  WEB_DATA_DIR       /tmp        (only writable path; used for the secret fallback)
"""

from __future__ import annotations

from web.app import app  # noqa: F401  (Vercel discovers `app`)
