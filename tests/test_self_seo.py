import re

from seo_bot.site_seo import INDEXABLE_PATHS, public_origin, robots_txt, sitemap_xml


def _meta(html: str, name: str) -> str | None:
    m = re.search(rf'<meta name="{name}" content="([^"]*)"', html)
    return m.group(1) if m else None


def _prop(html: str, name: str) -> str | None:
    m = re.search(rf'<meta property="{name}" content="([^"]*)"', html)
    return m.group(1) if m else None


def _canonical(html: str) -> str | None:
    m = re.search(r'<link rel="canonical" href="([^"]*)"', html)
    return m.group(1) if m else None


def test_robots_and_sitemap_routes(client):
    robots = client.get("/robots.txt")
    assert robots.status_code == 200
    body = robots.text
    assert "User-agent: *" in body
    assert "Allow: /app/signup" in body
    assert "Disallow: /" in body
    assert "Disallow: /login" in body
    assert "Disallow: /api/" in body
    assert "Disallow: /docs" in body
    assert "Disallow: /openapi.json" in body
    assert f"Sitemap: {public_origin()}/sitemap.xml" in body
    assert body == robots_txt()

    sitemap = client.get("/sitemap.xml")
    assert sitemap.status_code == 200
    xml = sitemap.text
    assert xml == sitemap_xml()
    assert f"{public_origin()}/app/signup" in xml
    # Operator console, login, and docs stay out of the sitemap
    assert f"{public_origin()}/</loc>" not in xml
    assert "/app/login" not in xml
    assert "/docs" not in xml
    for path in INDEXABLE_PATHS:
        assert f"{public_origin()}{path}" in xml


def test_operator_console_has_description_canonical_and_noindex(client):
    from tests.test_console_auth import _login

    anonymous = client.get("/", follow_redirects=False)
    assert anonymous.status_code == 303
    assert "/login" in anonymous.headers["location"]

    assert _login(client).status_code == 303
    res = client.get("/")
    assert res.status_code == 200
    html = res.text
    assert "<title>GeneMeal SEO Bot — Live Organic Growth &amp; Audit Console</title>" in html
    desc = _meta(html, "description")
    assert desc
    assert 110 <= len(desc) <= 160
    assert _meta(html, "robots") == "noindex, nofollow"
    assert _canonical(html) == "https://genemeal-seo-bot.onrender.com/"


def test_signup_is_indexable_with_complete_tags(client):
    res = client.get("/app/signup")
    assert res.status_code == 200
    html = res.text
    assert "<title>Sign up for Traction | Multi-Site SEO Audits</title>" in html
    desc = _meta(html, "description")
    assert desc and 110 <= len(desc) <= 160
    assert "Payments are not collected" in desc
    assert _meta(html, "robots") == "index, follow"
    assert _canonical(html) == f"{public_origin()}/app/signup"
    assert _prop(html, "og:title")
    assert _prop(html, "og:description")
    # Auth and plans still present
    assert "Create a free Traction account" in html
    assert "No payment is collected here" in html


def test_login_sites_and_dashboard_are_noindexed(client):
    login = client.get("/app/login")
    assert login.status_code == 200
    assert _meta(login.text, "robots") == "noindex, nofollow"
    assert _canonical(login.text) == f"{public_origin()}/app/login"
    assert _meta(login.text, "description")
    assert "Credit or Debit Card" not in login.text  # no GeneMeal checkout here

    # Log in so /app/sites and a dashboard render
    from tests.test_auth import _csrf
    token = _csrf(client, "/app/signup")
    client.post(
        "/app/signup",
        data={"email": "seo-tags@example.com", "password": "correct-horse", "csrf_token": token},
    )
    sites = client.get("/app/sites")
    assert sites.status_code == 200
    assert "<title>Your Sites — Traction SEO Audit Dashboard</title>" in sites.text
    assert _meta(sites.text, "robots") == "noindex, nofollow"
    assert _canonical(sites.text) == f"{public_origin()}/app/sites"
    assert "of 3 sites" in sites.text or "3 sites" in sites.text
    assert "No payment is collected here" in sites.text


def test_api_and_docs_send_x_robots_tag(client):
    from tests.test_console_auth import _login

    for path in ("/api/gsc", "/api/dashboard", "/docs", "/redoc", "/openapi.json"):
        res = client.get(path, follow_redirects=False)
        assert res.status_code in (401, 303), path
        if res.status_code == 401:
            assert res.headers.get("x-robots-tag") == "noindex, nofollow", path

    assert _login(client).status_code == 303
    for path in ("/api/gsc", "/api/dashboard", "/docs", "/redoc", "/openapi.json"):
        res = client.get(path)
        assert res.status_code == 200, path
        assert res.headers.get("x-robots-tag") == "noindex, nofollow", path
