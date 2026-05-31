#!/usr/bin/env python
"""Convenience launcher for the mapgen web app.

    python run_web.py                 # http://127.0.0.1:8000
    python run_web.py --port 8800
    HOST=0.0.0.0 python run_web.py    # expose on LAN (use behind HTTPS!)

For production, run behind a TLS-terminating reverse proxy (Caddy / nginx) and
set environment variables:
    WEB_SECRET_KEY=<random 48+ chars>
    WEB_COOKIE_SECURE=1          # send cookies only over HTTPS, enable HSTS
    WEB_TRUST_PROXY=1            # honour X-Forwarded-For from your proxy
    ANTHROPIC_API_KEY=...        # optional: use the Claude parser
"""

from __future__ import annotations

import argparse
import os

import uvicorn


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default=os.environ.get("HOST", "127.0.0.1"))
    ap.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8000")))
    ap.add_argument("--reload", action="store_true", help="auto-reload (dev only)")
    args = ap.parse_args()

    uvicorn.run(
        "web.app:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="info",
    )


if __name__ == "__main__":
    main()
