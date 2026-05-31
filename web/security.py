"""Security primitives: Argon2id password hashing, session/CSRF tokens, a
sliding-window rate limiter, input validation, and the security-headers /
Content-Security-Policy middleware.

Defense highlights:
- Argon2id hashing (memory-hard) with a constant-time dummy verify to prevent
  user-enumeration via login timing.
- 256-bit random session tokens stored hashed (SHA-256) in the DB.
- Per-route, per-IP sliding-window rate limiting.
- Strict CSP with per-response nonces; no 'unsafe-inline' for scripts.
"""

from __future__ import annotations

import hashlib
import re
import secrets
import threading
import time

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from email_validator import EmailNotValidError, validate_email
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from .config import settings

# ---------------------------------------------------------------- passwords ---
_ph = PasswordHasher()  # Argon2id defaults: sensible memory/time cost
# Pre-computed hash used to spend the same time when an account doesn't exist.
_DUMMY_HASH = _ph.hash("dummy-password-for-timing-equalization")


def hash_password(password: str) -> str:
    return _ph.hash(password)


def verify_password(stored_hash: str | None, password: str) -> bool:
    """Constant-ish time verify. When stored_hash is None (no such user) we
    still run a verify against a dummy hash so timing doesn't leak existence."""
    try:
        if stored_hash is None:
            _ph.verify(_DUMMY_HASH, password)
            return False
        return _ph.verify(stored_hash, password)
    except VerifyMismatchError:
        return False
    except Exception:
        return False


def needs_rehash(stored_hash: str) -> bool:
    try:
        return _ph.check_needs_rehash(stored_hash)
    except Exception:
        return False


# ------------------------------------------------------------------- tokens ---
def new_token() -> str:
    return secrets.token_urlsafe(32)  # 256 bits


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def constant_time_eq(a: str, b: str) -> bool:
    return secrets.compare_digest(a, b)


# --------------------------------------------------------------- validation ---
_PW_LETTER = re.compile(r"[A-Za-z]")
_PW_NUMBER = re.compile(r"\d")


def validate_password(pw: str) -> str | None:
    """Return an error message, or None if the password is acceptable."""
    if len(pw) < settings.PASSWORD_MIN_LEN:
        return f"Password must be at least {settings.PASSWORD_MIN_LEN} characters."
    if len(pw) > 200:
        return "Password is too long."
    if not _PW_LETTER.search(pw) or not _PW_NUMBER.search(pw):
        return "Password must contain both letters and numbers."
    return None


def normalize_email(email: str) -> str:
    """Validate + normalise; raises ValueError with a safe message on failure."""
    try:
        info = validate_email(email, check_deliverability=False)
        return info.normalized.lower()
    except EmailNotValidError:
        raise ValueError("Please enter a valid email address.")


def clean_prompt(prompt: str) -> str:
    prompt = (prompt or "").strip()
    # strip control chars
    prompt = "".join(ch for ch in prompt if ch == " " or ch.isprintable())
    if len(prompt) < settings.PROMPT_MIN_LEN:
        raise ValueError("Prompt is too short.")
    if len(prompt) > settings.PROMPT_MAX_LEN:
        raise ValueError(f"Prompt must be {settings.PROMPT_MAX_LEN} characters or fewer.")
    return prompt


# --------------------------------------------------------------- rate limit ---
class RateLimiter:
    """In-memory sliding-window limiter. Sufficient for a single-process app;
    swap for Redis if you scale horizontally."""

    def __init__(self) -> None:
        self._hits: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def check(self, key: str, limit: int, window_s: int) -> bool:
        now = time.time()
        with self._lock:
            buf = [t for t in self._hits.get(key, []) if now - t < window_s]
            if len(buf) >= limit:
                self._hits[key] = buf
                return False
            buf.append(now)
            self._hits[key] = buf
            return True


rate_limiter = RateLimiter()


def client_ip(request: Request) -> str:
    # Honour a single proxy hop if explicitly trusted via header; otherwise peer.
    xff = request.headers.get("x-forwarded-for")
    if xff and request.app.state.trust_proxy:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


# ---------------------------------------------------- security headers / CSP ---
class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Adds a per-response CSP nonce and a hardened set of security headers."""

    async def dispatch(self, request: Request, call_next):
        nonce = secrets.token_urlsafe(16)
        request.state.csp_nonce = nonce
        response = await call_next(request)

        csp = (
            "default-src 'none'; "
            "base-uri 'none'; "
            "form-action 'self'; "
            "frame-ancestors 'none'; "
            "img-src 'self' data:; "
            f"style-src 'self' 'nonce-{nonce}' https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com; "
            f"script-src 'self' 'nonce-{nonce}' https://unpkg.com; "
            "connect-src 'self' https://unpkg.com; "
            "worker-src 'self' blob:; "
            "object-src 'none'; "
            "manifest-src 'self'"
        )
        h = response.headers
        h["Content-Security-Policy"] = csp
        h["X-Content-Type-Options"] = "nosniff"
        h["X-Frame-Options"] = "DENY"
        h["Referrer-Policy"] = "strict-origin-when-cross-origin"
        h["Permissions-Policy"] = "geolocation=(), microphone=(), camera=(), payment=()"
        h["Cross-Origin-Opener-Policy"] = "same-origin"
        h["Cross-Origin-Resource-Policy"] = "same-origin"
        if settings.COOKIE_SECURE:
            h["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        if "server" in h:
            del h["server"]
        return response
