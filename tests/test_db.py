from watchtower.config import load_settings
from watchtower.engine.db import connect


def test_connect_creates_tables(conn):
    names = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"jobs", "agent_context", "audit_log", "budgets"} <= names


def test_connect_uses_wal(conn):
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"


def test_connect_is_idempotent(settings):
    connect(settings.db_path).close()
    connect(settings.db_path).close()


def test_load_settings_respects_env(tmp_path, monkeypatch):
    monkeypatch.setenv("WATCHTOWER_HOME", str(tmp_path / "wt"))
    s = load_settings()
    assert s.home == tmp_path / "wt"
    assert s.home.is_dir()
    assert s.cloud_enabled is False
    assert s.default_max_usd == 0.0
