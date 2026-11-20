"""Multi-tenant prototype routes: signup, login, sites, and per-site audits."""

from __future__ import annotations

import asyncio
import sqlite3
from typing import Any, Dict, Optional, Set
from urllib.parse import quote, urlparse

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates

from seo_bot.analyzer import analyze_crawl
from seo_bot.auth import (
    clear_session,
    client_ip,
    current_user_id,
    ensure_csrf,
    get_session,
    hash_password,
    normalize_email,
    persist_session,
    rate_limit_ok,
    require_csrf,
    validate_credentials,
    verify_password,
)
from seo_bot.crawler import crawl_site
from seo_bot.db import (
    MAX_SITES_PER_USER,
    add_site,
    count_sites,
    create_site_run,
    create_user,
    delete_site,
    delete_user,
    finish_site_run,
    get_site,
    get_user_by_email,
    get_user_by_id,
    latest_completed_site_run,
    latest_site_run,
    list_sites,
)
from seo_bot.keywords import discover_keywords_generic, seeds_from_pages
from seo_bot.ssrf import UnsafeURLError, assert_public_http_url

TENANT_MAX_PAGES = 25
templates: Optional[Jinja2Templates] = None
router = APIRouter()
site_locks: dict[int, asyncio.Lock] = {}
site_subscribers: dict[int, Set[asyncio.Queue]] = {}
site_status: dict[int, str] = {}


def configure(template_dir: str) -> APIRouter:
    global templates
    templates = Jinja2Templates(directory=template_dir)
    return router


def _templates() -> Jinja2Templates:
    assert templates is not None
    return templates


def _lock_for(site_id: int) -> asyncio.Lock:
    lock = site_locks.get(site_id)
    if lock is None:
        lock = asyncio.Lock()
        site_locks[site_id] = lock
    return lock


def _prepare_csrf(request: Request) -> str:
    session = get_session(request)
    extra = getattr(request.state, "session_updates", None)
    if isinstance(extra, dict) and extra.get("csrf"):
        return str(extra["csrf"])
    token = session.get("csrf")
    if not token:
        token = __import__("secrets").token_urlsafe(32)
        merged = dict(session)
        merged["csrf"] = token
        request.state.session_updates = merged
    return str(token)


def _ctx(request: Request, **extra: Any) -> Dict[str, Any]:
    session = get_session(request)
    uid = current_user_id(request)
    user = get_user_by_id(uid) if uid else None
    return {
        "request": request,
        "csrf_token": _prepare_csrf(request),
        "user_email": (user or {}).get("email") or session.get("email") or "",
        "logged_in": bool(uid),
        **extra,
    }


def _html(request: Request, name: str, status_code: int = 200, **extra: Any) -> HTMLResponse:
    response = _templates().TemplateResponse(request, name, _ctx(request, **extra), status_code=status_code)
    persist_session(response, request)
    return response


def _owned_site(user_id: int, site_id: int) -> Optional[Dict[str, Any]]:
    site = get_site(site_id)
    if not site or int(site["user_id"]) != int(user_id):
        return None
    return site


async def _emit_site(site_id: int, level: str, stage: str, message: str, meta: Optional[Dict[str, Any]] = None) -> None:
    from datetime import datetime, timezone

    payload = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "level": level,
        "stage": stage,
        "message": message,
        "meta": meta or {},
    }
    site_status[site_id] = stage
    for q in list(site_subscribers.get(site_id, set())):
        try:
            q.put_nowait(payload)
        except Exception:
            pass


async def execute_site_audit(site_id: int) -> Dict[str, Any]:
    site = get_site(site_id)
    if not site:
        return {"ok": False, "error": "Site not found."}
    lock = _lock_for(site_id)
    if lock.locked():
        return {"ok": False, "error": "An audit is already running for this site."}

    async with lock:
        site_status[site_id] = "crawling"
        run_id = create_site_run(site_id)

        async def emit(level: str, stage: str, message: str, meta: Optional[Dict[str, Any]] = None) -> None:
            await _emit_site(site_id, level, stage, message, meta)

        await emit("info", "init", f"Starting audit of {site['url']} (max {TENANT_MAX_PAGES} pages) ...", {})
        try:
            crawl_data = await crawl_site(emit, site["url"], max_pages=TENANT_MAX_PAGES)
            await emit("info", "analyze", "Computing SEO scores and generic CTR snippet rewrites ...", {})
            analysis = analyze_crawl(crawl_data)
            seeds = seeds_from_pages(analysis.get("pages") or [], site["host"])
            keywords = await discover_keywords_generic(seeds, emit, brand=site["host"].split(".")[0])
            result = {
                "pages": analysis["pages"],
                "issues": analysis["issues"],
                "rewrites": analysis["rewrites"],
                "keywords": keywords,
                "summary": analysis["summary"],
                "overall_score": analysis["overall_score"],
                "avg_response_ms": analysis["avg_response_ms"],
                "total_bytes": analysis["total_bytes"],
                "robots_found": crawl_data["robots_found"],
                "sitemap_found": crawl_data["sitemap_found"],
                "sitemap_urls_count": len(crawl_data["sitemap_urls"]),
                "target_url": crawl_data["target_url"],
            }
            # Drop raw HTML if any slipped through
            for page in result["pages"]:
                page.pop("html", None)
            finish_site_run(run_id, "completed", len(analysis["pages"]), analysis["overall_score"], result)
            await emit(
                "success",
                "score",
                f"Audit complete: score {analysis['overall_score']}/100 across {len(analysis['pages'])} pages.",
                {"done": True, "score": analysis["overall_score"]},
            )
            site_status[site_id] = "idle"
            return {"ok": True, "run_id": run_id, "score": analysis["overall_score"]}
        except Exception as exc:
            finish_site_run(run_id, "failed", 0, 0.0, {"error": str(exc)})
            await emit("error", "error", f"Audit failed: {exc}", {"done": True})
            site_status[site_id] = "idle"
            return {"ok": False, "error": str(exc)}


@router.get("/app", include_in_schema=False)
async def app_root(request: Request):
    if current_user_id(request):
        return RedirectResponse("/app/sites", status_code=303)
    return RedirectResponse("/app/login", status_code=303)


@router.get("/app/signup", response_class=HTMLResponse)
async def signup_get(request: Request):
    if current_user_id(request):
        return RedirectResponse("/app/sites", status_code=303)
    return _html(request, "signup.html")


@router.post("/app/signup")
async def signup_post(request: Request, email: str = Form(""), password: str = Form(""), csrf_token: str = Form("")):
    if not rate_limit_ok("signup", client_ip(request)):
        return _html(request, "signup.html", 429, error="Too many signup attempts. Please wait and try again.")
    try:
        require_csrf(request, csrf_token)
        email_n = validate_credentials(email, password)
    except Exception as exc:
        detail = getattr(exc, "detail", None) or str(exc)
        return _html(request, "signup.html", 400, error=detail, email=email)
    if get_user_by_email(email_n):
        return _html(request, "signup.html", 400, error="That email is already registered. Try logging in.", email=email_n)
    uid = create_user(email_n, hash_password(password))
    response = RedirectResponse("/app/sites", status_code=303)
    persist_session(response, request, uid=uid, email=email_n, csrf=__import__("secrets").token_urlsafe(32))
    return response


@router.get("/app/login", response_class=HTMLResponse)
async def login_get(request: Request, next: str = "/app/sites"):
    if current_user_id(request):
        return RedirectResponse("/app/sites", status_code=303)
    return _html(request, "login.html", next_url=next or "/app/sites")


@router.post("/app/login")
async def login_post(
    request: Request,
    email: str = Form(""),
    password: str = Form(""),
    csrf_token: str = Form(""),
    next: str = Form("/app/sites"),
):
    if not rate_limit_ok("login", client_ip(request)):
        return _html(request, "login.html", 429, error="Too many login attempts. Please wait and try again.", email=email)
    try:
        require_csrf(request, csrf_token)
    except Exception as exc:
        return _html(request, "login.html", 403, error=getattr(exc, "detail", "Invalid CSRF token."), email=email)
    email_n = normalize_email(email)
    user = get_user_by_email(email_n)
    if not user or not verify_password(password, user["password_hash"]):
        return _html(request, "login.html", 401, error="Email or password is incorrect.", email=email_n)
    dest = next if isinstance(next, str) and next.startswith("/app") else "/app/sites"
    response = RedirectResponse(dest, status_code=303)
    persist_session(response, request, uid=user["id"], email=user["email"], csrf=__import__("secrets").token_urlsafe(32))
    return response


@router.post("/app/logout")
async def logout(request: Request, csrf_token: str = Form("")):
    require_csrf(request, csrf_token)
    response = RedirectResponse("/app/login", status_code=303)
    clear_session(response)
    return response


@router.get("/app/sites", response_class=HTMLResponse)
async def sites_list(request: Request, error: Optional[str] = None, notice: Optional[str] = None):
    uid = current_user_id(request)
    if not uid:
        return RedirectResponse("/app/login", status_code=303)
    sites = list_sites(uid)
    return _html(
        request,
        "sites.html",
        sites=sites,
        site_count=len(sites),
        max_sites=MAX_SITES_PER_USER,
        error=error,
        notice=notice,
    )


@router.post("/app/sites")
async def sites_add(request: Request, url: str = Form(""), csrf_token: str = Form("")):
    uid = current_user_id(request)
    if not uid:
        return RedirectResponse("/app/login", status_code=303)
    try:
        require_csrf(request, csrf_token)
    except Exception as exc:
        return RedirectResponse("/app/sites?error=" + quote(str(getattr(exc, "detail", exc))), status_code=303)
    if count_sites(uid) >= MAX_SITES_PER_USER:
        return RedirectResponse("/app/sites?error=" + quote(f"Prototype cap is {MAX_SITES_PER_USER} sites per account."), status_code=303)
    try:
        clean = assert_public_http_url(url)
    except UnsafeURLError as exc:
        return RedirectResponse("/app/sites?error=" + quote(str(exc)), status_code=303)
    parsed = urlparse(clean)
    host = (parsed.hostname or "").rstrip(".").lower().removeprefix("www.")
    canonical = f"{parsed.scheme}://{parsed.hostname}{parsed.path or '/'}"
    if parsed.path in ("", "/"):
        canonical = f"{parsed.scheme}://{parsed.hostname}"
    try:
        add_site(uid, canonical, host)
    except sqlite3.IntegrityError:
        return RedirectResponse("/app/sites?error=" + quote("That site is already on your list."), status_code=303)
    return RedirectResponse("/app/sites", status_code=303)


@router.post("/app/sites/{site_id}/delete")
async def sites_delete(request: Request, site_id: int, csrf_token: str = Form("")):
    uid = current_user_id(request)
    if not uid:
        return RedirectResponse("/app/login", status_code=303)
    require_csrf(request, csrf_token)
    delete_site(site_id, uid)
    return RedirectResponse("/app/sites", status_code=303)


@router.get("/app/sites/{site_id}", response_class=HTMLResponse)
async def site_dashboard(request: Request, site_id: int):
    uid = current_user_id(request)
    if not uid:
        return RedirectResponse("/app/login", status_code=303)
    site = _owned_site(uid, site_id)
    if not site:
        return _html(request, "sites.html", 404, sites=list_sites(uid), site_count=count_sites(uid), max_sites=MAX_SITES_PER_USER, error="Site not found.")
    run = latest_site_run(site_id)
    completed = latest_completed_site_run(site_id)
    return _html(
        request,
        "site_dashboard.html",
        site=site,
        run=run,
        completed=completed,
        running=site_status.get(site_id) in ("crawling", "analyze", "keywords", "init") or (run and run.get("status") == "running"),
    )


@router.post("/app/sites/{site_id}/run")
async def site_run(request: Request, site_id: int, csrf_token: str = Form("")):
    uid = current_user_id(request)
    if not uid:
        return RedirectResponse("/app/login", status_code=303)
    require_csrf(request, csrf_token)
    site = _owned_site(uid, site_id)
    if not site:
        return RedirectResponse("/app/sites?error=" + quote("Site not found."), status_code=303)
    if _lock_for(site_id).locked():
        return RedirectResponse(f"/app/sites/{site_id}", status_code=303)
    asyncio.create_task(execute_site_audit(site_id))
    return RedirectResponse(f"/app/sites/{site_id}", status_code=303)


@router.post("/app/account/delete")
async def account_delete(request: Request, csrf_token: str = Form("")):
    uid = current_user_id(request)
    if not uid:
        return RedirectResponse("/app/login", status_code=303)
    require_csrf(request, csrf_token)
    delete_user(uid)
    response = RedirectResponse("/app/signup?deleted=1", status_code=303)
    clear_session(response)
    return response


@router.get("/api/app/sites/{site_id}")
async def api_site_dashboard(request: Request, site_id: int):
    uid = current_user_id(request)
    if not uid:
        return JSONResponse({"error": "Authentication required."}, status_code=401)
    site = _owned_site(uid, site_id)
    if not site:
        return JSONResponse({"error": "Site not found."}, status_code=404)
    run = latest_site_run(site_id)
    completed = latest_completed_site_run(site_id)
    result = (completed or run or {}).get("result") or {}
    return {
        "site": site,
        "latest_run_status": (run or {}).get("status") or "idle",
        "running": site_status.get(site_id) in ("crawling", "analyze", "keywords", "init") or (run and run.get("status") == "running"),
        "active_run": completed or run,
        "pages": result.get("pages") or [],
        "issues": result.get("issues") or [],
        "rewrites": result.get("rewrites") or [],
        "keywords": result.get("keywords") or [],
        "summary": result.get("summary") or {},
    }


@router.get("/api/app/sites/{site_id}/events")
async def api_site_events(request: Request, site_id: int):
    import json

    uid = current_user_id(request)
    if not uid:
        return JSONResponse({"error": "Authentication required."}, status_code=401)
    if not _owned_site(uid, site_id):
        return JSONResponse({"error": "Site not found."}, status_code=404)

    q: asyncio.Queue = asyncio.Queue(maxsize=100)
    site_subscribers.setdefault(site_id, set()).add(q)

    async def event_stream():
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    ev = await asyncio.wait_for(q.get(), timeout=15.0)
                    yield f"event: activity\ndata: {json.dumps(ev)}\n\n"
                except asyncio.TimeoutError:
                    yield ": heartbeat\n\n"
        finally:
            site_subscribers.get(site_id, set()).discard(q)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )
