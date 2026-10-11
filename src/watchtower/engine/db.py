from __future__ import annotations

import fcntl
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_V1 = """
CREATE TABLE IF NOT EXISTS jobs(
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    prompt TEXT NOT NULL,
    status TEXT NOT NULL,
    error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS agent_context(
    agent_id TEXT NOT NULL,
    job_id TEXT NOT NULL,
    data TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (agent_id, job_id)
);
CREATE TABLE IF NOT EXISTS audit_log(
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    job_id TEXT,
    actor TEXT NOT NULL,
    action TEXT NOT NULL,
    detail TEXT NOT NULL,
    prev_hash TEXT NOT NULL,
    hash TEXT NOT NULL
);
CREATE TRIGGER IF NOT EXISTS audit_no_update BEFORE UPDATE ON audit_log
BEGIN SELECT RAISE(ABORT, 'audit_log is append-only'); END;
CREATE TRIGGER IF NOT EXISTS audit_no_delete BEFORE DELETE ON audit_log
BEGIN SELECT RAISE(ABORT, 'audit_log is append-only'); END;
CREATE TABLE IF NOT EXISTS budgets(
    job_id TEXT PRIMARY KEY,
    max_tokens INTEGER NOT NULL,
    max_seconds INTEGER NOT NULL,
    max_usd REAL NOT NULL,
    used_tokens INTEGER NOT NULL DEFAULT 0,
    used_seconds REAL NOT NULL DEFAULT 0,
    used_usd REAL NOT NULL DEFAULT 0
);
"""


MIGRATIONS = [
    SCHEMA_V1,
    "ALTER TABLE jobs ADD COLUMN pause_requested INTEGER NOT NULL DEFAULT 0;",
]


def connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path, timeout=10, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=10000")
    conn.execute("PRAGMA journal_mode=WAL")
    _migrate(conn, path)
    return conn


def _migrate(conn: sqlite3.Connection, path: Path) -> None:
    """Apply pending migrations; a file lock stops two processes migrating at once."""
    with open(path.with_name(path.name + ".migrate.lock"), "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            for number, sql in enumerate(MIGRATIONS[version:], start=version + 1):
                conn.executescript(sql)
                conn.execute(f"PRAGMA user_version={number}")
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def now() -> str:
    return datetime.now(timezone.utc).isoformat()
