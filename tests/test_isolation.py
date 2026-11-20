def _csrf(client, path="/app/signup"):
    page = client.get(path)
    return page.text.split('name="csrf_token" value="', 1)[1].split('"', 1)[0]


def _signup(client, email):
    token = _csrf(client, "/app/signup")
    client.post("/app/signup", data={"email": email, "password": "correct-horse", "csrf_token": token})


def test_users_cannot_see_each_others_sites(client):
    _signup(client, "alice@example.com")
    token = _csrf(client, "/app/sites")
    added = client.post("/app/sites", data={"url": "https://example.com", "csrf_token": token}, follow_redirects=False)
    assert added.status_code == 303

    sites = client.get("/app/sites")
    assert 'class="site-host"' in sites.text
    import re
    ids = re.findall(r'href="/app/sites/(\d+)"', sites.text)
    assert ids
    site_id = ids[0]
    alice_dash = client.get(f"/app/sites/{site_id}")
    assert alice_dash.status_code == 200
    assert "example.com" in alice_dash.text
    api = client.get(f"/api/app/sites/{site_id}")
    assert api.status_code == 200
    assert api.json()["site"]["host"] == "example.com"

    client.post("/app/logout", data={"csrf_token": _csrf(client, "/app/sites")})

    _signup(client, "bob@example.com")
    bob_list = client.get("/app/sites")
    assert bob_list.status_code == 200
    assert 'class="site-host"' not in bob_list.text
    bob_html = client.get(f"/app/sites/{site_id}")
    assert bob_html.status_code == 404
    assert "Site not found" in bob_html.text
    bob_api = client.get(f"/api/app/sites/{site_id}")
    assert bob_api.status_code == 404

    token = _csrf(client, "/app/sites")
    client.post(f"/app/sites/{site_id}/delete", data={"csrf_token": token})
    client.post("/app/logout", data={"csrf_token": _csrf(client, "/app/sites")})

    token = _csrf(client, "/app/login")
    client.post("/app/login", data={"email": "alice@example.com", "password": "correct-horse", "csrf_token": token, "next": "/app/sites"})
    assert 'class="site-host"' in client.get("/app/sites").text
    assert client.get(f"/api/app/sites/{site_id}").status_code == 200


def test_delete_account_removes_sites(client):
    _signup(client, "gone@example.com")
    token = _csrf(client, "/app/sites")
    client.post("/app/sites", data={"url": "https://example.com", "csrf_token": token})
    token = _csrf(client, "/app/sites")
    resp = client.post("/app/account/delete", data={"csrf_token": token}, follow_redirects=False)
    assert resp.status_code == 303
    # Cannot access sites after delete
    assert client.get("/app/sites", follow_redirects=False).status_code == 303
