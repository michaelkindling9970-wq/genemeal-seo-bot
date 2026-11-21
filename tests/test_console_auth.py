import re

from tests.conftest import TEST_CONSOLE_PASSWORD
from seo_bot.auth import CONSOLE_COOKIE_NAME, CONSOLE_REMEMBER_MAX_AGE, reset_rate_limit_for_tests


def _console_csrf(client):
    page = client.get("/login")
    html = page.text
    marker = 'name="csrf_token" value="'
    assert marker in html
    return html.split(marker, 1)[1].split('"', 1)[0]


def _cookie_header(response, name=CONSOLE_COOKIE_NAME):
    # Starlette may include multiple Set-Cookie headers; inspect the named one.
    raw = response.headers.get_list("set-cookie") if hasattr(response.headers, "get_list") else None
    if not raw:
        header = response.headers.get("set-cookie") or ""
        raw = [part.strip() for part in header.split("\n") if part.strip()] or ([header] if header else [])
    for item in raw:
        if item.lower().startswith(name.lower() + "="):
            return item
    return ""


def test_login_page_checks_remember_me_by_default(client):
    page = client.get("/login")
    assert page.status_code == 200
    assert "<title>Sign in — GeneMeal SEO Bot Console</title>" in page.text
    match = re.search(r"<input[^>]*id=\"remember\"[^>]*>", page.text)
    assert match, "Remember me checkbox missing"
    assert "checked" in match.group(0)
    assert 'name="remember"' in match.group(0)


def test_public_routes_remain_open(client):
    assert client.get("/healthz").status_code == 200
    assert client.get("/robots.txt").status_code == 200
    assert client.get("/sitemap.xml").status_code == 200


def test_dashboard_requires_login(client):
    home = client.get("/", follow_redirects=False)
    assert home.status_code == 303
    assert "/login" in home.headers["location"]

    dash = client.get("/api/dashboard", follow_redirects=False)
    assert dash.status_code == 401

    events = client.get("/api/events", follow_redirects=False)
    assert events.status_code == 401

    static_index = client.get("/static/index.html", follow_redirects=False)
    assert static_index.status_code in (303, 401)


def test_login_not_configured_fails_closed(client, monkeypatch):
    monkeypatch.delenv("CONSOLE_PASSWORD_HASH", raising=False)
    page = client.get("/login")
    assert page.status_code == 200
    assert "login not configured" in page.text
    assert "console-login-form" not in page.text

    home = client.get("/", follow_redirects=False)
    assert home.status_code == 303
    dash = client.get("/api/dashboard", follow_redirects=False)
    assert dash.status_code == 401


def test_login_rejects_bad_password_and_requires_csrf(client):
    token = _console_csrf(client)
    bad = client.post(
        "/login",
        data={"username": "michael", "password": "wrong-password", "csrf_token": token, "remember": "1"},
    )
    assert bad.status_code == 401
    assert "incorrect" in bad.text.lower()

    forged = client.post(
        "/login",
        data={"username": "michael", "password": TEST_CONSOLE_PASSWORD, "csrf_token": "forged"},
        follow_redirects=False,
    )
    assert forged.status_code == 403


def _login(client, *, remember=True, username="michael", password=TEST_CONSOLE_PASSWORD):
    token = _console_csrf(client)
    data = {
        "username": username,
        "password": password,
        "csrf_token": token,
        "next": "/",
    }
    if remember:
        data["remember"] = "1"
    return client.post("/login", data=data, follow_redirects=False)


def test_remember_me_sets_persistent_cookie(client):
    login = _login(client, remember=True)
    assert login.status_code == 303
    assert login.headers["location"] == "/"
    header = _cookie_header(login).lower()
    assert header
    assert "httponly" in header
    assert "samesite=lax" in header
    assert f"max-age={CONSOLE_REMEMBER_MAX_AGE}" in header

    home = client.get("/")
    assert home.status_code == 200
    assert "Live Organic Growth" in home.text
    assert "Log out" in home.text

    dash = client.get("/api/dashboard")
    assert dash.status_code == 200
    body = dash.json()
    assert body["session_user"] == "michael"
    assert body["auth_required_for_controls"] is False


def test_remember_me_unchecked_is_session_cookie(client):
    login = _login(client, remember=False)
    assert login.status_code == 303
    header = _cookie_header(login).lower()
    assert header
    assert "httponly" in header
    assert "samesite=lax" in header
    assert "max-age=" not in header
    assert "expires=" not in header

    dash = client.get("/api/dashboard")
    assert dash.status_code == 200
    assert dash.json()["session_user"] == "michael"


def test_logout_clears_session(client):
    assert _login(client).status_code == 303
    out = client.get("/logout", follow_redirects=False)
    assert out.status_code == 303
    assert "/login" in out.headers["location"]
    assert client.get("/api/dashboard", follow_redirects=False).status_code == 401
    assert client.get("/", follow_redirects=False).status_code == 303


def test_signed_in_session_can_use_controls_without_token(client):
    assert _login(client).status_code == 303
    verify = client.post("/api/auth/verify")
    assert verify.status_code == 200
    assert verify.json()["ok"] is True
    missing = client.post("/api/drafts/999999/status", json={"status": "approved"})
    assert missing.status_code == 404


def test_control_token_still_works_without_session(client):
    denied = client.post("/api/gsc/ingest", json={
        "site": "https://genemeal.onrender.com/",
        "start_date": "2026-11-01",
        "end_date": "2026-11-20",
        "totals": {},
    })
    assert denied.status_code == 401

    missing_body = client.post(
        "/api/gsc/ingest",
        headers={"X-Control-Token": "test-control-token"},
    )
    # Valid token is accepted past the auth gate; a missing body is not an auth failure.
    assert missing_body.status_code != 401


def test_console_login_rate_limited(client):
    reset_rate_limit_for_tests()
    token = _console_csrf(client)
    last = None
    for _ in range(6):
        last = client.post(
            "/login",
            data={"username": "michael", "password": "bad-bad-bad", "csrf_token": token, "remember": "1"},
        )
    assert last.status_code == 429
    assert "too many" in last.text.lower()
