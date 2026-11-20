import pytest

from seo_bot.ssrf import UnsafeURLError, assert_public_http_url, is_public_http_url


@pytest.mark.parametrize("url", [
    "http://127.0.0.1/",
    "https://127.0.0.1/",
    "http://localhost/",
    "http://localhost.localdomain/",
    "http://10.0.0.1/",
    "http://192.168.1.20/admin",
    "http://172.16.0.5/",
    "http://169.254.169.254/latest/meta-data",
    "http://[::1]/",
    "http://0.0.0.0/",
    "https://metadata.google.internal/",
    "http://something.render.internal/metrics",
    "http://app.internal/",
    "ftp://example.com/",
    "file:///etc/passwd",
    "http://example.com@127.0.0.1/",
    "http://127.0.0.1:80/",
    "https://example.com:8443/",
    "http://user:pass@example.com/",
])
def test_blocks_unsafe_urls(url):
    with pytest.raises(UnsafeURLError):
        assert_public_http_url(url)
    assert is_public_http_url(url) is False


def test_allows_public_example_com():
    cleaned = assert_public_http_url("https://example.com")
    assert cleaned.startswith("https://example.com")


def test_add_site_form_rejects_localhost(client):
    page = client.get("/app/signup")
    token = page.text.split('name="csrf_token" value="', 1)[1].split('"', 1)[0]
    client.post("/app/signup", data={"email": "ssrf@example.com", "password": "correct-horse", "csrf_token": token})
    token = client.get("/app/sites").text.split('name="csrf_token" value="', 1)[1].split('"', 1)[0]
    resp = client.post("/app/sites", data={"url": "http://127.0.0.1/", "csrf_token": token}, follow_redirects=True)
    assert resp.status_code == 200
    assert "example.com" not in resp.text or "127.0.0.1" not in resp.text
    assert "not allowed" in resp.text.lower() or "not a public" in resp.text.lower() or "localhost" in resp.text.lower() or "error" in resp.text.lower()
    # Confirm it was not stored
    assert "127.0.0.1" not in client.get("/app/sites").text
