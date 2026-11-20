import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

DB_PATH = os.environ.get("SEO_DB_PATH", "/tmp/genemeal_seo.db")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    with get_conn() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS crawl_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                status TEXT NOT NULL,
                trigger TEXT NOT NULL,
                target_url TEXT NOT NULL,
                pages_crawled INTEGER DEFAULT 0,
                overall_score REAL DEFAULT 0,
                avg_response_ms REAL DEFAULT 0,
                total_bytes INTEGER DEFAULT 0,
                robots_found INTEGER DEFAULT 0,
                sitemap_found INTEGER DEFAULT 0,
                sitemap_urls_count INTEGER DEFAULT 0,
                summary_json TEXT DEFAULT '{}'
            );

            CREATE TABLE IF NOT EXISTS page_audits (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER NOT NULL,
                url TEXT NOT NULL,
                path TEXT NOT NULL,
                status_code INTEGER DEFAULT 0,
                response_ms REAL DEFAULT 0,
                content_bytes INTEGER DEFAULT 0,
                word_count INTEGER DEFAULT 0,
                title TEXT DEFAULT '',
                title_len INTEGER DEFAULT 0,
                meta_description TEXT DEFAULT '',
                meta_desc_len INTEGER DEFAULT 0,
                h1_count INTEGER DEFAULT 0,
                h1_text TEXT DEFAULT '',
                canonical_url TEXT DEFAULT '',
                og_title TEXT DEFAULT '',
                og_description TEXT DEFAULT '',
                og_image TEXT DEFAULT '',
                twitter_card TEXT DEFAULT '',
                json_ld_types TEXT DEFAULT '[]',
                images_total INTEGER DEFAULT 0,
                images_missing_alt INTEGER DEFAULT 0,
                internal_links_count INTEGER DEFAULT 0,
                broken_links_count INTEGER DEFAULT 0,
                in_sitemap INTEGER DEFAULT 0,
                page_score REAL DEFAULT 0,
                category_scores_json TEXT DEFAULT '{}',
                issues_json TEXT DEFAULT '[]',
                FOREIGN KEY (run_id) REFERENCES crawl_runs(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS issues (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER NOT NULL,
                page_url TEXT NOT NULL,
                severity TEXT NOT NULL,
                category TEXT NOT NULL,
                title TEXT NOT NULL,
                detail TEXT NOT NULL,
                recommendation TEXT NOT NULL,
                FOREIGN KEY (run_id) REFERENCES crawl_runs(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS ctr_rewrites (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER NOT NULL,
                page_url TEXT NOT NULL,
                path TEXT NOT NULL,
                current_title TEXT NOT NULL,
                suggested_title TEXT NOT NULL,
                current_meta TEXT NOT NULL,
                suggested_meta TEXT NOT NULL,
                rationale TEXT NOT NULL,
                expected_ctr_impact TEXT NOT NULL,
                FOREIGN KEY (run_id) REFERENCES crawl_runs(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS keywords (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                discovered_at TEXT NOT NULL,
                keyword TEXT UNIQUE NOT NULL,
                seed_term TEXT NOT NULL,
                source TEXT NOT NULL,
                intent TEXT NOT NULL,
                relevance_score INTEGER DEFAULT 50,
                suggested_angle TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS draft_queue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                title TEXT NOT NULL,
                slug TEXT UNIQUE NOT NULL,
                target_keyword TEXT NOT NULL,
                meta_description TEXT NOT NULL,
                outline_json TEXT NOT NULL,
                positioning_notes TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending'
            );

            CREATE TABLE IF NOT EXISTS activity_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL,
                level TEXT NOT NULL,
                stage TEXT NOT NULL,
                message TEXT NOT NULL,
                meta_json TEXT DEFAULT '{}'
            );
            """
        )


def log_activity(level: str, stage: str, message: str, meta: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    ts = utc_now_iso()
    meta_str = json.dumps(meta or {})
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO activity_events (ts, level, stage, message, meta_json) VALUES (?, ?, ?, ?, ?)",
            (ts, level, stage, message, meta_str),
        )
        event_id = cur.lastrowid
        # Keep table compact (last 250 events)
        conn.execute(
            "DELETE FROM activity_events WHERE id NOT IN (SELECT id FROM activity_events ORDER BY id DESC LIMIT 250)"
        )
    return {
        "id": event_id,
        "ts": ts,
        "level": level,
        "stage": stage,
        "message": message,
        "meta": meta or {},
    }


def get_recent_events(limit: int = 80) -> List[Dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, ts, level, stage, message, meta_json FROM activity_events ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    out = []
    for r in reversed(rows):
        out.append(
            {
                "id": r["id"],
                "ts": r["ts"],
                "level": r["level"],
                "stage": r["stage"],
                "message": r["message"],
                "meta": json.loads(r["meta_json"] or "{}"),
            }
        )
    return out


def create_run(trigger: str, target_url: str) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO crawl_runs (started_at, status, trigger, target_url) VALUES (?, 'running', ?, ?)",
            (utc_now_iso(), trigger, target_url),
        )
        return cur.lastrowid


def finish_run(
    run_id: int,
    status: str,
    pages_crawled: int,
    overall_score: float,
    avg_response_ms: float,
    total_bytes: int,
    robots_found: bool,
    sitemap_found: bool,
    sitemap_urls_count: int,
    summary: Dict[str, Any],
) -> None:
    with get_conn() as conn:
        conn.execute(
            """
            UPDATE crawl_runs SET
                finished_at = ?,
                status = ?,
                pages_crawled = ?,
                overall_score = ?,
                avg_response_ms = ?,
                total_bytes = ?,
                robots_found = ?,
                sitemap_found = ?,
                sitemap_urls_count = ?,
                summary_json = ?
            WHERE id = ?
            """,
            (
                utc_now_iso(),
                status,
                pages_crawled,
                round(overall_score, 1),
                round(avg_response_ms, 1),
                total_bytes,
                1 if robots_found else 0,
                1 if sitemap_found else 0,
                sitemap_urls_count,
                json.dumps(summary),
                run_id,
            ),
        )


def save_run_details(
    run_id: int,
    pages: List[Dict[str, Any]],
    issues: List[Dict[str, Any]],
    rewrites: List[Dict[str, Any]],
) -> None:
    with get_conn() as conn:
        for p in pages:
            conn.execute(
                """
                INSERT INTO page_audits (
                    run_id, url, path, status_code, response_ms, content_bytes, word_count,
                    title, title_len, meta_description, meta_desc_len, h1_count, h1_text,
                    canonical_url, og_title, og_description, og_image, twitter_card,
                    json_ld_types, images_total, images_missing_alt, internal_links_count,
                    broken_links_count, in_sitemap, page_score, category_scores_json, issues_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    p["url"],
                    p["path"],
                    p["status_code"],
                    round(p["response_ms"], 1),
                    p["content_bytes"],
                    p["word_count"],
                    p["title"],
                    p["title_len"],
                    p["meta_description"],
                    p["meta_desc_len"],
                    p["h1_count"],
                    p["h1_text"],
                    p["canonical_url"],
                    p["og_title"],
                    p["og_description"],
                    p["og_image"],
                    p["twitter_card"],
                    json.dumps(p["json_ld_types"]),
                    p["images_total"],
                    p["images_missing_alt"],
                    p["internal_links_count"],
                    p["broken_links_count"],
                    1 if p["in_sitemap"] else 0,
                    round(p["page_score"], 1),
                    json.dumps(p["category_scores"]),
                    json.dumps(p["issues"]),
                ),
            )

        for iss in issues:
            conn.execute(
                """
                INSERT INTO issues (run_id, page_url, severity, category, title, detail, recommendation)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    iss["page_url"],
                    iss["severity"],
                    iss["category"],
                    iss["title"],
                    iss["detail"],
                    iss["recommendation"],
                ),
            )

        for rw in rewrites:
            conn.execute(
                """
                INSERT INTO ctr_rewrites (
                    run_id, page_url, path, current_title, suggested_title,
                    current_meta, suggested_meta, rationale, expected_ctr_impact
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    rw["page_url"],
                    rw["path"],
                    rw["current_title"],
                    rw["suggested_title"],
                    rw["current_meta"],
                    rw["suggested_meta"],
                    rw["rationale"],
                    rw["expected_ctr_impact"],
                ),
            )


def upsert_keywords(items: List[Dict[str, Any]]) -> int:
    now = utc_now_iso()
    count = 0
    with get_conn() as conn:
        for item in items:
            conn.execute(
                """
                INSERT INTO keywords (discovered_at, keyword, seed_term, source, intent, relevance_score, suggested_angle)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(keyword) DO UPDATE SET
                    discovered_at = excluded.discovered_at,
                    seed_term = excluded.seed_term,
                    source = excluded.source,
                    intent = excluded.intent,
                    relevance_score = excluded.relevance_score,
                    suggested_angle = excluded.suggested_angle
                """,
                (
                    now,
                    item["keyword"],
                    item["seed_term"],
                    item["source"],
                    item["intent"],
                    item["relevance_score"],
                    item["suggested_angle"],
                ),
            )
            count += 1
    return count


def upsert_drafts(drafts: List[Dict[str, Any]]) -> int:
    now = utc_now_iso()
    added = 0
    with get_conn() as conn:
        for d in drafts:
            existing = conn.execute("SELECT id, status FROM draft_queue WHERE slug = ?", (d["slug"],)).fetchone()
            if existing:
                # Preserve user's approved/rejected status
                conn.execute(
                    """
                    UPDATE draft_queue SET
                        updated_at = ?,
                        title = ?,
                        target_keyword = ?,
                        meta_description = ?,
                        outline_json = ?,
                        positioning_notes = ?
                    WHERE id = ?
                    """,
                    (
                        now,
                        d["title"],
                        d["target_keyword"],
                        d["meta_description"],
                        json.dumps(d["outline"]),
                        d["positioning_notes"],
                        existing["id"],
                    ),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO draft_queue (
                        created_at, updated_at, title, slug, target_keyword,
                        meta_description, outline_json, positioning_notes, status
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending')
                    """,
                    (
                        now,
                        now,
                        d["title"],
                        d["slug"],
                        d["target_keyword"],
                        d["meta_description"],
                        json.dumps(d["outline"]),
                        d["positioning_notes"],
                    ),
                )
                added += 1
    return added


def update_draft_status(draft_id: int, status: str) -> Optional[Dict[str, Any]]:
    if status not in ("pending", "approved", "rejected"):
        raise ValueError("Invalid draft status")
    with get_conn() as conn:
        conn.execute(
            "UPDATE draft_queue SET status = ?, updated_at = ? WHERE id = ?",
            (status, utc_now_iso(), draft_id),
        )
        row = conn.execute("SELECT * FROM draft_queue WHERE id = ?", (draft_id,)).fetchone()
        if not row:
            return None
        d = dict(row)
        d["outline"] = json.loads(d.pop("outline_json") or "[]")
        return d


def get_dashboard_snapshot() -> Dict[str, Any]:
    with get_conn() as conn:
        latest_run = conn.execute(
            "SELECT * FROM crawl_runs ORDER BY id DESC LIMIT 1"
        ).fetchone()
        completed_run = conn.execute(
            "SELECT * FROM crawl_runs WHERE status = 'completed' ORDER BY id DESC LIMIT 1"
        ).fetchone()
        history_runs = conn.execute(
            "SELECT id, started_at, finished_at, status, trigger, pages_crawled, overall_score, avg_response_ms FROM crawl_runs WHERE status = 'completed' ORDER BY id DESC LIMIT 12"
        ).fetchall()

        active_run = completed_run or latest_run
        pages = []
        issues = []
        rewrites = []
        if active_run:
            rid = active_run["id"]
            page_rows = conn.execute(
                "SELECT * FROM page_audits WHERE run_id = ? ORDER BY page_score ASC, path ASC",
                (rid,),
            ).fetchall()
            for r in page_rows:
                p = dict(r)
                p["json_ld_types"] = json.loads(p.pop("json_ld_types") or "[]")
                p["category_scores"] = json.loads(p.pop("category_scores_json") or "{}")
                p["issues"] = json.loads(p.pop("issues_json") or "[]")
                p["in_sitemap"] = bool(p["in_sitemap"])
                pages.append(p)

            issue_rows = conn.execute(
                """
                SELECT * FROM issues WHERE run_id = ?
                ORDER BY CASE severity
                    WHEN 'critical' THEN 1
                    WHEN 'high' THEN 2
                    WHEN 'medium' THEN 3
                    ELSE 4 END, id ASC
                """,
                (rid,),
            ).fetchall()
            issues = [dict(r) for r in issue_rows]

            rw_rows = conn.execute(
                "SELECT * FROM ctr_rewrites WHERE run_id = ? ORDER BY id ASC",
                (rid,),
            ).fetchall()
            rewrites = [dict(r) for r in rw_rows]

        kw_rows = conn.execute(
            "SELECT * FROM keywords ORDER BY relevance_score DESC, id ASC LIMIT 60"
        ).fetchall()
        keywords = [dict(r) for r in kw_rows]

        draft_rows = conn.execute(
            "SELECT * FROM draft_queue ORDER BY CASE status WHEN 'pending' THEN 1 WHEN 'approved' THEN 2 ELSE 3 END, id ASC"
        ).fetchall()
        drafts = []
        for r in draft_rows:
            d = dict(r)
            d["outline"] = json.loads(d.pop("outline_json") or "[]")
            drafts.append(d)

    run_dict = None
    if active_run:
        run_dict = dict(active_run)
        run_dict["summary"] = json.loads(run_dict.pop("summary_json") or "{}")
        run_dict["robots_found"] = bool(run_dict["robots_found"])
        run_dict["sitemap_found"] = bool(run_dict["sitemap_found"])

    return {
        "latest_run_status": latest_run["status"] if latest_run else "idle",
        "active_run": run_dict,
        "history": [dict(r) for r in reversed(history_runs)],
        "pages": pages,
        "issues": issues,
        "rewrites": rewrites,
        "keywords": keywords,
        "drafts": drafts,
    }
