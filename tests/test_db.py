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
import sqlite3


def test_migrates_phase_1a_database(tmp_path):
    path = tmp_path / "old.db"
    old = sqlite3.connect(path)
    old.executescript(
        "CREATE TABLE jobs(id TEXT PRIMARY KEY, user_id TEXT NOT NULL, workspace_id TEXT NOT NULL,"
        " prompt TEXT NOT NULL, status TEXT NOT NULL, error TEXT, created_at TEXT NOT NULL,"
        " updated_at TEXT NOT NULL);"
        "INSERT INTO jobs VALUES ('j1','owner','default','keep me','done',NULL,'t','t');"
    )
    old.close()
    conn = connect(path)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 5
    row = conn.execute("SELECT prompt, pause_requested FROM jobs WHERE id='j1'").fetchone()
    assert tuple(row) == ("keep me", 0)
    conn.close()


def test_migration_runs_once(settings):
    connect(settings.db_path).close()
    conn = connect(settings.db_path)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 5
    conn.close()


def test_min_free_ram_env_override(tmp_path, monkeypatch):
    monkeypatch.setenv("WATCHTOWER_HOME", str(tmp_path))
    monkeypatch.setenv("WATCHTOWER_MIN_FREE_RAM_PCT", "99")
    assert load_settings().min_free_ram_pct == 99


def test_failed_migration_rolls_back_atomically(tmp_path, monkeypatch):
    from watchtower.engine import db
    path = tmp_path / "m.db"
    monkeypatch.setattr(db, "MIGRATIONS", [db.SCHEMA_V1, "ALTER TABLE jobs ADD COLUMN x INTEGER; SELECT * FROM nope;"])
    try:
        connect(path)
    except sqlite3.OperationalError:
        pass
    raw = sqlite3.connect(path)
    assert raw.execute("PRAGMA user_version").fetchone()[0] == 1
    assert "x" not in [r[1] for r in raw.execute("PRAGMA table_info(jobs)")]
    raw.close()


def test_knowledge_tables_exist(conn):
    names = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master")}
    assert {"knowledge_docs", "knowledge_fts"} <= names


def test_sandbox_image_env_override(tmp_path, monkeypatch):
    monkeypatch.setenv("WATCHTOWER_HOME", str(tmp_path))
    monkeypatch.setenv("WATCHTOWER_SANDBOX_IMAGE", "python:latest")
    assert load_settings().sandbox_image == "python:latest"


def test_approvals_table_exists(conn):
    names = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master")}
    assert "approvals" in names


def test_online_by_default_and_offline_env(tmp_path, monkeypatch):
    monkeypatch.setenv("WATCHTOWER_HOME", str(tmp_path))
    monkeypatch.delenv("WATCHTOWER_OFFLINE", raising=False)
    assert load_settings().online is True
    monkeypatch.setenv("WATCHTOWER_OFFLINE", "1")
    assert load_settings().online is False


def test_tower_jobs_get_a_larger_token_budget(tmp_path, monkeypatch):
    monkeypatch.setenv("WATCHTOWER_HOME", str(tmp_path))
    s = load_settings()
    assert s.tower_max_tokens == 200_000 and s.tower_max_tokens > s.default_max_tokens
