"""FastAPI application: pages, auth API, quota-enforced generation, and secure
file serving. See security.py for the cryptographic / header primitives."""

from __future__ import annotations

import datetime as dt
import os
import re
import uuid

from fastapi import Depends, FastAPI, Request, Response
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from sqlalchemy import select

from .config import HERE, OUTPUTS_DIR, settings
from .db import Generation, Session as DbSession, SessionLocal, User, init_db, utcnow
from .generate import run_generation
from .tickets import issue_ticket, read_ticket
from .security import (
    SecurityHeadersMiddleware,
    clean_prompt,
    client_ip,
    constant_time_eq,
    hash_password,
    hash_token,
    needs_rehash,
    new_token,
    normalize_email,
    rate_limiter,
    validate_password,
    verify_password,
)

templates = Jinja2Templates(directory=str(HERE / "templates"))
_FILENAME_RE = re.compile(r"^scene\.(glb|obj|stl|mtl)$")


# --------------------------------------------------------------------- app ---
def create_app() -> FastAPI:
    init_db()
    app = FastAPI(title="mapgen", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.trust_proxy = os.environ.get("WEB_TRUST_PROXY", "0").lower() in ("1", "true", "yes")
    app.add_middleware(SecurityHeadersMiddleware)
    app.mount("/static", StaticFiles(directory=str(HERE / "static")), name="static")

    _register_routes(app)
    return app


# ----------------------------------------------------------------- helpers ---
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _current(request: Request, db) -> tuple[DbSession | None, User | None]:
    token = request.cookies.get(settings.SESSION_COOKIE)
    if not token:
        return None, None
    row = db.scalar(select(DbSession).where(DbSession.token_hash == hash_token(token)))
    if not row:
        return None, None
    if row.expires_at.replace(tzinfo=dt.timezone.utc) < utcnow():
        db.delete(row)
        db.commit()
        return None, None
    return row, row.user


def _set_session_cookies(resp: Response, token: str, csrf: str) -> None:
    common = dict(secure=settings.COOKIE_SECURE, samesite="strict", path="/")
    resp.set_cookie(
        settings.SESSION_COOKIE, token, httponly=True,
        max_age=settings.SESSION_TTL_HOURS * 3600, **common,
    )
    # CSRF token is readable by JS (double-submit) but also bound to the session.
    resp.set_cookie(
        settings.CSRF_COOKIE, csrf, httponly=False,
        max_age=settings.SESSION_TTL_HOURS * 3600, **common,
    )


def _clear_session_cookies(resp: Response) -> None:
    resp.delete_cookie(settings.SESSION_COOKIE, path="/")
    resp.delete_cookie(settings.CSRF_COOKIE, path="/")


def _create_session(db, user: User) -> tuple[str, str]:
    token = new_token()
    csrf = new_token()
    db.add(DbSession(
        token_hash=hash_token(token), csrf_token=csrf, user_id=user.id,
        expires_at=utcnow().replace(tzinfo=None) + dt.timedelta(hours=settings.SESSION_TTL_HOURS),
    ))
    db.commit()
    return token, csrf


def _same_origin(request: Request) -> bool:
    """Reject cross-site POSTs (defense in depth alongside SameSite cookies)."""
    origin = request.headers.get("origin")
    if origin is None:
        ref = request.headers.get("referer")
        if ref is None:
            return True  # non-browser client (e.g. curl); cookies+CSRF still apply
        origin = ref
    host = request.headers.get("host", "")
    return origin.split("://")[-1].split("/")[0] == host


def _err(status: int, message: str) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=status)


# ------------------------------------------------------------------ models ---
class Credentials(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=200)


class GenerateBody(BaseModel):
    prompt: str = Field(min_length=1, max_length=400)
    extent_m: float = Field(default=settings.GEN_DEFAULT_EXTENT_M, ge=50.0, le=settings.GEN_MAX_EXTENT_M)


# ------------------------------------------------------------------ routes ---
def _register_routes(app: FastAPI) -> None:

    def page(request, name, **ctx):
        ctx["nonce"] = request.state.csp_nonce
        return templates.TemplateResponse(request, name, ctx)

    # ---- pages ----
    @app.get("/")
    def index(request: Request, db=Depends(get_db)):
        _, user = _current(request, db)
        return page(request, "index.html", user=user)

    @app.get("/login")
    def login_page(request: Request, db=Depends(get_db)):
        _, user = _current(request, db)
        if user:
            return RedirectResponse("/app", status_code=303)
        return page(request, "login.html", mode="login")

    @app.get("/register")
    def register_page(request: Request, db=Depends(get_db)):
        _, user = _current(request, db)
        if user:
            return RedirectResponse("/app", status_code=303)
        return page(request, "login.html", mode="register")

    @app.get("/app")
    def app_page(request: Request, db=Depends(get_db)):
        sess, user = _current(request, db)
        if not user:
            return RedirectResponse("/login", status_code=303)
        remaining = max(0, settings.FREE_GENERATIONS - user.generations_used)
        return page(request, "app.html", user=user, csrf=sess.csrf_token,
                    remaining=remaining, limit=settings.FREE_GENERATIONS)

    # ---- auth API ----
    @app.post("/api/register")
    async def api_register(request: Request, db=Depends(get_db)):
        if not _same_origin(request):
            return _err(403, "Cross-origin request blocked.")
        if not rate_limiter.check(f"reg:{client_ip(request)}", *settings.RL_REGISTER):
            return _err(429, "Too many attempts. Please wait and try again.")
        data = await _json(request)
        try:
            creds = Credentials(**data)
            email = normalize_email(creds.email)
        except Exception as e:
            return _err(400, _safe_msg(e, "Invalid input."))
        pw_err = validate_password(creds.password)
        if pw_err:
            return _err(400, pw_err)
        if db.scalar(select(User).where(User.email == email)):
            return _err(409, "An account with this email already exists.")
        user = User(email=email, password_hash=hash_password(creds.password))
        db.add(user)
        db.commit()
        token, csrf = _create_session(db, user)
        resp = JSONResponse({"ok": True, "email": email})
        _set_session_cookies(resp, token, csrf)
        return resp

    @app.post("/api/login")
    async def api_login(request: Request, db=Depends(get_db)):
        if not _same_origin(request):
            return _err(403, "Cross-origin request blocked.")
        if not rate_limiter.check(f"login:{client_ip(request)}", *settings.RL_LOGIN):
            return _err(429, "Too many attempts. Please wait and try again.")
        data = await _json(request)
        try:
            creds = Credentials(**data)
            email = normalize_email(creds.email)
        except Exception as e:
            return _err(400, _safe_msg(e, "Invalid input."))

        user = db.scalar(select(User).where(User.email == email))
        now = utcnow().replace(tzinfo=None)
        if user and user.locked_until and user.locked_until > now:
            return _err(423, "Account temporarily locked. Try again later.")

        ok = verify_password(user.password_hash if user else None, creds.password)
        if not ok or not user:
            if user:
                user.failed_logins += 1
                if user.failed_logins >= settings.MAX_FAILED_LOGINS:
                    user.locked_until = now + dt.timedelta(minutes=settings.LOCKOUT_MINUTES)
                    user.failed_logins = 0
                db.commit()
            return _err(401, "Invalid email or password.")

        # success
        user.failed_logins = 0
        user.locked_until = None
        if needs_rehash(user.password_hash):
            user.password_hash = hash_password(creds.password)
        db.commit()
        token, csrf = _create_session(db, user)
        resp = JSONResponse({"ok": True, "email": email})
        _set_session_cookies(resp, token, csrf)
        return resp

    @app.post("/api/logout")
    def api_logout(request: Request, db=Depends(get_db)):
        sess, _ = _current(request, db)
        if sess:
            db.delete(sess)
            db.commit()
        resp = JSONResponse({"ok": True})
        _clear_session_cookies(resp)
        return resp

    @app.get("/api/me")
    def api_me(request: Request, db=Depends(get_db)):
        _, user = _current(request, db)
        if not user:
            return _err(401, "Not authenticated.")
        return {
            "email": user.email,
            "used": user.generations_used,
            "limit": settings.FREE_GENERATIONS,
            "remaining": max(0, settings.FREE_GENERATIONS - user.generations_used),
        }

    @app.get("/api/history")
    def api_history(request: Request, db=Depends(get_db)):
        _, user = _current(request, db)
        if not user:
            return _err(401, "Not authenticated.")
        rows = db.scalars(
            select(Generation).where(
                Generation.user_id == user.id, Generation.pending == False  # noqa: E712
            ).order_by(Generation.created_at.desc()).limit(60)
        ).all()
        base = settings.WORKER_URL or ""  # files live on the worker in split mode
        return {"base": base, "items": [{
            "id": g.id,
            "prompt": g.prompt,
            "location": g.location,
            "used_real": g.used_real,
            "created_at": g.created_at.replace(tzinfo=dt.timezone.utc).isoformat(),
            "glb": f"{base}/files/{g.id}/scene.glb",
        } for g in rows]}

    # ---- generation ----
    @app.post("/api/generate")
    async def api_generate(request: Request, db=Depends(get_db)):
        sess, user = _current(request, db)
        if not user:
            return _err(401, "Not authenticated.")
        if not _same_origin(request):
            return _err(403, "Cross-origin request blocked.")
        if not _csrf_ok(request, sess):
            return _err(403, "Invalid CSRF token.")
        if not rate_limiter.check(f"gen:{client_ip(request)}", *settings.RL_GENERATE):
            return _err(429, "Too many requests. Please slow down.")

        data = await _json(request)
        try:
            body = GenerateBody(**data)
            prompt = clean_prompt(body.prompt)
        except Exception as e:
            return _err(400, _safe_msg(e, "Invalid input."))

        # --- reserve a quota slot atomically ---
        fresh = db.get(User, user.id)
        if fresh.generations_used >= settings.FREE_GENERATIONS:
            return _err(402, "You have used all your free generations.")
        gen_id = uuid.uuid4().hex
        fresh.generations_used += 1
        db.commit()

        # ---- split mode: hand the browser a signed ticket for the worker ----
        if settings.WORKER_URL:
            # Record a pending row so the slot is tracked; /confirm commits or
            # /confirm(ok=false) deletes it and refunds.
            db.add(Generation(
                id=gen_id, user_id=user.id, prompt=prompt, pending=True,
            ))
            db.commit()
            ticket = issue_ticket({
                "uid": user.id, "gid": gen_id, "prompt": prompt,
                "extent_m": body.extent_m,
            })
            fresh = db.get(User, user.id)
            return JSONResponse({
                "mode": "worker",
                "id": gen_id,
                "ticket": ticket,
                "worker_url": settings.WORKER_URL,
                "remaining": max(0, settings.FREE_GENERATIONS - fresh.generations_used),
                "used": fresh.generations_used,
                "limit": settings.FREE_GENERATIONS,
            })

        # ---- local mode: run the pipeline in-process ----
        try:
            result = await run_generation(prompt, body.extent_m)
        except Exception as e:
            # refund on failure
            fresh = db.get(User, user.id)
            fresh.generations_used = max(0, fresh.generations_used - 1)
            db.commit()
            msg = "Generation timed out." if isinstance(e, TimeoutError) else "Generation failed. Please try again."
            return _err(504 if isinstance(e, TimeoutError) else 500, msg)

        db.add(Generation(
            id=result["id"], user_id=user.id, prompt=prompt,
            location=str(result.get("name", ""))[:256],
            used_real=False, pending=False,
        ))
        db.commit()

        fresh = db.get(User, user.id)
        result["mode"] = "local"
        result["remaining"] = max(0, settings.FREE_GENERATIONS - fresh.generations_used)
        result["used"] = fresh.generations_used
        result["limit"] = settings.FREE_GENERATIONS
        return JSONResponse(result)

    @app.post("/api/generate/confirm")
    async def api_generate_confirm(request: Request, db=Depends(get_db)):
        """Worker-mode callback from the browser: commit the pending generation
        on success, or delete it and refund the reserved quota on failure."""
        sess, user = _current(request, db)
        if not user:
            return _err(401, "Not authenticated.")
        if not _same_origin(request):
            return _err(403, "Cross-origin request blocked.")
        if not _csrf_ok(request, sess):
            return _err(403, "Invalid CSRF token.")

        data = await _json(request)
        payload = read_ticket(data.get("ticket", ""), max_age=settings.WORKER_TIMEOUT_S + 600)
        if not payload or payload.get("uid") != user.id:
            return _err(400, "Invalid or expired ticket.")
        gen_id = str(payload.get("gid", ""))
        gen = db.get(Generation, gen_id)
        if not gen or gen.user_id != user.id:
            return _err(404, "Not found.")

        ok = bool(data.get("ok"))
        if gen.pending:  # idempotent: only act on a still-pending reservation
            if ok:
                meta = data.get("metadata") or {}
                gen.location = str(meta.get("name", ""))[:256]
                gen.used_real = False
                gen.pending = False
            else:
                db.delete(gen)
                fresh = db.get(User, user.id)
                fresh.generations_used = max(0, fresh.generations_used - 1)
            db.commit()

        fresh = db.get(User, user.id)
        return JSONResponse({
            "ok": ok,
            "remaining": max(0, settings.FREE_GENERATIONS - fresh.generations_used),
            "used": fresh.generations_used,
            "limit": settings.FREE_GENERATIONS,
        })

    # ---- secure file serving (owner-only, no path traversal) ----
    @app.get("/files/{gen_id}/{name}")
    def serve_file(gen_id: str, name: str, request: Request, db=Depends(get_db)):
        _, user = _current(request, db)
        if not user:
            return _err(401, "Not authenticated.")
        if not re.fullmatch(r"[0-9a-f]{32}", gen_id) or not _FILENAME_RE.match(name):
            return _err(404, "Not found.")
        gen = db.get(Generation, gen_id)
        if not gen or gen.user_id != user.id:
            return _err(404, "Not found.")
        path = (OUTPUTS_DIR / gen_id / name).resolve()
        if not str(path).startswith(str(OUTPUTS_DIR.resolve())) or not path.is_file():
            return _err(404, "Not found.")
        return FileResponse(path, headers={"Cache-Control": "private, max-age=3600"})

    @app.exception_handler(404)
    async def not_found(request: Request, exc):
        if request.url.path.startswith(("/api", "/files")):
            return _err(404, "Not found.")
        return page(request, "index.html", user=None)


# ------------------------------------------------------------- small utils ---
async def _json(request: Request) -> dict:
    try:
        data = await request.json()
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _csrf_ok(request: Request, sess: DbSession | None) -> bool:
    if sess is None:
        return False
    header = request.headers.get("x-csrf-token", "")
    return bool(header) and constant_time_eq(header, sess.csrf_token)


def _safe_msg(exc: Exception, fallback: str) -> str:
    # Only surface our own ValueError messages; never leak internals.
    return str(exc) if isinstance(exc, ValueError) else fallback


app = create_app()
