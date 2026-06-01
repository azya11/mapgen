"""Signed generation tickets.

In the split (Vercel) topology the browser cannot run generation on Vercel
(bundle/time limits), so it calls the worker directly. To authorize that
cross-origin call without exposing generation to the world, Vercel issues a
short-lived ticket signed with WORKER_SECRET. The worker verifies the same
signature before doing any work, and Vercel re-reads the ticket on /confirm to
bind the result back to the reserving user.

The worker carries an independent copy of this verify logic (worker/app.py);
both sides MUST share the same WORKER_SECRET and salt.
"""

from __future__ import annotations

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from .config import settings

_SALT = "mapgen-gen-ticket"
_serializer = URLSafeTimedSerializer(settings.WORKER_SECRET, salt=_SALT)


def issue_ticket(payload: dict) -> str:
    return _serializer.dumps(payload)


def read_ticket(token: str, max_age: int) -> dict | None:
    """Return the payload, or None if the signature is bad/expired/malformed."""
    if not token:
        return None
    try:
        data = _serializer.loads(token, max_age=max_age)
        return data if isinstance(data, dict) else None
    except (BadSignature, SignatureExpired, Exception):
        return None
