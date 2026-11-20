import asyncio
import os
import time
import xml.etree.ElementTree as ET
from typing import Any, Awaitable, Callable, Dict, List, Optional, Set, Tuple
from urllib.parse import urljoin, urlparse, urlunparse
from urllib.robotparser import RobotFileParser

import httpx
from bs4 import BeautifulSoup

TARGET_URL = os.environ.get("TARGET_URL", "https://genemeal.onrender.com").rstrip("/")
USER_AGENT = "GeneMealSEOBot/1.0 (+https://genemeal.onrender.com; organic-seo-audit)"
MAX_PAGES = int(os.environ.get("SEO_MAX_PAGES", "20"))
POLITE_DELAY_SEC = float(os.environ.get("SEO_POLITE_DELAY", "0.35"))

EmitFn = Callable[[str, str, str, Optional[Dict[str, Any]]], Awaitable[None]]

SKIP_EXTENSIONS = (
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".ico",
    ".css", ".js", ".pdf", ".zip", ".woff", ".woff2", ".ttf",
    ".mp4", ".webm", ".json", ".xml", ".txt",
)


def normalize_url(url: str) -> str:
    parsed = urlparse(url)
    path = parsed.path or "/"
    if path != "/" and path.endswith("/"):
        path = path[:-1]
    return urlunparse((parsed.scheme.lower(), parsed.netloc.lower(), path, "", "", ""))


def is_same_origin(url: str, base_netloc: str) -> bool:
    p = urlparse(url)
    return p.scheme in ("http", "https") and p.netloc.lower() == base_netloc.lower()


def should_skip_asset(url: str) -> bool:
    path = urlparse(url).path.lower()
    return any(path.endswith(ext) for ext in SKIP_EXTENSIONS)


async def fetch_robots(client: httpx.AsyncClient, base_url: str, emit: EmitFn) -> Tuple[bool, RobotFileParser, List[str]]:
    robots_url = f"{base_url}/robots.txt"
    rp = RobotFileParser()
    rp.set_url(robots_url)
    sitemaps: List[str] = []
    await emit("info", "robots", f"Fetching {robots_url} ...", {"url": robots_url})
    try:
        resp = await client.get(robots_url)
        if resp.status_code == 200 and "user-agent" in resp.text.lower():
            lines = resp.text.splitlines()
            rp.parse(lines)
            for line in lines:
                if line.lower().startswith("sitemap:"):
                    sm = line.split(":", 1)[1].strip()
                    if sm:
                        sitemaps.append(sm)
            await emit(
                "success",
                "robots",
                f"robots.txt verified (HTTP 200, {len(lines)} rules, {len(sitemaps)} sitemap directive).",
                {"lines": len(lines)},
            )
            return True, rp, sitemaps
        await emit("warn", "robots", f"robots.txt returned HTTP {resp.status_code}; assuming cautious allow.", {"status": resp.status_code})
        rp.parse(["User-agent: *", "Allow: /"])
        return False, rp, sitemaps
    except Exception as exc:
        await emit("warn", "robots", f"robots.txt check failed ({exc}); using cautious default.", {})
        rp.parse(["User-agent: *", "Allow: /"])
        return False, rp, sitemaps


async def fetch_sitemap(
    client: httpx.AsyncClient, base_url: str, sitemap_urls: List[str], base_netloc: str, emit: EmitFn
) -> Tuple[bool, Set[str]]:
    candidates = sitemap_urls or [f"{base_url}/sitemap.xml"]
    discovered: Set[str] = set()
    found_any = False

    for sm_url in candidates[:3]:
        await emit("info", "sitemap", f"Inspecting XML sitemap at {sm_url} ...", {"url": sm_url})
        try:
            resp = await client.get(sm_url)
            if resp.status_code != 200:
                await emit("warn", "sitemap", f"Sitemap {sm_url} returned HTTP {resp.status_code}.", {"status": resp.status_code})
                continue
            root = ET.fromstring(resp.text)
            for elem in root.iter():
                if elem.tag.endswith("loc") and elem.text:
                    loc = elem.text.strip()
                    if is_same_origin(loc, base_netloc):
                        discovered.add(normalize_url(loc))
            found_any = True
            await emit(
                "success",
                "sitemap",
                f"Parsed sitemap.xml: {len(discovered)} same-origin URLs indexed.",
                {"count": len(discovered)},
            )
        except Exception as exc:
            await emit("warn", "sitemap", f"Failed parsing sitemap {sm_url}: {exc}", {})

    return found_any, discovered


async def crawl_site(emit: EmitFn, target_url: str = TARGET_URL) -> Dict[str, Any]:
    base_url = target_url.rstrip("/")
    base_netloc = urlparse(base_url).netloc

    async with httpx.AsyncClient(
        follow_redirects=True,
        timeout=httpx.Timeout(15.0, connect=8.0),
        headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"},
    ) as client:
        robots_found, rp, sitemap_directives = await fetch_robots(client, base_url, emit)
        sitemap_found, sitemap_urls = await fetch_sitemap(client, base_url, sitemap_directives, base_netloc, emit)

        queue: List[str] = []
        seen_queued: Set[str] = set()

        def enqueue(u: str) -> None:
            nu = normalize_url(u)
            if nu in seen_queued:
                return
            if not is_same_origin(nu, base_netloc):
                return
            if should_skip_asset(nu):
                return
            if not rp.can_fetch(USER_AGENT, nu):
                return
            seen_queued.add(nu)
            queue.append(nu)

        enqueue(base_url + "/")
        for sm_u in sorted(sitemap_urls):
            enqueue(sm_u)

        crawled_pages: List[Dict[str, Any]] = []
        status_cache: Dict[str, int] = {}
        disallowed_skipped: Set[str] = set()

        while queue and len(crawled_pages) < MAX_PAGES:
            url = queue.pop(0)
            path = urlparse(url).path or "/"
            await emit("info", "crawl", f"Crawling {path} ...", {"url": url, "index": len(crawled_pages) + 1})

            t0 = time.perf_counter()
            try:
                resp = await client.get(url)
                elapsed_ms = (time.perf_counter() - t0) * 1000.0
                final_url = normalize_url(str(resp.url))
                status_cache[url] = resp.status_code
                status_cache[final_url] = resp.status_code
                ctype = resp.headers.get("content-type", "").lower()

                if "text/html" not in ctype and resp.status_code == 200:
                    await emit("warn", "crawl", f"Skipped non-HTML resource {path} ({ctype}).", {"url": url})
                    continue

                html = resp.text
                content_bytes = len(resp.content)
                soup = BeautifulSoup(html, "html.parser")

                internal_links: List[str] = []
                for a in soup.find_all("a", href=True):
                    href = a["href"].strip()
                    if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
                        continue
                    abs_url = urljoin(str(resp.url), href)
                    if is_same_origin(abs_url, base_netloc):
                        nu = normalize_url(abs_url)
                        internal_links.append(nu)
                        if not should_skip_asset(nu):
                            if rp.can_fetch(USER_AGENT, nu):
                                enqueue(nu)
                            else:
                                disallowed_skipped.add(nu)

                crawled_pages.append(
                    {
                        "url": url,
                        "final_url": final_url,
                        "path": path,
                        "status_code": resp.status_code,
                        "response_ms": elapsed_ms,
                        "content_bytes": content_bytes,
                        "html": html,
                        "in_sitemap": url in sitemap_urls or final_url in sitemap_urls,
                        "internal_links": list(dict.fromkeys(internal_links)),
                    }
                )
                lvl = "success" if resp.status_code == 200 else "warn"
                await emit(
                    lvl,
                    "crawl",
                    f"Audited {path} -> HTTP {resp.status_code} ({elapsed_ms:.0f} ms, {content_bytes/1024:.1f} KB)",
                    {"path": path, "status": resp.status_code, "ms": round(elapsed_ms, 1)},
                )
            except Exception as exc:
                elapsed_ms = (time.perf_counter() - t0) * 1000.0
                status_cache[url] = 0
                crawled_pages.append(
                    {
                        "url": url,
                        "final_url": url,
                        "path": path,
                        "status_code": 0,
                        "response_ms": elapsed_ms,
                        "content_bytes": 0,
                        "html": "",
                        "in_sitemap": url in sitemap_urls,
                        "internal_links": [],
                        "error": str(exc),
                    }
                )
                await emit("error", "crawl", f"Error fetching {path}: {exc}", {"path": path})

            await asyncio.sleep(POLITE_DELAY_SEC)

        # Politely check any remaining allowed internal links for broken status (cap 15)
        unchecked: List[str] = []
        for p in crawled_pages:
            for link in p["internal_links"]:
                if link not in status_cache and link not in unchecked and rp.can_fetch(USER_AGENT, link):
                    unchecked.append(link)
        for link in unchecked[:15]:
            try:
                r = await client.head(link)
                if r.status_code == 405:
                    r = await client.get(link)
                status_cache[link] = r.status_code
                await asyncio.sleep(0.15)
            except Exception:
                status_cache[link] = 0

        if disallowed_skipped:
            await emit(
                "info",
                "robots",
                f"Respected robots.txt Disallow on {len(disallowed_skipped)} private/checkout routes (e.g. {', '.join(sorted(urlparse(u).path for u in disallowed_skipped)[:4])}).",
                {"skipped": len(disallowed_skipped)},
            )

        return {
            "target_url": base_url,
            "robots_found": robots_found,
            "sitemap_found": sitemap_found,
            "sitemap_urls": sorted(sitemap_urls),
            "pages": crawled_pages,
            "status_cache": status_cache,
            "disallowed_skipped_count": len(disallowed_skipped),
        }
