"""Password hashing, signed httpOnly sessions, CSRF, and login/signup rate limits."""

from __future__ import annotations

import base64
import hashlib
import hmac
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


# --- Operator console login (separate cookie from Traction /app sessions) ---
CONSOLE_COOKIE_NAME = "seo_console_session"
CONSOLE_REMEMBER_MAX_AGE = 60 * 60 * 24 * 30  # 30 days
CONSOLE_SESSION_MAX_AGE = 60 * 60 * 12  # 12 hours server-side
CONSOLE_RATE_LIMIT_ATTEMPTS = 5
CONSOLE_RATE_LIMIT_WINDOW = 15 * 60
PBKDF2_SCHEME = "pbkdf2_sha256"
PBKDF2_ITERATIONS = 600_000
CONSOLE_SALT = "seo-console-session"


def console_username() -> str:
    return (os.environ.get("CONSOLE_USERNAME") or "michael").strip() or "michael"


def console_password_hash() -> str:
    return (os.environ.get("CONSOLE_PASSWORD_HASH") or "").strip()


def console_login_configured() -> bool:
    return bool(console_password_hash())


def _console_serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(session_secret(), salt=CONSOLE_SALT)


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64decode(value: str) -> bytes:
    pad = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + pad)


def hash_console_password(password: str, *, iterations: int = PBKDF2_ITERATIONS) -> str:
    if not password:
        raise ValueError("Password is required.")
    if iterations < 1:
        raise ValueError("Iterations must be positive.")
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"{PBKDF2_SCHEME}${iterations}${_b64encode(salt)}${_b64encode(digest)}"


def verify_password_hash(password: str, password_hash: str) -> bool:
    if not password or not password_hash:
        return False
    stored = password_hash.strip()
    if stored.startswith(("$2a$", "$2b$", "$2y$")):
        return verify_password(password, stored)
    if stored.startswith(f"{PBKDF2_SCHEME}$") or stored.startswith("$pbkdf2-sha256$"):
        try:
            if stored.startswith("$pbkdf2-sha256$"):
                _prefix, iterations_s, salt_s, digest_s = stored[1:].split("$", 3)
            else:
                _scheme, iterations_s, salt_s, digest_s = stored.split("$", 3)
            iterations = int(iterations_s)
            salt = _b64decode(salt_s)
            expected = _b64decode(digest_s)
            actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
            return hmac.compare_digest(actual, expected)
        except (ValueError, TypeError, AttributeError):
            return False
    return False


def verify_console_credentials(username: str, password: str) -> bool:
    stored = console_password_hash()
    if not stored:
        return False
    user_ok = secrets.compare_digest((username or "").strip(), console_username())
    pass_ok = verify_password_hash(password or "", stored)
    return user_ok and pass_ok


def console_login_allowed(ip: str) -> bool:
    key = f"console_login:{ip}"
    now = time.time()
    hits = [t for t in _rate_hits.get(key, []) if now - t < CONSOLE_RATE_LIMIT_WINDOW]
    _rate_hits[key] = hits
    return len(hits) < CONSOLE_RATE_LIMIT_ATTEMPTS


def record_console_login_failure(ip: str) -> None:
    key = f"console_login:{ip}"
    now = time.time()
    hits = [t for t in _rate_hits.get(key, []) if now - t < CONSOLE_RATE_LIMIT_WINDOW]
    hits.append(now)
    _rate_hits[key] = hits


def _cookie_secure(request: Request) -> bool:
    if request.url.scheme == "https":
        return True
    proto = (request.headers.get("x-forwarded-proto") or "").split(",")[0].strip().lower()
    return proto == "https"


def get_console_session(request: Request) -> Dict[str, Any]:
    raw = request.cookies.get(CONSOLE_COOKIE_NAME)
    if not raw:
        return {}
    try:
        data = _console_serializer().loads(raw, max_age=CONSOLE_REMEMBER_MAX_AGE)
        if not isinstance(data, dict):
            return {}
        issued = float(data.get("iat") or 0)
        remember = bool(data.get("remember"))
        limit = CONSOLE_REMEMBER_MAX_AGE if remember else CONSOLE_SESSION_MAX_AGE
        if issued <= 0 or (time.time() - issued) > limit:
            return {}
        return data
    except (BadSignature, SignatureExpired, TypeError, ValueError):
        return {}


def set_console_session(
    response: Response,
    request: Request,
    data: Dict[str, Any],
    *,
    remember: bool,
) -> None:
    payload = dict(data)
    payload["remember"] = bool(remember)
    payload.setdefault("iat", int(time.time()))
    token = _console_serializer().dumps(payload)
    kwargs: Dict[str, Any] = {
        "key": CONSOLE_COOKIE_NAME,
        "value": token,
        "httponly": True,
        "samesite": "lax",
        "secure": _cookie_secure(request),
        "path": "/",
    }
    if remember:
        kwargs["max_age"] = CONSOLE_REMEMBER_MAX_AGE
    response.set_cookie(**kwargs)


def clear_console_session(response: Response) -> None:
    response.delete_cookie(CONSOLE_COOKIE_NAME, path="/")


def ensure_console_csrf(request: Request, response: Response) -> str:
    session = get_console_session(request)
    token = session.get("csrf")
    if not token:
        token = secrets.token_urlsafe(32)
        session["csrf"] = token
        # Pre-auth CSRF cookie is a short-lived browser session with a 12h server cap.
        if "iat" not in session:
            session["iat"] = int(time.time())
        set_console_session(response, request, session, remember=False)
    return str(token)


def require_console_csrf(request: Request, form_token: Optional[str] = None) -> None:
    session = get_console_session(request)
    expected = str(session.get("csrf") or "")
    provided = (form_token or "").strip()
    if not provided:
        provided = (request.headers.get("x-csrf-token") or "").strip()
    if not expected or not provided or not secrets.compare_digest(expected, provided):
        raise HTTPException(status_code=403, detail="Invalid or missing CSRF token.")


def current_console_user(request: Request) -> Optional[str]:
    session = get_console_session(request)
    user = session.get("console_user")
    if not user:
        return None
    return str(user)


def control_token_expected() -> str:
    return (os.environ.get("CONTROL_TOKEN") or "").strip()


def provided_control_token(request: Request) -> str:
    token = (request.headers.get("x-control-token") or "").strip()
    if token:
        return token
    authorization = request.headers.get("authorization") or ""
    if authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return ""


def control_token_is_valid(request: Request) -> bool:
    expected = control_token_expected()
    token = provided_control_token(request)
    if not expected or not token:
        return False
    return hmac.compare_digest(token, expected)
