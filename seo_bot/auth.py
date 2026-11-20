"""Password hashing, signed httpOnly sessions, CSRF, and login/signup rate limits."""

from __future__ import annotations

import os
import re
import secrets
import time
from typing import Any, Dict, Optional

import bcrypt
from fastapi import HTTPException, Request, Response
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

COOKIE_NAME = "seo_session"
COOKIE_MAX_AGE = 60 * 60 * 24 * 14
RATE_LIMIT_ATTEMPTS = 8
RATE_LIMIT_WINDOW = 15 * 60
EMAIL_RE = re.compile(r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$")
MIN_PASSWORD_LEN = 8

_process_secret = secrets.token_urlsafe(32)
_rate_hits: dict[str, list[float]] = {}


def session_secret() -> str:
    env = (os.environ.get("SESSION_SECRET") or "").strip()
    return env or _process_secret


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(session_secret(), salt="seo-app-session")


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("ascii")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("ascii"))
    except (ValueError, TypeError):
        return False


def normalize_email(email: str) -> str:
    return (email or "").strip().lower()


def validate_credentials(email: str, password: str) -> str:
    email = normalize_email(email)
    if not email or not EMAIL_RE.match(email) or len(email) > 254:
        raise ValueError("Enter a valid email address.")
    if not password or len(password) < MIN_PASSWORD_LEN:
        raise ValueError(f"Password must be at least {MIN_PASSWORD_LEN} characters.")
    if len(password) > 128:
        raise ValueError("Password is too long.")
    return email


def client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip() or (request.client.host if request.client else "unknown")
    return request.client.host if request.client else "unknown"


def rate_limit_ok(bucket: str, ip: str) -> bool:
    key = f"{bucket}:{ip}"
    now = time.time()
    hits = [t for t in _rate_hits.get(key, []) if now - t < RATE_LIMIT_WINDOW]
    if len(hits) >= RATE_LIMIT_ATTEMPTS:
        _rate_hits[key] = hits
        return False
    hits.append(now)
    _rate_hits[key] = hits
    return True


def reset_rate_limit_for_tests() -> None:
    _rate_hits.clear()


def get_session(request: Request) -> Dict[str, Any]:
    raw = request.cookies.get(COOKIE_NAME)
    if not raw:
        return {}
    try:
        data = _serializer().loads(raw, max_age=COOKIE_MAX_AGE)
        return data if isinstance(data, dict) else {}
    except (BadSignature, SignatureExpired, TypeError):
        return {}


def set_session(response: Response, request: Request, data: Dict[str, Any]) -> None:
    token = _serializer().dumps(data)
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        max_age=COOKIE_MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=request.url.scheme == "https",
        path="/",
    )


def clear_session(response: Response) -> None:
    response.delete_cookie(COOKIE_NAME, path="/")


def ensure_csrf(request: Request, response: Optional[Response] = None) -> str:
    session = get_session(request)
    token = session.get("csrf")
    if not token:
        token = secrets.token_urlsafe(32)
        session["csrf"] = token
        if response is not None:
            set_session(response, request, session)
        else:
            # Stash so a later set_session can persist it on this request cycle.
            request.state.session_updates = session
    return token


def persist_session(response: Response, request: Request, **updates: Any) -> Dict[str, Any]:
    session = get_session(request)
    extra = getattr(request.state, "session_updates", None)
    if isinstance(extra, dict):
        session.update(extra)
    session.update(updates)
    if "csrf" not in session:
        session["csrf"] = secrets.token_urlsafe(32)
    set_session(response, request, session)
    return session


def require_csrf(request: Request, form_token: Optional[str] = None) -> None:
    session = get_session(request)
    expected = session.get("csrf") or ""
    provided = (form_token or "").strip()
    if not provided:
        provided = (request.headers.get("x-csrf-token") or "").strip()
    if not expected or not provided or not secrets.compare_digest(str(expected), provided):
        raise HTTPException(status_code=403, detail="Invalid or missing CSRF token.")


def current_user_id(request: Request) -> Optional[int]:
    uid = get_session(request).get("uid")
    try:
        return int(uid) if uid is not None else None
    except (TypeError, ValueError):
        return None
