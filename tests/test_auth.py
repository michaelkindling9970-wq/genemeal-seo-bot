from seo_bot.auth import reset_rate_limit_for_tests


def _csrf(client, path="/app/signup"):
    page = client.get(path)
    html = page.text
    marker = 'name="csrf_token" value="'
    assert marker in html
    return html.split(marker, 1)[1].split('"', 1)[0]


def test_signup_login_logout_roundtrip(client):
    token = _csrf(client, "/app/signup")
    r = client.post("/app/signup", data={"email": "Ada@Example.com", "password": "correct-horse", "csrf_token": token}, follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/app/sites"
    # httpOnly session cookie
    cookie = r.cookies.get("seo_session")
    assert cookie
    assert "httponly" in r.headers.get("set-cookie", "").lower()

    sites = client.get("/app/sites")
    assert sites.status_code == 200
    assert "Ada@example.com".lower() in sites.text.lower() or "ada@example.com" in sites.text

    # logout
    token = _csrf(client, "/app/sites")
    out = client.post("/app/logout", data={"csrf_token": token}, follow_redirects=False)
    assert out.status_code == 303
    guarded = client.get("/app/sites", follow_redirects=False)
    assert guarded.status_code == 303
    assert "/app/login" in guarded.headers["location"]

    # login
    token = _csrf(client, "/app/login")
    login = client.post("/app/login", data={"email": "ada@example.com", "password": "correct-horse", "csrf_token": token, "next": "/app/sites"}, follow_redirects=False)
    assert login.status_code == 303
    assert client.get("/app/sites").status_code == 200


def test_login_rejects_bad_password(client):
    token = _csrf(client, "/app/signup")
    client.post("/app/signup", data={"email": "user@example.com", "password": "correct-horse", "csrf_token": token})
    client.post("/app/logout", data={"csrf_token": _csrf(client, "/app/sites")})
    token = _csrf(client, "/app/login")
    r = client.post("/app/login", data={"email": "user@example.com", "password": "wrong-password", "csrf_token": token})
    assert r.status_code == 401
    assert "incorrect" in r.text.lower()


def test_signup_requires_csrf(client):
    r = client.post("/app/signup", data={"email": "x@example.com", "password": "correct-horse", "csrf_token": "forged"})
    assert r.status_code in (400, 403)


def test_login_rate_limited(client):
    reset_rate_limit_for_tests()
    token = _csrf(client, "/app/login")
    last = None
    for _ in range(9):
        last = client.post("/app/login", data={"email": "nobody@example.com", "password": "bad-bad-bad", "csrf_token": token})
    assert last.status_code == 429
    assert "too many" in last.text.lower()
