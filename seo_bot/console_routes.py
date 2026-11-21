"""Operator console login, logout, and authentication gate."""

from __future__ import annotations

from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from fastapi import APIRouter, Form, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from seo_bot.auth import (
    clear_console_session,
    client_ip,
    console_login_allowed,
    console_login_configured,
    console_username,
    current_console_user,
    ensure_console_csrf,
    record_console_login_failure,
    require_console_csrf,
    set_console_session,
    verify_console_credentials,
)
from seo_bot.site_seo import public_origin

TEMPLATES: Optional[Jinja2Templates] = None


def safe_next_url(value: Optional[str]) -> str:
    raw = (value or "").strip() or "/"
    parsed = urlparse(raw)
    if parsed.scheme or parsed.netloc:
        return "/"
    if not raw.startswith("/") or raw.startswith("//"):
        return "/"
    if raw.startswith("/login"):
        return "/"
    return raw



def login_response(request: Request, *, error, username, next_url, remember_checked, status_code=200):
    configured = console_login_configured()
    # Issue/refresh the CSRF cookie on a placeholder, then render with the token.
    placeholder = Response()
    csrf = ensure_console_csrf(request, placeholder)
    html = TEMPLATES.TemplateResponse(
        request,
        "console_login.html",
        {
            "csrf_token": csrf,
            "configured": configured,
            "error": error,
            "username": username,
            "next_url": next_url,
            "origin": public_origin(),
            "remember_checked": remember_checked,
        },
        status_code=status_code,
    )
    html.headers["X-Robots-Tag"] = "noindex, nofollow"
    cookie = placeholder.headers.get("set-cookie")
    if cookie:
        html.headers.append("set-cookie", cookie)
    return html


def is_public_path(path: str) -> bool:
    if path in {"/healthz", "/robots.txt", "/sitemap.xml", "/login", "/logout"}:
        return True
    if path == "/app" or path.startswith("/app/"):
        return True
    if path == "/api/app" or path.startswith("/api/app/"):
        return True
    if path.startswith("/static/"):
        name = path.rsplit("/", 1)[-1]
        return name != "index.html"
    return False


def wants_json(request: Request) -> bool:
    path = request.url.path
    if path.startswith("/api/") or path in {"/openapi.json"}:
        return True
    accept = (request.headers.get("accept") or "").lower()
    if "application/json" in accept and "text/html" not in accept:
        return True
    return False


def configure_console(templates_dir: str) -> APIRouter:
    global TEMPLATES
    TEMPLATES = Jinja2Templates(directory=templates_dir)
    router = APIRouter()

    @router.get("/login", include_in_schema=False)
    async def login_page(request: Request, next: Optional[str] = None):
        if current_console_user(request) and console_login_configured():
            return RedirectResponse(safe_next_url(next), status_code=303)
        configured = console_login_configured()
        return login_response(
            request,
            error=None if configured else "login not configured",
            username=console_username() if configured else "",
            next_url=safe_next_url(next),
            remember_checked=True,
        )

    @router.post("/login", include_in_schema=False)
    async def login_submit(
        request: Request,
        username: str = Form(""),
        password: str = Form(""),
        csrf_token: str = Form(""),
        next: str = Form("/"),
        remember: Optional[str] = Form(None),
    ):
        require_console_csrf(request, csrf_token)
        next_url = safe_next_url(next)
        remember_me = remember in {"1", "on", "true", "yes"}
        ip = client_ip(request)

        def render_error(message: str, status_code: int, *, remember_checked: bool):
            return login_response(
                request,
                error=message,
                username=username,
                next_url=next_url,
                remember_checked=remember_checked,
                status_code=status_code,
            )

        if not console_login_allowed(ip):
            return render_error(
                "Too many login attempts. Try again in 15 minutes.",
                429,
                remember_checked=remember_me,
            )

        if not console_login_configured():
            record_console_login_failure(ip)
            return render_error("login not configured", 403, remember_checked=remember_me)

        if not verify_console_credentials(username, password):
            record_console_login_failure(ip)
            return render_error("Incorrect username or password.", 401, remember_checked=remember_me)

        redirect = RedirectResponse(next_url, status_code=303)
        set_console_session(
            redirect,
            request,
            {
                "console_user": console_username(),
                "csrf": csrf_token or ensure_console_csrf(request, redirect),
            },
            remember=remember_me,
        )
        return redirect

    @router.api_route("/logout", methods=["GET", "POST"], include_in_schema=False)
    async def logout(request: Request):
        redirect = RedirectResponse("/login", status_code=303)
        clear_console_session(redirect)
        return redirect

    return router


async def console_auth_middleware(request: Request, call_next):
    path = request.url.path or "/"
    if is_public_path(path):
        return await call_next(request)
    if current_console_user(request):
        return await call_next(request)
    # Machine callers may use the control token on API routes.
    if path.startswith("/api/"):
        from seo_bot.auth import control_token_is_valid

        if control_token_is_valid(request):
            return await call_next(request)
    if wants_json(request):
        return JSONResponse({"detail": "Authentication required."}, status_code=401)
    next_url = path
    if request.url.query:
        next_url = f"{path}?{request.url.query}"
    return RedirectResponse(f"/login?next={safe_next_url(next_url)}", status_code=303)
