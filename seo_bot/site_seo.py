"""Public origin, robots.txt, and sitemap for this bot's own pages."""

from __future__ import annotations

import os
from datetime import date

DEFAULT_PUBLIC_ORIGIN = "https://genemeal-seo-bot.onrender.com"

# Traction signup is the only page we want indexed. The operator console, console
# login, Traction login, site dashboards, and API/docs are noindexed (and the
# console plus API/docs are disallowed).
INDEXABLE_PATHS = ("/app/signup",)


def public_origin() -> str:
    return (os.environ.get("PUBLIC_BASE_URL") or DEFAULT_PUBLIC_ORIGIN).rstrip("/")


def robots_txt() -> str:
    origin = public_origin()
    return (
        "User-agent: *\n"
        "Allow: /app/signup\n"
        "Disallow: /\n"
        "Disallow: /login\n"
        "Disallow: /api/\n"
        "Disallow: /docs\n"
        "Disallow: /docs/\n"
        "Disallow: /redoc\n"
        "Disallow: /redoc/\n"
        "Disallow: /openapi.json\n"
        f"Sitemap: {origin}/sitemap.xml\n"
    )


def sitemap_xml() -> str:
    origin = public_origin()
    today = date.today().isoformat()
    urls = "\n".join(
        f"  <url><loc>{origin}{path}</loc><lastmod>{today}</lastmod></url>"
        for path in INDEXABLE_PATHS
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f"{urls}\n"
        "</urlset>\n"
    )


def should_noindex_api_or_docs(path: str) -> bool:
    return (
        path.startswith("/api/")
        or path in {"/docs", "/redoc", "/openapi.json"}
        or path.startswith("/docs/")
        or path.startswith("/redoc/")
    )
