import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

os.environ["SEO_SKIP_SCHEDULER"] = "1"
os.environ["SESSION_SECRET"] = "test-session-secret-not-for-production"
os.environ["CONTROL_TOKEN"] = "test-control-token"
os.environ["CONSOLE_USERNAME"] = "michael"

from seo_bot.auth import hash_console_password  # noqa: E402

TEST_CONSOLE_PASSWORD = "test-console-passphrase"
os.environ["CONSOLE_PASSWORD_HASH"] = hash_console_password(TEST_CONSOLE_PASSWORD, iterations=10_000)
os.environ["SEO_DB_PATH"] = str(Path(tempfile.gettempdir()) / "seo_bot_pytest.db")
os.environ["GSC_CACHE_PATH"] = str(Path(tempfile.gettempdir()) / "seo_bot_pytest_gsc.json")

# Isolate each test session DB
_db = Path(os.environ["SEO_DB_PATH"])
if _db.exists():
    _db.unlink()
cache = Path(os.environ["GSC_CACHE_PATH"])
if cache.exists():
    cache.unlink()

import pytest
from fastapi.testclient import TestClient

from seo_bot.auth import reset_rate_limit_for_tests
from seo_bot.db import init_db


@pytest.fixture
def client(tmp_path, monkeypatch):
    db = tmp_path / "test.db"
    gsc = tmp_path / "gsc.json"
    monkeypatch.setenv("SEO_DB_PATH", str(db))
    monkeypatch.setenv("GSC_CACHE_PATH", str(gsc))
    monkeypatch.setenv("SEO_SKIP_SCHEDULER", "1")
    monkeypatch.setenv("SESSION_SECRET", "test-session-secret-not-for-production")
    monkeypatch.setenv("CONTROL_TOKEN", "test-control-token")
    monkeypatch.setenv("CONSOLE_USERNAME", "michael")
    monkeypatch.setenv("CONSOLE_PASSWORD_HASH", os.environ["CONSOLE_PASSWORD_HASH"])
    # Re-bind db module paths after env change
    import seo_bot.db as dbmod
    dbmod.DB_PATH = str(db)
    dbmod.GSC_CACHE_PATH = str(gsc)
    dbmod._gsc_memory = None
    init_db()
    reset_rate_limit_for_tests()
    from app import app
    with TestClient(app) as c:
        yield c
    reset_rate_limit_for_tests()
