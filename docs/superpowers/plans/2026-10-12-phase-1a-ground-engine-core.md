# Phase 1a — Ground Engine Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A local `watchtower` CLI that sends a prompt through the Engine's Model Socket to a local Ollama model, enforces a budget, writes a tamper-evident audit log, saves agent context, and reports job status — all at $0.

**Architecture:** One Python package (`src/watchtower`). A shared SQLite database (WAL mode) under `~/.watchtower` holds jobs, agent context, budgets and the append-only audit log. Each Engine module is a small class taking a `sqlite3.Connection` (or injected callables) so it is testable without Ollama or the Keychain. The Typer CLI wires modules together.

**Tech Stack:** Python 3.12 (via uv), LiteLLM, Ollama, SQLite (stdlib), keyring (macOS Keychain), httpx, Typer, pytest.

**Spec:** `docs/superpowers/specs/2026-10-12-watchtower-design.md` (§4 Ground Engine, §9 Security, §10 Error handling, §12 phase 1a)

## Global Constraints

- Cost: $0 by default. Cloud models disabled unless `cloud_enabled=True`; default `max_usd = 0.0`.
- Hardware: Apple M2, 8 GB RAM — only one local Ollama model loaded at a time.
- Default tiers: `small = ollama/llama3.2:3b`, `work = ollama/qwen2.5-coder:3b`, `review = ollama/llama3.2:3b` (review family differs from work).
- Data home: `$WATCHTOWER_HOME`, default `~/.watchtower`.
- Every row is scoped by `user_id` + `workspace_id` (defaults `owner` / `default`) for future multi-user.
- Audit log is append-only and hash-chained.
- Secrets live only in the macOS Keychain (service `watchtower`); never printed or logged.
- Files under 500 lines. Python `>=3.12`.

## Review Focus

1. **Ollama not running or model not pulled** → job marked `failed`, audit entry written, one-line actionable error with `ollama pull …`, exit code 1, no traceback. (Task 7, Task 8)
2. **Budget exceeded** → hard stop, job `failed` with reason, exit 1. (Task 5, Task 8)
3. **Audit tampering** → SQL `UPDATE`/`DELETE` on `audit_log` rejected; `verify()` detects a broken chain. (Task 4)
4. **Secret leakage** → a `SecretHandle` passed into audit detail or printed shows `<secret:name>`, never the value. (Task 4, Task 6)
5. **Empty / whitespace prompt** → rejected at the CLI boundary with exit 2 before any job is created. (Task 2, Task 8)

---

## File Structure

```
pyproject.toml                         # package, deps, entry point, pytest config
src/watchtower/__init__.py
src/watchtower/config.py               # Settings + load_settings()
src/watchtower/engine/__init__.py
src/watchtower/engine/db.py            # connect(), schema, now()
src/watchtower/engine/jobs.py          # Job, JobStore
src/watchtower/engine/memory.py        # ContextStore (agent context save/restore)
src/watchtower/engine/governor/__init__.py
src/watchtower/engine/governor/audit.py    # AuditLog (append-only, hash chain)
src/watchtower/engine/governor/budget.py   # Budget, BudgetExceeded
src/watchtower/engine/governor/secrets.py  # SecretStore, SecretHandle
src/watchtower/engine/model_socket.py  # ModelSocket, Reply, errors
src/watchtower/cli.py                  # Typer app: run/status/logs/budget
tests/conftest.py
tests/test_db.py tests/test_jobs.py tests/test_memory.py tests/test_audit.py
tests/test_budget.py tests/test_secrets.py tests/test_model_socket.py tests/test_cli.py
```

---

### Task 1: Project scaffold, settings, database

**Files:**
- Create: `pyproject.toml`, `src/watchtower/__init__.py`, `src/watchtower/config.py`, `src/watchtower/engine/__init__.py`, `src/watchtower/engine/db.py`, `tests/conftest.py`, `tests/test_db.py`

**Interfaces:**
- Produces: `Settings` (fields `home: Path`, `tiers: dict[str, str]`, `ollama_url: str`, `cloud_enabled: bool`, `default_max_tokens: int`, `default_max_seconds: int`, `default_max_usd: float`; property `db_path`), `load_settings() -> Settings`, `connect(path: Path) -> sqlite3.Connection`, `now() -> str`. Fixtures `conn`, `settings`; helper `fake_response(text, pt, ct)`.

- [ ] **Step 1: Install Python 3.12 and create pyproject**

Run: `uv python install 3.12`

Create `pyproject.toml`:
```toml
[project]
name = "watchtower"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "litellm>=1.50",
    "typer>=0.12",
    "keyring>=25",
    "httpx>=0.27",
]

[project.scripts]
watchtower = "watchtower.cli:app"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/watchtower"]

[dependency-groups]
dev = ["pytest>=8"]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["src"]
```

Create empty `src/watchtower/__init__.py` and `src/watchtower/engine/__init__.py`.

Run: `uv sync --python 3.12`
Expected: `.venv` created, dependencies installed.

Append to `.gitignore`:
```
.venv/
__pycache__/
*.db
```

- [ ] **Step 2: Write the failing test**

`tests/conftest.py`:
```python
from types import SimpleNamespace

import pytest

from watchtower.config import Settings, DEFAULT_TIERS
from watchtower.engine.db import connect


@pytest.fixture
def settings(tmp_path):
    return Settings(home=tmp_path, tiers=dict(DEFAULT_TIERS))


@pytest.fixture
def conn(settings):
    c = connect(settings.db_path)
    yield c
    c.close()


def fake_response(text="hi", pt=3, ct=2):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=text))],
        usage=SimpleNamespace(prompt_tokens=pt, completion_tokens=ct),
    )
```

`tests/test_db.py`:
```python
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
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/test_db.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'watchtower.config'`

- [ ] **Step 4: Implement**

`src/watchtower/config.py`:
```python
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

DEFAULT_TIERS = {
    "small": "ollama/llama3.2:3b",
    "work": "ollama/qwen2.5-coder:3b",
    "review": "ollama/llama3.2:3b",
}


@dataclass(frozen=True)
class Settings:
    home: Path
    tiers: dict[str, str]
    ollama_url: str = "http://localhost:11434"
    cloud_enabled: bool = False
    default_max_tokens: int = 50_000
    default_max_seconds: int = 3600
    default_max_usd: float = 0.0

    @property
    def db_path(self) -> Path:
        return self.home / "watchtower.db"


def load_settings() -> Settings:
    home = Path(os.environ.get("WATCHTOWER_HOME", Path.home() / ".watchtower"))
    home.mkdir(parents=True, exist_ok=True)
    return Settings(home=home, tiers=dict(DEFAULT_TIERS))
```

`src/watchtower/engine/db.py`:
```python
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
PRAGMA journal_mode=WAL;
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


def connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path, timeout=10, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=10000")
    conn.executescript(SCHEMA)
    return conn


def now() -> str:
    return datetime.now(timezone.utc).isoformat()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_db.py -v`
Expected: 4 passed

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml uv.lock .gitignore src tests
git commit -m "feat(engine): scaffold package, settings, sqlite schema"
```

---

### Task 2: Job store

**Files:**
- Create: `src/watchtower/engine/jobs.py`, `tests/test_jobs.py`

**Interfaces:**
- Consumes: `connect`, `now` (Task 1).
- Produces: `Job` dataclass (`id, user_id, workspace_id, prompt, status, error, created_at, updated_at`); `JobStore(conn, user_id="owner", workspace_id="default")` with `create(prompt: str) -> Job`, `get(job_id: str) -> Job | None`, `set_status(job_id: str, status: str, error: str | None = None) -> None`, `list(limit: int = 20) -> list[Job]`. Statuses: `queued, running, done, failed`.

- [ ] **Step 1: Write the failing test**

`tests/test_jobs.py`:
```python
import pytest

from watchtower.engine.jobs import JobStore


def test_create_and_get(conn):
    store = JobStore(conn)
    job = store.create("  build a todo app  ")
    assert job.prompt == "build a todo app"
    assert job.status == "queued"
    assert store.get(job.id) == job


@pytest.mark.parametrize("bad", ["", "   ", "\n\t"])
def test_create_rejects_empty_prompt(conn, bad):
    with pytest.raises(ValueError, match="empty"):
        JobStore(conn).create(bad)


def test_set_status_and_error(conn):
    store = JobStore(conn)
    job = store.create("x")
    store.set_status(job.id, "failed", "boom")
    got = store.get(job.id)
    assert got.status == "failed" and got.error == "boom"


def test_set_status_rejects_unknown_status(conn):
    store = JobStore(conn)
    job = store.create("x")
    with pytest.raises(ValueError):
        store.set_status(job.id, "exploded")


def test_set_status_missing_job(conn):
    with pytest.raises(KeyError):
        JobStore(conn).set_status("nope", "done")


def test_list_newest_first_and_scoped(conn):
    mine = JobStore(conn)
    other = JobStore(conn, user_id="someone-else")
    a = mine.create("a")
    b = mine.create("b")
    other.create("c")
    assert [j.id for j in mine.list()] == [b.id, a.id]


def test_unicode_prompt_roundtrip(conn):
    store = JobStore(conn)
    job = store.create("बनाओ 🗼 app")
    assert store.get(job.id).prompt == "बनाओ 🗼 app"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_jobs.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'watchtower.engine.jobs'`

- [ ] **Step 3: Implement**

`src/watchtower/engine/jobs.py`:
```python
from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass

from watchtower.engine.db import now

STATUSES = {"queued", "running", "done", "failed"}


@dataclass(frozen=True)
class Job:
    id: str
    user_id: str
    workspace_id: str
    prompt: str
    status: str
    error: str | None
    created_at: str
    updated_at: str


class JobStore:
    def __init__(self, conn: sqlite3.Connection, user_id: str = "owner", workspace_id: str = "default"):
        self._conn = conn
        self._user = user_id
        self._ws = workspace_id

    def create(self, prompt: str) -> Job:
        prompt = prompt.strip()
        if not prompt:
            raise ValueError("prompt must not be empty")
        ts = now()
        job_id = uuid.uuid4().hex[:12]
        self._conn.execute(
            "INSERT INTO jobs VALUES (?,?,?,?,?,?,?,?)",
            (job_id, self._user, self._ws, prompt, "queued", None, ts, ts),
        )
        return self.get(job_id)

    def get(self, job_id: str) -> Job | None:
        row = self._conn.execute(
            "SELECT * FROM jobs WHERE id=? AND user_id=? AND workspace_id=?",
            (job_id, self._user, self._ws),
        ).fetchone()
        return Job(**dict(row)) if row else None

    def set_status(self, job_id: str, status: str, error: str | None = None) -> None:
        if status not in STATUSES:
            raise ValueError(f"unknown status {status!r}")
        cur = self._conn.execute(
            "UPDATE jobs SET status=?, error=?, updated_at=? WHERE id=? AND user_id=? AND workspace_id=?",
            (status, error, now(), job_id, self._user, self._ws),
        )
        if cur.rowcount == 0:
            raise KeyError(job_id)

    def list(self, limit: int = 20) -> list[Job]:
        rows = self._conn.execute(
            "SELECT * FROM jobs WHERE user_id=? AND workspace_id=? ORDER BY rowid DESC LIMIT ?",
            (self._user, self._ws, limit),
        ).fetchall()
        return [Job(**dict(r)) for r in rows]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_jobs.py -v`
Expected: all passed

- [ ] **Step 5: Commit**

```bash
git add src/watchtower/engine/jobs.py tests/test_jobs.py
git commit -m "feat(engine): add scoped job store"
```

---

### Task 3: Memory — agent context store

**Files:**
- Create: `src/watchtower/engine/memory.py`, `tests/test_memory.py`

**Interfaces:**
- Consumes: `now` (Task 1).
- Produces: `ContextStore(conn)` with `save(agent_id: str, job_id: str, data: dict) -> None` (upsert) and `load(agent_id: str, job_id: str) -> dict | None`.

- [ ] **Step 1: Write the failing test**

`tests/test_memory.py`:
```python
from watchtower.engine.memory import ContextStore


def test_load_missing_returns_none(conn):
    assert ContextStore(conn).load("f1.worker", "job1") is None


def test_save_then_load(conn):
    store = ContextStore(conn)
    data = {"messages": [{"role": "user", "content": "hi 🗼"}], "step": 2}
    store.save("f1.worker", "job1", data)
    assert store.load("f1.worker", "job1") == data


def test_save_overwrites(conn):
    store = ContextStore(conn)
    store.save("a", "j", {"v": 1})
    store.save("a", "j", {"v": 2})
    assert store.load("a", "j") == {"v": 2}


def test_contexts_are_isolated_per_agent_and_job(conn):
    store = ContextStore(conn)
    store.save("a", "j1", {"v": 1})
    store.save("b", "j1", {"v": 2})
    store.save("a", "j2", {"v": 3})
    assert store.load("a", "j1") == {"v": 1}
    assert store.load("b", "j1") == {"v": 2}
    assert store.load("a", "j2") == {"v": 3}


def test_context_survives_reconnect(settings, conn):
    from watchtower.engine.db import connect
    ContextStore(conn).save("a", "j", {"keep": True})
    fresh = connect(settings.db_path)
    assert ContextStore(fresh).load("a", "j") == {"keep": True}
    fresh.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_memory.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'watchtower.engine.memory'`

- [ ] **Step 3: Implement**

`src/watchtower/engine/memory.py`:
```python
from __future__ import annotations

import json
import sqlite3

from watchtower.engine.db import now


class ContextStore:
    """Saves an agent's working context when it goes idle, restores it when woken."""

    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def save(self, agent_id: str, job_id: str, data: dict) -> None:
        self._conn.execute(
            "INSERT INTO agent_context VALUES (?,?,?,?) "
            "ON CONFLICT(agent_id, job_id) DO UPDATE SET data=excluded.data, updated_at=excluded.updated_at",
            (agent_id, job_id, json.dumps(data, ensure_ascii=False), now()),
        )

    def load(self, agent_id: str, job_id: str) -> dict | None:
        row = self._conn.execute(
            "SELECT data FROM agent_context WHERE agent_id=? AND job_id=?", (agent_id, job_id)
        ).fetchone()
        return json.loads(row["data"]) if row else None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_memory.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add src/watchtower/engine/memory.py tests/test_memory.py
git commit -m "feat(engine): add agent context memory store"
```

---

### Task 4: Governor — append-only audit log

**Files:**
- Create: `src/watchtower/engine/governor/__init__.py` (empty), `src/watchtower/engine/governor/audit.py`, `tests/test_audit.py`

**Interfaces:**
- Consumes: `now` (Task 1).
- Produces: `AuditEntry` dataclass (`seq, ts, job_id, actor, action, detail: dict, prev_hash, hash`); `AuditLog(conn)` with `append(actor: str, action: str, detail: dict, job_id: str | None = None) -> int`, `entries(job_id: str | None = None, limit: int = 100) -> list[AuditEntry]` (oldest first), `verify() -> bool`. Non-JSON values in `detail` are serialized with `str()` (so `SecretHandle` renders as `<secret:name>`).

- [ ] **Step 1: Write the failing test**

`tests/test_audit.py`:
```python
import sqlite3

import pytest

from watchtower.engine.governor.audit import AuditLog


class FakeHandle:
    def __str__(self):
        return "<secret:api>"


def test_append_and_read_in_order(conn):
    log = AuditLog(conn)
    log.append("owner", "job_created", {"prompt": "x"}, job_id="j1")
    log.append("engine", "job_done", {}, job_id="j1")
    log.append("engine", "other", {}, job_id="j2")
    entries = log.entries(job_id="j1")
    assert [e.action for e in entries] == ["job_created", "job_done"]
    assert entries[0].detail == {"prompt": "x"}


def test_chain_verifies(conn):
    log = AuditLog(conn)
    for i in range(5):
        log.append("a", "act", {"i": i})
    assert log.verify() is True


def test_update_is_rejected(conn):
    AuditLog(conn).append("a", "act", {})
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        conn.execute("UPDATE audit_log SET action='forged'")


def test_delete_is_rejected(conn):
    AuditLog(conn).append("a", "act", {})
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        conn.execute("DELETE FROM audit_log")


def test_verify_detects_tampering(conn):
    log = AuditLog(conn)
    log.append("a", "act", {"n": 1})
    log.append("a", "act", {"n": 2})
    conn.execute("DROP TRIGGER audit_no_update")
    conn.execute("UPDATE audit_log SET detail='{\"n\": 99}' WHERE seq=1")
    assert log.verify() is False


def test_secret_handle_is_never_stored_raw(conn):
    log = AuditLog(conn)
    log.append("a", "used_secret", {"key": FakeHandle()})
    raw = conn.execute("SELECT detail FROM audit_log").fetchone()[0]
    assert "<secret:api>" in raw
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_audit.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement**

`src/watchtower/engine/governor/audit.py`:
```python
from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass

from watchtower.engine.db import now

GENESIS = "0" * 64


@dataclass(frozen=True)
class AuditEntry:
    seq: int
    ts: str
    job_id: str | None
    actor: str
    action: str
    detail: dict
    prev_hash: str
    hash: str


def _digest(prev: str, ts: str, job_id: str | None, actor: str, action: str, detail: str) -> str:
    payload = json.dumps([prev, ts, job_id, actor, action, detail], ensure_ascii=False)
    return hashlib.sha256(payload.encode()).hexdigest()


class AuditLog:
    """Append-only, hash-chained record of every action in the tower."""

    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def append(self, actor: str, action: str, detail: dict, job_id: str | None = None) -> int:
        detail_json = json.dumps(detail, sort_keys=True, ensure_ascii=False, default=str)
        ts = now()
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            row = self._conn.execute("SELECT hash FROM audit_log ORDER BY seq DESC LIMIT 1").fetchone()
            prev = row["hash"] if row else GENESIS
            h = _digest(prev, ts, job_id, actor, action, detail_json)
            cur = self._conn.execute(
                "INSERT INTO audit_log(ts, job_id, actor, action, detail, prev_hash, hash) VALUES (?,?,?,?,?,?,?)",
                (ts, job_id, actor, action, detail_json, prev, h),
            )
            self._conn.execute("COMMIT")
        except BaseException:
            self._conn.execute("ROLLBACK")
            raise
        return cur.lastrowid

    def entries(self, job_id: str | None = None, limit: int = 100) -> list[AuditEntry]:
        if job_id is None:
            rows = self._conn.execute(
                "SELECT * FROM (SELECT * FROM audit_log ORDER BY seq DESC LIMIT ?) ORDER BY seq", (limit,)
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM (SELECT * FROM audit_log WHERE job_id=? ORDER BY seq DESC LIMIT ?) ORDER BY seq",
                (job_id, limit),
            ).fetchall()
        return [AuditEntry(**{**dict(r), "detail": json.loads(r["detail"])}) for r in rows]

    def verify(self) -> bool:
        prev = GENESIS
        for r in self._conn.execute("SELECT * FROM audit_log ORDER BY seq"):
            if r["prev_hash"] != prev:
                return False
            if _digest(prev, r["ts"], r["job_id"], r["actor"], r["action"], r["detail"]) != r["hash"]:
                return False
            prev = r["hash"]
        return True
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_audit.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add src/watchtower/engine/governor tests/test_audit.py
git commit -m "feat(governor): add append-only hash-chained audit log"
```

---

### Task 5: Governor — budgets

**Files:**
- Create: `src/watchtower/engine/governor/budget.py`, `tests/test_budget.py`

**Interfaces:**
- Produces: `BudgetExceeded(Exception)`; `Budget(conn)` with `open(job_id: str, max_tokens: int, max_seconds: int, max_usd: float) -> None`, `charge(job_id: str, tokens: int = 0, seconds: float = 0.0, usd: float = 0.0) -> None` (records, then raises `BudgetExceeded` if any limit is exceeded), `check(job_id: str) -> None` (raises if already exceeded), `usage(job_id: str) -> dict` with keys `used_tokens, max_tokens, used_seconds, max_seconds, used_usd, max_usd`. Unknown job → `KeyError`.

- [ ] **Step 1: Write the failing test**

`tests/test_budget.py`:
```python
import pytest

from watchtower.engine.governor.budget import Budget, BudgetExceeded


def test_charge_within_limits(conn):
    b = Budget(conn)
    b.open("j", max_tokens=100, max_seconds=60, max_usd=0.0)
    b.charge("j", tokens=40, seconds=1.5)
    u = b.usage("j")
    assert u["used_tokens"] == 40 and u["used_seconds"] == 1.5 and u["max_tokens"] == 100
    b.check("j")


def test_token_limit_exceeded_raises_and_records(conn):
    b = Budget(conn)
    b.open("j", max_tokens=10, max_seconds=60, max_usd=0.0)
    with pytest.raises(BudgetExceeded, match="tokens"):
        b.charge("j", tokens=11)
    assert b.usage("j")["used_tokens"] == 11
    with pytest.raises(BudgetExceeded):
        b.check("j")


def test_zero_usd_budget_blocks_any_spend(conn):
    b = Budget(conn)
    b.open("j", max_tokens=100, max_seconds=60, max_usd=0.0)
    with pytest.raises(BudgetExceeded, match="usd"):
        b.charge("j", usd=0.0001)


def test_seconds_limit(conn):
    b = Budget(conn)
    b.open("j", max_tokens=100, max_seconds=5, max_usd=0.0)
    with pytest.raises(BudgetExceeded, match="seconds"):
        b.charge("j", seconds=6)


def test_unknown_job(conn):
    with pytest.raises(KeyError):
        Budget(conn).usage("missing")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_budget.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement**

`src/watchtower/engine/governor/budget.py`:
```python
from __future__ import annotations

import sqlite3


class BudgetExceeded(Exception):
    pass


class Budget:
    """Per-job hard limits on tokens, wall-clock seconds and dollars."""

    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def open(self, job_id: str, max_tokens: int, max_seconds: int, max_usd: float) -> None:
        self._conn.execute(
            "INSERT INTO budgets(job_id, max_tokens, max_seconds, max_usd) VALUES (?,?,?,?)",
            (job_id, max_tokens, max_seconds, max_usd),
        )

    def usage(self, job_id: str) -> dict:
        row = self._conn.execute("SELECT * FROM budgets WHERE job_id=?", (job_id,)).fetchone()
        if row is None:
            raise KeyError(job_id)
        return {k: row[k] for k in row.keys() if k != "job_id"}

    def charge(self, job_id: str, tokens: int = 0, seconds: float = 0.0, usd: float = 0.0) -> None:
        cur = self._conn.execute(
            "UPDATE budgets SET used_tokens=used_tokens+?, used_seconds=used_seconds+?, used_usd=used_usd+? "
            "WHERE job_id=?",
            (tokens, seconds, usd, job_id),
        )
        if cur.rowcount == 0:
            raise KeyError(job_id)
        self.check(job_id)

    def check(self, job_id: str) -> None:
        u = self.usage(job_id)
        for name in ("tokens", "seconds", "usd"):
            if u[f"used_{name}"] > u[f"max_{name}"]:
                raise BudgetExceeded(
                    f"budget exceeded: {name} used {u[f'used_{name}']} > max {u[f'max_{name}']}"
                )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_budget.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add src/watchtower/engine/governor/budget.py tests/test_budget.py
git commit -m "feat(governor): add per-job budgets with hard stop"
```

---

### Task 6: Governor — Keychain secrets

**Files:**
- Create: `src/watchtower/engine/governor/secrets.py`, `tests/test_secrets.py`

**Interfaces:**
- Produces: `SERVICE = "watchtower"`; `SecretHandle` (`name` attr, `reveal() -> str`, `str()`/`repr()` → `<secret:name>`); `SecretStore(backend=None)` (default backend = `keyring` module; backend needs `get_password(service, name)`, `set_password(service, name, value)`, `delete_password(service, name)`) with `set(name, value) -> None`, `handle(name) -> SecretHandle` (`KeyError` if missing), `delete(name) -> None`.

- [ ] **Step 1: Write the failing test**

`tests/test_secrets.py`:
```python
import pytest

from watchtower.engine.governor.secrets import SERVICE, SecretStore


class MemoryBackend:
    def __init__(self):
        self.data = {}

    def get_password(self, service, name):
        return self.data.get((service, name))

    def set_password(self, service, name, value):
        self.data[(service, name)] = value

    def delete_password(self, service, name):
        self.data.pop((service, name), None)


def test_set_and_reveal():
    backend = MemoryBackend()
    store = SecretStore(backend)
    store.set("anthropic", "sk-123")
    assert backend.data[(SERVICE, "anthropic")] == "sk-123"
    assert store.handle("anthropic").reveal() == "sk-123"


def test_handle_never_shows_value():
    store = SecretStore(MemoryBackend())
    store.set("anthropic", "sk-123")
    h = store.handle("anthropic")
    assert "sk-123" not in str(h)
    assert "sk-123" not in repr(h)
    assert f"{h}" == "<secret:anthropic>"


def test_missing_secret():
    with pytest.raises(KeyError):
        SecretStore(MemoryBackend()).handle("nope")


@pytest.mark.parametrize("name,value", [("", "v"), ("n", ""), ("  ", "v")])
def test_rejects_blank(name, value):
    with pytest.raises(ValueError):
        SecretStore(MemoryBackend()).set(name, value)


def test_delete():
    store = SecretStore(MemoryBackend())
    store.set("x", "y")
    store.delete("x")
    with pytest.raises(KeyError):
        store.handle("x")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_secrets.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement**

`src/watchtower/engine/governor/secrets.py`:
```python
from __future__ import annotations

SERVICE = "watchtower"


class SecretHandle:
    """A reference to a Keychain secret. Printing or logging it never shows the value."""

    def __init__(self, name: str, store: "SecretStore"):
        self.name = name
        self._store = store

    def reveal(self) -> str:
        return self._store._get(self.name)

    def __str__(self) -> str:
        return f"<secret:{self.name}>"

    __repr__ = __str__


class SecretStore:
    def __init__(self, backend=None):
        if backend is None:
            import keyring as backend
        self._b = backend

    def set(self, name: str, value: str) -> None:
        if not name.strip() or not value:
            raise ValueError("secret name and value must not be blank")
        self._b.set_password(SERVICE, name, value)

    def handle(self, name: str) -> SecretHandle:
        self._get(name)
        return SecretHandle(name, self)

    def delete(self, name: str) -> None:
        self._b.delete_password(SERVICE, name)

    def _get(self, name: str) -> str:
        value = self._b.get_password(SERVICE, name)
        if value is None:
            raise KeyError(name)
        return value
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_secrets.py -v`
Expected: all passed

- [ ] **Step 5: Commit**

```bash
git add src/watchtower/engine/governor/secrets.py tests/test_secrets.py
git commit -m "feat(governor): add Keychain secret store with redacted handles"
```

---

### Task 7: Model Socket

**Files:**
- Create: `src/watchtower/engine/model_socket.py`, `tests/test_model_socket.py`

**Interfaces:**
- Consumes: `Settings` (Task 1), `Budget`, `BudgetExceeded` (Task 5), `AuditLog` (Task 4), `fake_response` (conftest).
- Produces: `ModelUnavailable(Exception)`, `CloudDisabled(Exception)`, `Reply` dataclass (`text, model, prompt_tokens, completion_tokens, seconds, usd`); `ModelSocket(settings, budget, audit, completion_fn=None, unload_fn=None, clock=time.monotonic)` with `ask(tier: str, messages: list[dict], job_id: str) -> Reply` and read-only property `loaded: str | None`. Unknown tier → `ValueError`.

- [ ] **Step 1: Write the failing test**

`tests/test_model_socket.py`:
```python
from dataclasses import replace

import pytest

from conftest import fake_response
from watchtower.engine.governor.audit import AuditLog
from watchtower.engine.governor.budget import Budget, BudgetExceeded
from watchtower.engine.model_socket import CloudDisabled, ModelSocket, ModelUnavailable


@pytest.fixture
def parts(conn, settings):
    budget = Budget(conn)
    budget.open("j", max_tokens=1000, max_seconds=600, max_usd=0.0)
    return settings, budget, AuditLog(conn)


def make(parts, completion=None, unloaded=None):
    settings, budget, audit = parts
    calls = []

    def fake_completion(**kw):
        calls.append(kw)
        return fake_response("hello", 4, 6)

    sock = ModelSocket(
        settings, budget, audit,
        completion_fn=completion or fake_completion,
        unload_fn=(unloaded.append if unloaded is not None else lambda m: None),
        clock=iter([0.0, 2.0, 10.0, 12.0, 20.0, 22.0]).__next__,
    )
    return sock, calls


def test_ask_routes_tier_and_returns_reply(parts):
    sock, calls = make(parts)
    reply = sock.ask("small", [{"role": "user", "content": "hi"}], "j")
    assert reply.text == "hello"
    assert reply.model == "ollama/llama3.2:3b"
    assert (reply.prompt_tokens, reply.completion_tokens, reply.seconds, reply.usd) == (4, 6, 2.0, 0.0)
    assert calls[0]["model"] == "ollama/llama3.2:3b"
    assert calls[0]["api_base"] == "http://localhost:11434"


def test_ask_charges_budget_and_audits(parts):
    _, budget, audit = parts
    sock, _ = make(parts)
    sock.ask("small", [{"role": "user", "content": "hi"}], "j")
    assert budget.usage("j")["used_tokens"] == 10
    actions = [e.action for e in audit.entries(job_id="j")]
    assert actions == ["model_call", "model_reply"]


def test_only_one_local_model_loaded(parts):
    unloaded = []
    sock, _ = make(parts, unloaded=unloaded)
    sock.ask("small", [{"role": "user", "content": "a"}], "j")
    sock.ask("small", [{"role": "user", "content": "b"}], "j")
    assert unloaded == []
    sock.ask("work", [{"role": "user", "content": "c"}], "j")
    assert unloaded == ["ollama/llama3.2:3b"]
    assert sock.loaded == "ollama/qwen2.5-coder:3b"


def test_unknown_tier(parts):
    sock, _ = make(parts)
    with pytest.raises(ValueError, match="tier"):
        sock.ask("giant", [], "j")


def test_cloud_model_blocked_by_default(parts):
    settings, budget, audit = parts
    cloud = replace(settings, tiers={**settings.tiers, "cloud": "anthropic/claude-haiku"})
    sock, calls = make((cloud, budget, audit))
    with pytest.raises(CloudDisabled):
        sock.ask("cloud", [{"role": "user", "content": "x"}], "j")
    assert calls == []


def test_ollama_down_gives_actionable_error_and_audit(parts):
    _, _, audit = parts

    def broken(**kw):
        raise ConnectionError("Connection refused")

    sock, _ = make(parts, completion=broken)
    with pytest.raises(ModelUnavailable, match="ollama pull llama3.2:3b"):
        sock.ask("small", [{"role": "user", "content": "x"}], "j")
    assert [e.action for e in audit.entries(job_id="j")] == ["model_call", "model_error"]


def test_budget_exceeded_stops(parts):
    settings, budget, audit = parts
    budget.open("tiny", max_tokens=5, max_seconds=600, max_usd=0.0)
    sock, _ = make(parts)
    with pytest.raises(BudgetExceeded):
        sock.ask("small", [{"role": "user", "content": "x"}], "tiny")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_model_socket.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement**

`src/watchtower/engine/model_socket.py`:
```python
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable

from watchtower.config import Settings
from watchtower.engine.governor.audit import AuditLog
from watchtower.engine.governor.budget import Budget

LOCAL_PREFIX = "ollama/"


class ModelUnavailable(Exception):
    pass


class CloudDisabled(Exception):
    pass


@dataclass(frozen=True)
class Reply:
    text: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    seconds: float
    usd: float


def _litellm_completion(**kw):
    import litellm

    return litellm.completion(**kw)


def _litellm_cost(response) -> float:
    import litellm

    return float(litellm.completion_cost(completion_response=response))


class ModelSocket:
    """One way to call any model. Routes by tier; keeps only one local model in RAM."""

    def __init__(
        self,
        settings: Settings,
        budget: Budget,
        audit: AuditLog,
        completion_fn: Callable | None = None,
        unload_fn: Callable[[str], None] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ):
        self._s = settings
        self._budget = budget
        self._audit = audit
        self._complete = completion_fn or _litellm_completion
        self._unload = unload_fn or self._unload_ollama
        self._clock = clock
        self._loaded: str | None = None

    @property
    def loaded(self) -> str | None:
        return self._loaded

    def ask(self, tier: str, messages: list[dict], job_id: str) -> Reply:
        if tier not in self._s.tiers:
            raise ValueError(f"unknown model tier {tier!r}; known: {sorted(self._s.tiers)}")
        model = self._s.tiers[tier]
        local = model.startswith(LOCAL_PREFIX)
        if not local and not self._s.cloud_enabled:
            raise CloudDisabled(f"cloud model {model} is disabled; enable cloud models explicitly")
        self._budget.check(job_id)
        if local:
            self._swap_to(model, job_id)

        self._audit.append("model_socket", "model_call", {"tier": tier, "model": model}, job_id)
        kwargs = {"model": model, "messages": messages}
        if local:
            kwargs["api_base"] = self._s.ollama_url
        start = self._clock()
        try:
            resp = self._complete(**kwargs)
        except Exception as e:
            self._audit.append(
                "model_socket", "model_error",
                {"model": model, "error": f"{type(e).__name__}: {str(e)[:200]}"}, job_id,
            )
            hint = f" Is Ollama running? Try: ollama pull {model.removeprefix(LOCAL_PREFIX)}" if local else ""
            raise ModelUnavailable(f"{model} unavailable ({type(e).__name__}).{hint}") from e
        seconds = self._clock() - start

        pt = int(resp.usage.prompt_tokens or 0)
        ct = int(resp.usage.completion_tokens or 0)
        usd = 0.0 if local else _litellm_cost(resp)
        self._budget.charge(job_id, tokens=pt + ct, seconds=seconds, usd=usd)
        self._audit.append(
            "model_socket", "model_reply",
            {"model": model, "tokens": pt + ct, "seconds": round(seconds, 3), "usd": usd}, job_id,
        )
        return Reply(resp.choices[0].message.content or "", model, pt, ct, seconds, usd)

    def _swap_to(self, model: str, job_id: str) -> None:
        if self._loaded and self._loaded != model:
            try:
                self._unload(self._loaded)
            except Exception as e:
                self._audit.append(
                    "model_socket", "unload_failed", {"model": self._loaded, "error": str(e)[:200]}, job_id
                )
        self._loaded = model

    def _unload_ollama(self, model: str) -> None:
        import httpx

        httpx.post(
            f"{self._s.ollama_url}/api/generate",
            json={"model": model.removeprefix(LOCAL_PREFIX), "keep_alive": 0},
            timeout=10,
        ).raise_for_status()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_model_socket.py -v`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add src/watchtower/engine/model_socket.py tests/test_model_socket.py
git commit -m "feat(engine): add model socket with tiers, one-local-model rule, budget + audit"
```

---

### Task 8: CLI — run / status / logs / budget

**Files:**
- Create: `src/watchtower/cli.py`, `tests/test_cli.py`

**Interfaces:**
- Consumes: everything above.
- Produces: Typer `app`; module-level `build_socket(settings, budget, audit) -> ModelSocket` (tests monkeypatch it). Exit codes: 0 ok, 1 job failed, 2 bad input.

- [ ] **Step 1: Write the failing test**

`tests/test_cli.py`:
```python
import pytest
from typer.testing import CliRunner

from conftest import fake_response
from watchtower import cli
from watchtower.engine.model_socket import ModelSocket

runner = CliRunner()


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("WATCHTOWER_HOME", str(tmp_path))
    return tmp_path


def use_completion(monkeypatch, fn):
    monkeypatch.setattr(
        cli, "build_socket",
        lambda s, b, a: ModelSocket(s, b, a, completion_fn=fn, unload_fn=lambda m: None),
    )


def test_run_success(monkeypatch):
    use_completion(monkeypatch, lambda **kw: fake_response("Hello from the tower", 3, 4))
    result = runner.invoke(cli.app, ["run", "hello"])
    assert result.exit_code == 0, result.output
    assert "Hello from the tower" in result.output
    status = runner.invoke(cli.app, ["status"])
    assert "done" in status.output and "hello" in status.output


@pytest.mark.parametrize("bad", ["", "   "])
def test_run_rejects_empty_prompt(monkeypatch, bad):
    use_completion(monkeypatch, lambda **kw: fake_response())
    result = runner.invoke(cli.app, ["run", bad])
    assert result.exit_code == 2
    assert "empty" in result.output
    assert "No jobs" in runner.invoke(cli.app, ["status"]).output


def test_run_ollama_down(monkeypatch):
    def broken(**kw):
        raise ConnectionError("refused")

    use_completion(monkeypatch, broken)
    result = runner.invoke(cli.app, ["run", "hello"])
    assert result.exit_code == 1
    assert "ollama pull" in result.output
    assert "Traceback" not in result.output
    assert "failed" in runner.invoke(cli.app, ["status"]).output


def test_run_budget_exceeded(monkeypatch):
    use_completion(monkeypatch, lambda **kw: fake_response("x", 50, 50))
    result = runner.invoke(cli.app, ["run", "hello", "--max-tokens", "10"])
    assert result.exit_code == 1
    assert "budget exceeded" in result.output


def test_logs_and_budget(monkeypatch):
    use_completion(monkeypatch, lambda **kw: fake_response("ok", 1, 1))
    runner.invoke(cli.app, ["run", "hello"])
    from watchtower.config import load_settings
    from watchtower.engine.db import connect
    from watchtower.engine.jobs import JobStore
    job_id = JobStore(connect(load_settings().db_path)).list()[0].id

    logs = runner.invoke(cli.app, ["logs", job_id])
    assert logs.exit_code == 0
    for action in ("job_created", "model_call", "model_reply", "job_done"):
        assert action in logs.output
    assert "chain: ok" in logs.output

    budget = runner.invoke(cli.app, ["budget", job_id])
    assert budget.exit_code == 0
    assert "tokens: 2 / 50000" in budget.output


def test_budget_unknown_job():
    result = runner.invoke(cli.app, ["budget", "nope"])
    assert result.exit_code == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_cli.py -v`
Expected: FAIL — `ImportError: cannot import name 'cli'`

- [ ] **Step 3: Implement**

`src/watchtower/cli.py`:
```python
from __future__ import annotations

from typing import Optional

import typer

from watchtower.config import Settings, load_settings
from watchtower.engine.db import connect
from watchtower.engine.governor.audit import AuditLog
from watchtower.engine.governor.budget import Budget, BudgetExceeded
from watchtower.engine.jobs import JobStore
from watchtower.engine.memory import ContextStore
from watchtower.engine.model_socket import CloudDisabled, ModelSocket, ModelUnavailable

app = typer.Typer(no_args_is_help=True, help="THE WATCHTOWER — local agentic ecosystem.")


def build_socket(settings: Settings, budget: Budget, audit: AuditLog) -> ModelSocket:
    return ModelSocket(settings, budget, audit)


def _open():
    settings = load_settings()
    return settings, connect(settings.db_path)


@app.command()
def run(
    prompt: str,
    tier: str = typer.Option("small", help="Model tier: small | work | review"),
    max_tokens: Optional[int] = typer.Option(None, help="Token budget for this job"),
):
    """Send a prompt through the Ground Engine."""
    if not prompt.strip():
        typer.echo("Error: prompt must not be empty", err=True)
        raise typer.Exit(2)
    settings, conn = _open()
    jobs, audit, budget, memory = JobStore(conn), AuditLog(conn), Budget(conn), ContextStore(conn)

    job = jobs.create(prompt)
    budget.open(job.id, max_tokens or settings.default_max_tokens,
                settings.default_max_seconds, settings.default_max_usd)
    audit.append("owner", "job_created", {"prompt": job.prompt, "tier": tier}, job.id)
    jobs.set_status(job.id, "running")

    messages = [{"role": "user", "content": job.prompt}]
    try:
        reply = build_socket(settings, budget, audit).ask(tier, messages, job.id)
    except (ModelUnavailable, BudgetExceeded, CloudDisabled, ValueError) as e:
        jobs.set_status(job.id, "failed", str(e))
        audit.append("engine", "job_failed", {"error": str(e)}, job.id)
        typer.echo(f"Job {job.id} failed: {e}", err=True)
        raise typer.Exit(1)

    messages.append({"role": "assistant", "content": reply.text})
    memory.save("ground.echo", job.id, {"messages": messages})
    jobs.set_status(job.id, "done")
    audit.append("engine", "job_done", {"tokens": reply.prompt_tokens + reply.completion_tokens}, job.id)
    typer.echo(reply.text)
    typer.echo(f"\n[job {job.id} · {reply.model} · "
               f"{reply.prompt_tokens + reply.completion_tokens} tokens · ${reply.usd:.4f}]")


@app.command()
def status(limit: int = 20):
    """List recent jobs."""
    _, conn = _open()
    rows = JobStore(conn).list(limit)
    if not rows:
        typer.echo("No jobs yet.")
        return
    for j in rows:
        line = f"{j.id}  {j.status:<8} {j.created_at[:19]}  {j.prompt[:60]}"
        typer.echo(line + (f"  — {j.error}" if j.error else ""))


@app.command()
def logs(job_id: Optional[str] = typer.Argument(None), limit: int = 100):
    """Show the audit log (optionally for one job) and verify its hash chain."""
    _, conn = _open()
    audit = AuditLog(conn)
    for e in audit.entries(job_id=job_id, limit=limit):
        typer.echo(f"#{e.seq} {e.ts[:19]} {e.actor:<13} {e.action:<12} {e.detail}")
    typer.echo(f"chain: {'ok' if audit.verify() else 'BROKEN — audit log was tampered with'}")


@app.command()
def budget(job_id: str):
    """Show budget usage for a job."""
    _, conn = _open()
    try:
        u = Budget(conn).usage(job_id)
    except KeyError:
        typer.echo(f"Error: no budget for job {job_id}", err=True)
        raise typer.Exit(2)
    typer.echo(f"tokens: {u['used_tokens']} / {u['max_tokens']}")
    typer.echo(f"seconds: {u['used_seconds']:.1f} / {u['max_seconds']}")
    typer.echo(f"usd: ${u['used_usd']:.4f} / ${u['max_usd']:.4f}")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest -v`
Expected: all tests in all files pass

- [ ] **Step 5: Commit**

```bash
git add src/watchtower/cli.py tests/test_cli.py
git commit -m "feat(cli): add run/status/logs/budget commands"
```

---

### Task 9: Real smoke test with Ollama

No new code. Verifies the whole Phase 1a against a real local model.

- [ ] **Step 1: Pull the small model (≈2 GB download — ask the owner before running)**

Run: `ollama pull llama3.2:3b`
Expected: `success`

- [ ] **Step 2: Make sure Ollama is serving**

Run: `curl -s http://localhost:11434/api/tags | head -c 200`
Expected: JSON listing `llama3.2:3b`. If connection refused, start it: `open -a Ollama` (or `ollama serve` in a separate terminal).

- [ ] **Step 3: Run a real job**

Run: `uv run watchtower run "In one sentence, what is a lighthouse?"`
Expected: a one-sentence answer, then `[job <id> · ollama/llama3.2:3b · N tokens · $0.0000]`

- [ ] **Step 4: Inspect it**

Run: `uv run watchtower status` → job shows `done`
Run: `uv run watchtower logs <id>` → `job_created, model_call, model_reply, job_done`, then `chain: ok`
Run: `uv run watchtower budget <id>` → `usd: $0.0000 / $0.0000`

- [ ] **Step 5: Failure path**

Quit Ollama, then run: `uv run watchtower run "hello"`
Expected: exit 1, `Job <id> failed: ollama/llama3.2:3b unavailable (...). Is Ollama running? Try: ollama pull llama3.2:3b`, no traceback.

- [ ] **Step 6: RAM check**

While a job runs: `memory_pressure | tail -1`
Expected: system-wide free memory percentage stays above ~20%.

- [ ] **Step 7: Tag**

```bash
git tag phase-1a
```
