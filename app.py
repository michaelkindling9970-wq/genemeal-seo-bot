import asyncio
import hmac
import json
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Set

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from seo_bot.analyzer import analyze_crawl
from seo_bot.crawler import TARGET_URL, crawl_site
from seo_bot.db import (
    create_run,
    finish_run,
    get_dashboard_snapshot,
    get_recent_events,
    init_db,
    log_activity,
    save_run_details,
    update_draft_status,
    upsert_drafts,
    upsert_keywords,
    get_latest_gsc,
    save_gsc_ingest,
)
from seo_bot.keywords import build_blog_drafts, discover_keywords

STATIC_DIR = Path(__file__).parent / "static"
SCHEDULE_HOURS = float(os.environ.get("SEO_SCHEDULE_HOURS", "6"))
CONTROL_TOKEN = os.environ.get("CONTROL_TOKEN", "").strip()

subscribers: Set[asyncio.Queue] = set()
run_lock = asyncio.Lock()
bot_state: Dict[str, Any] = {
    "status": "idle",
    "stage": "standby",
    "target_url": TARGET_URL,
    "last_run_at": None,
    "next_scheduled_at": None,
    "schedule_hours": SCHEDULE_HOURS,
}


async def emit_event(level: str, stage: str, message: str, meta: Optional[Dict[str, Any]] = None) -> None:
    payload = log_activity(level, stage, message, meta)
    bot_state["stage"] = stage
    dead = []
    for q in list(subscribers):
        try:
            q.put_nowait(payload)
        except Exception:
            dead.append(q)
    for q in dead:
        subscribers.discard(q)


async def execute_audit(trigger: str = "manual", include_keywords: bool = True) -> Dict[str, Any]:
    if run_lock.locked():
        return {"started": False, "reason": "Audit already in progress"}

    async with run_lock:
        bot_state["status"] = "crawling"
        bot_state["stage"] = "init"
        run_id = create_run(trigger, TARGET_URL)
        await emit_event(
            "info",
            "init",
            f"Starting SEO audit run #{run_id} ({trigger}) targeting {TARGET_URL} ...",
            {"run_id": run_id, "trigger": trigger},
        )
        try:
            crawl_data = await crawl_site(emit_event, TARGET_URL)
            await emit_event("info", "analyze", "Computing deterministic SEO scores & CTR snippet rewrites ...", {})
            analysis = analyze_crawl(crawl_data)

            save_run_details(run_id, analysis["pages"], analysis["issues"], analysis["rewrites"])
            finish_run(
                run_id=run_id,
                status="completed",
                pages_crawled=len(analysis["pages"]),
                overall_score=analysis["overall_score"],
                avg_response_ms=analysis["avg_response_ms"],
                total_bytes=analysis["total_bytes"],
                robots_found=crawl_data["robots_found"],
                sitemap_found=crawl_data["sitemap_found"],
                sitemap_urls_count=len(crawl_data["sitemap_urls"]),
                summary=analysis["summary"],
            )
            await emit_event(
                "success",
                "score",
                f"Audit #{run_id} complete: Score {analysis['overall_score']}/100 across {len(analysis['pages'])} pages ({len(analysis['issues'])} findings).",
                {"run_id": run_id, "score": analysis["overall_score"]},
            )

            if include_keywords:
                bot_state["status"] = "discovering"
                kws = await discover_keywords(emit_event)
                upsert_keywords(kws)
                drafts = build_blog_drafts(kws)
                added = upsert_drafts(drafts)
                await emit_event(
                    "success",
                    "drafts",
                    f"Approval queue synced ({len(drafts)} outlines ready, {added} newly queued; draft-only, never auto-published).",
                    {"drafts": len(drafts)},
                )

            bot_state["last_run_at"] = datetime.now(timezone.utc).isoformat()
            bot_state["status"] = "idle"
            bot_state["stage"] = "standby"
            await emit_event("info", "standby", "Bot idle and streaming. Waiting for next schedule or manual trigger.", {"done": True})
            return {"started": True, "run_id": run_id, "score": analysis["overall_score"]}
        except Exception as exc:
            finish_run(run_id, "failed", 0, 0.0, 0.0, 0, False, False, 0, {"error": str(exc)})
            bot_state["status"] = "idle"
            bot_state["stage"] = "error"
            await emit_event("error", "error", f"Audit #{run_id} failed: {exc}", {"run_id": run_id})
            return {"started": True, "run_id": run_id, "error": str(exc)}


async def scheduler_loop() -> None:
    await asyncio.sleep(1.0)
    snap = get_dashboard_snapshot()
    if not snap["active_run"] or snap["active_run"].get("status") != "completed":
        await execute_audit(trigger="startup", include_keywords=True)

    interval_sec = max(1800.0, SCHEDULE_HOURS * 3600.0)
    while True:
        next_ts = datetime.now(timezone.utc).timestamp() + interval_sec
        bot_state["next_scheduled_at"] = datetime.fromtimestamp(next_ts, tz=timezone.utc).isoformat()
        await asyncio.sleep(interval_sec)
        await execute_audit(trigger="scheduled", include_keywords=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    task = asyncio.create_task(scheduler_loop())
    try:
        yield
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


app = FastAPI(title="GeneMeal SEO Bot", version="1.0.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


def require_control_token(
    x_control_token: Optional[str] = Header(default=None),
    authorization: Optional[str] = Header(default=None),
) -> None:
    if not CONTROL_TOKEN:
        return
    token = (x_control_token or "").strip()
    if not token and authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    if not token or not hmac.compare_digest(token, CONTROL_TOKEN):
        raise HTTPException(status_code=401, detail="Valid control token required for control actions.")


class DraftStatusBody(BaseModel):
    status: str


class GscTotals(BaseModel):
    clicks: float = 0
    impressions: float = 0
    ctr: float = 0
    position: float = 0


class GscQueryRow(BaseModel):
    query: str
    clicks: float = 0
    impressions: float = 0
    ctr: float = 0
    position: float = 0


class GscPageRow(BaseModel):
    page: str
    clicks: float = 0
    impressions: float = 0
    ctr: float = 0
    position: float = 0


class GscIngestBody(BaseModel):
    site: str
    start_date: str
    end_date: str
    totals: GscTotals
    queries: list[GscQueryRow] = []
    pages: list[GscPageRow] = []


@app.get("/")
async def index():
    return FileResponse(str(STATIC_DIR / "index.html"))


@app.get("/healthz")
async def healthz():
    return {
        "ok": True,
        "status": bot_state["status"],
        "target_url": TARGET_URL,
        "auth_enabled": bool(CONTROL_TOKEN),
    }


@app.get("/api/dashboard")
async def api_dashboard():
    snap = get_dashboard_snapshot()
    snap["bot_state"] = dict(bot_state)
    snap["gsc_connected"] = True
    snap["gsc"] = snap.get("gsc") or get_latest_gsc()
    snap["auth_required_for_controls"] = bool(CONTROL_TOKEN)
    snap["events"] = get_recent_events(60)
    return JSONResponse(snap)


@app.post("/api/auth/verify", dependencies=[Depends(require_control_token)])
async def api_auth_verify():
    return {"ok": True, "unlocked": True}


@app.post("/api/run", dependencies=[Depends(require_control_token)])
async def api_run():
    if run_lock.locked():
        return JSONResponse({"ok": False, "message": "Audit already running."}, status_code=409)
    asyncio.create_task(execute_audit(trigger="manual", include_keywords=True))
    return {"ok": True, "message": "Live SEO audit started."}


@app.post("/api/keywords/refresh", dependencies=[Depends(require_control_token)])
async def api_keywords_refresh():
    if run_lock.locked():
        return JSONResponse({"ok": False, "message": "Bot busy with active audit."}, status_code=409)

    async def _job():
        async with run_lock:
            bot_state["status"] = "discovering"
            kws = await discover_keywords(emit_event)
            upsert_keywords(kws)
            drafts = build_blog_drafts(kws)
            upsert_drafts(drafts)
            bot_state["status"] = "idle"
            await emit_event("info", "standby", "Keyword refresh finished.", {"done": True})

    asyncio.create_task(_job())
    return {"ok": True, "message": "Keyword discovery started."}


@app.post("/api/drafts/{draft_id}/status", dependencies=[Depends(require_control_token)])
async def api_draft_status(draft_id: int, body: DraftStatusBody):
    try:
        updated = update_draft_status(draft_id, body.status)
    except ValueError:
        raise HTTPException(status_code=400, detail="Status must be pending, approved, or rejected.")
    if not updated:
        raise HTTPException(status_code=404, detail="Draft not found.")
    await emit_event(
        "info",
        "drafts",
        f"Draft #{draft_id} marked '{body.status}' in local approval queue (not published).",
        {"draft_id": draft_id, "status": body.status},
    )
    return {"ok": True, "draft": updated}




@app.post("/api/gsc/ingest", dependencies=[Depends(require_control_token)])
async def api_gsc_ingest(body: GscIngestBody):
    record = save_gsc_ingest(body.model_dump())
    query_count = len(record.get("queries") or [])
    page_count = len(record.get("pages") or [])
    await emit_event(
        "success",
        "gsc",
        f"Search Console snapshot ingested for {record['start_date']} to {record['end_date']} "
        f"({query_count} queries, {page_count} pages).",
        {"queries": query_count, "pages": page_count},
    )
    return {"ok": True, "gsc": record}


@app.get("/api/gsc")
async def api_gsc():
    return {
        "connected": True,
        "gsc": get_latest_gsc(),
        "empty_state": "Search Console connected; Google is still collecting data, usually 2-3 days after verification",
    }

@app.get("/api/events")
async def api_events(request: Request):
    q: asyncio.Queue = asyncio.Queue(maxsize=100)
    subscribers.add(q)

    async def event_stream():
        try:
            recent = get_recent_events(30)
            yield f"event: replay\ndata: {json.dumps(recent)}\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    ev = await asyncio.wait_for(q.get(), timeout=15.0)
                    yield f"event: activity\ndata: {json.dumps(ev)}\n\n"
                except asyncio.TimeoutError:
                    yield ": heartbeat\n\n"
        finally:
            subscribers.discard(q)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
