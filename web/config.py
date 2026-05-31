"""Web app configuration.

The same code runs in two topologies, selected entirely by environment:

  • Local / single host  — SQLite, local file storage, in-process generation.
  • Vercel split          — Postgres (DATABASE_URL), S3/Blob storage, and
                            generation delegated to a worker (WORKER_URL).

Nothing in the request path imports the heavy `mapgen` pipeline unless we are
actually generating in-process, so the Vercel function bundle stays small.
"""

from __future__ import annotations

import os
import secrets
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("WEB_DATA_DIR", str(HERE / "data")))
OUTPUTS_DIR = DATA_DIR / "outputs"
for _d in (DATA_DIR, OUTPUTS_DIR):
    try:
        _d.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass  # read-only FS (serverless); storage backend handles persistence


def _persistent_secret() -> str:
    env = os.environ.get("WEB_SECRET_KEY")
    if env:
        return env
    f = DATA_DIR / ".secret"
    try:
        if f.exists():
            return f.read_text().strip()
        s = secrets.token_urlsafe(48)
        f.write_text(s)
        os.chmod(f, 0o600)
        return s
    except OSError:
        # Ephemeral fallback (set WEB_SECRET_KEY in production!).
        return secrets.token_urlsafe(48)


def _db_url() -> str:
    raw = os.environ.get("DATABASE_URL") or os.environ.get("WEB_DB_URL")
    if not raw:
        return f"sqlite:///{(DATA_DIR / 'app.db').as_posix()}"
    # Normalise to the psycopg v3 driver SQLAlchemy expects.
    if raw.startswith("postgres://"):
        raw = "postgresql+psycopg://" + raw[len("postgres://"):]
    elif raw.startswith("postgresql://"):
        raw = "postgresql+psycopg://" + raw[len("postgresql://"):]
    return raw


class Settings:
    SECRET_KEY = _persistent_secret()
    DB_URL = _db_url()

    # cookies / sessions
    SESSION_COOKIE = "sid"
    CSRF_COOKIE = "csrf"
    SESSION_TTL_HOURS = 12
    COOKIE_SECURE = os.environ.get("WEB_COOKIE_SECURE", "0").lower() in ("1", "true", "yes")

    # quota
    FREE_GENERATIONS = int(os.environ.get("WEB_FREE_GENERATIONS", "2"))

    # auth policy
    PASSWORD_MIN_LEN = 10
    MAX_FAILED_LOGINS = 5
    LOCKOUT_MINUTES = 15

    # generation limits
    GEN_MAX_EXTENT_KM = 6.0
    GEN_DEFAULT_EXTENT_KM = 4.0
    GEN_RESOLUTION = int(os.environ.get("WEB_GEN_RESOLUTION", "80"))
    GEN_TIMEOUT_S = int(os.environ.get("WEB_GEN_TIMEOUT_S", "210"))
    GEN_CONCURRENCY = 2
    GEN_FORMATS = ("glb", "obj", "stl")
    PROMPT_MAX_LEN = 280
    PROMPT_MIN_LEN = 3

    # rate limits: (max_events, window_seconds)
    RL_LOGIN = (10, 300)
    RL_REGISTER = (6, 3600)
    RL_GENERATE = (30, 3600)

    # --- deployment topology ---
    # If set, /api/generate delegates to this worker instead of running locally.
    WORKER_URL = os.environ.get("WORKER_URL", "").rstrip("/") or None
    WORKER_SECRET = os.environ.get("WORKER_SECRET", SECRET_KEY)
    WORKER_TIMEOUT_S = int(os.environ.get("WORKER_TIMEOUT_S", "180"))

    # storage backend for generated files: "local" | "s3"
    STORAGE_BACKEND = os.environ.get("STORAGE_BACKEND", "local").lower()
    S3_BUCKET = os.environ.get("S3_BUCKET")
    S3_ENDPOINT = os.environ.get("S3_ENDPOINT")            # R2/Supabase/MinIO
    S3_REGION = os.environ.get("S3_REGION", "auto")
    S3_ACCESS_KEY = os.environ.get("S3_ACCESS_KEY_ID")
    S3_SECRET_KEY = os.environ.get("S3_SECRET_ACCESS_KEY")


settings = Settings()
