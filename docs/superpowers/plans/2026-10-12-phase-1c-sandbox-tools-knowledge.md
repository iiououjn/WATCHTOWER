# Phase 1c — Sandbox, Tool Hub, Knowledge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete the Ground Engine: a locked-down Docker sandbox for agent code, a default-deny MCP Tool Hub, a local full-text Knowledge store with provenance, and a `watchtower doctor` health check.

**Architecture:** `Sandbox` shells out to the `docker` CLI with hardening flags and only ever mounts `~/.watchtower/workspaces/<job>`. `Knowledge` stores chunked documents in SQLite FTS5 (BM25) via migration 3, every chunk tied to a source and a `trusted` flag. `ToolHub` calls tools on MCP stdio servers (MCP SDK 2.x) after a per-role fnmatch policy check. CLI gains `doctor` and `knowledge add/search`.

**Tech Stack:** Python 3.12, Docker CLI, SQLite FTS5, `mcp` 2.x, Typer, pytest.

**Spec:** `docs/superpowers/specs/2026-10-12-watchtower-design.md` (§4 Sandbox/Tool Hub/Knowledge, §7 quarantine, §9 security, §12 phase 1c)

## Global Constraints

- Never auto-start Docker; never auto-pull images (`--pull never`). Missing Docker/image → `SandboxUnavailable` with a fix hint.
- Sandbox flags: `--network none --read-only --tmpfs /tmp:rw,size=64m --memory 512m --cpus 1 --pids-limit 128 --cap-drop ALL --security-opt no-new-privileges --user 1000:1000`.
- Sandbox mounts only `settings.home/workspaces/<job_id>`; job ids must match `[A-Za-z0-9_-]+`.
- Tool Hub is default-deny; tool argument values never reach the audit log.
- Knowledge v1 = SQLite FTS5 (no embedding model, no extra RAM); web content defaults to `trusted=False`.
- MCP SDK 2.x API: server `from mcp.server.mcpserver import MCPServer`; result fields `content`, `is_error`.
- Files under 500 lines.

## Review Focus

1. **Docker installed but not running** (owner's current state) → clear one-line fix, job-pausable error, no traceback. (Task 1, Task 4)
2. **Hostile job id like `../../Users/rishi`** → rejected; nothing outside the tower's workspace is ever mounted. (Task 1)
3. **Search text containing FTS syntax** (`"`, `*`, `NEAR(`, `AND OR`) → no crash, sensible results. (Task 2)
4. **Tool call by a role with no policy** → denied before any server process starts. (Task 3)
5. **MCP server hangs** → call times out and the server process is cleaned up. (Task 3)

---

## File Structure

```
src/watchtower/config.py                 # MODIFY: sandbox_image
src/watchtower/engine/sandbox.py         # CREATE: Sandbox, SandboxResult, SandboxUnavailable
src/watchtower/engine/db.py              # MODIFY: migration 3 (knowledge tables)
src/watchtower/engine/knowledge.py       # CREATE: Knowledge, Hit
src/watchtower/engine/tools/__init__.py  # CREATE (empty)
src/watchtower/engine/tools/hub.py       # CREATE: ToolHub, ServerSpec, ToolResult, ToolDenied, ToolError
src/watchtower/engine/runner.py          # MODIFY: SandboxUnavailable pauses
src/watchtower/cli.py                    # MODIFY: doctor, knowledge add/search
tests/fixtures/echo_mcp_server.py        # CREATE: test MCP server
tests/test_sandbox.py tests/test_knowledge.py tests/test_tool_hub.py tests/test_cli.py
```

---

### Task 1: Sandbox

**Files:**
- Modify: `src/watchtower/config.py`
- Create: `src/watchtower/engine/sandbox.py`, `tests/test_sandbox.py`

**Interfaces:**
- Consumes: `Settings`, `AuditLog`.
- Produces: `Settings.sandbox_image: str = "python:3.12-slim"`; `SandboxUnavailable(Exception)`; `SandboxResult(exit_code: int, stdout: str, stderr: str, timed_out: bool)`; `Sandbox(settings, audit, run=subprocess.run)` with `workspace(job_id: str) -> Path`, `check() -> str | None` (problem text or None), `run(job_id: str, command: list[str], timeout: float = 60.0) -> SandboxResult`.

- [ ] **Step 1: Write the failing test**

`tests/test_sandbox.py`:
```python
import subprocess
from types import SimpleNamespace

import pytest

from watchtower.engine.governor.audit import AuditLog
from watchtower.engine.sandbox import MAX_OUTPUT, Sandbox, SandboxUnavailable


class FakeDocker:
    def __init__(self, daemon=True, image=True, run_result=None, hang=False):
        self.calls = []
        self.daemon, self.image, self.hang = daemon, image, hang
        self.run_result = run_result or SimpleNamespace(returncode=0, stdout="hello\n", stderr="")

    def __call__(self, argv, **kw):
        self.calls.append(argv)
        if argv[:2] == ["docker", "info"]:
            return SimpleNamespace(returncode=0 if self.daemon else 1, stdout="27.0", stderr="")
        if argv[:3] == ["docker", "image", "inspect"]:
            return SimpleNamespace(returncode=0 if self.image else 1, stdout="", stderr="")
        if argv[:2] == ["docker", "run"]:
            if self.hang:
                raise subprocess.TimeoutExpired(argv, kw["timeout"])
            return self.run_result
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    def run_argv(self):
        return next(a for a in self.calls if a[:2] == ["docker", "run"])


@pytest.fixture
def audit(conn):
    return AuditLog(conn)


def test_runs_command_with_hardening_flags(settings, audit):
    docker = FakeDocker()
    result = Sandbox(settings, audit, run=docker).run("job1", ["python", "-c", "print('hello')"])
    assert (result.exit_code, result.stdout, result.timed_out) == (0, "hello\n", False)
    argv = docker.run_argv()
    for flag in ["--network", "none", "--read-only", "--cap-drop", "ALL", "--pids-limit", "128",
                 "--memory", "512m", "--user", "1000:1000", "--pull", "never", "no-new-privileges"]:
        assert flag in argv
    assert f"{settings.home / 'workspaces' / 'job1'}:/work:rw" in argv
    assert argv[-4:] == ["python:3.12-slim", "python", "-c", "print('hello')"]


@pytest.mark.parametrize("bad", ["../../Users/rishi", "a/b", "", "job 1", ".."])
def test_rejects_hostile_job_ids(settings, audit, bad):
    docker = FakeDocker()
    with pytest.raises(ValueError):
        Sandbox(settings, audit, run=docker).run(bad, ["true"])
    assert not any(a[:2] == ["docker", "run"] for a in docker.calls)


def test_docker_not_running(settings, audit):
    with pytest.raises(SandboxUnavailable, match="Docker is not running"):
        Sandbox(settings, audit, run=FakeDocker(daemon=False)).run("j", ["true"])


def test_docker_not_installed(settings, audit):
    def missing(argv, **kw):
        raise FileNotFoundError("docker")

    sandbox = Sandbox(settings, audit, run=missing)
    assert "not installed" in sandbox.check()
    with pytest.raises(SandboxUnavailable):
        sandbox.run("j", ["true"])


def test_image_missing_gives_pull_hint(settings, audit):
    with pytest.raises(SandboxUnavailable, match="docker pull python:3.12-slim"):
        Sandbox(settings, audit, run=FakeDocker(image=False)).run("j", ["true"])


def test_check_ok(settings, audit):
    assert Sandbox(settings, audit, run=FakeDocker()).check() is None


def test_timeout_kills_container(settings, audit):
    docker = FakeDocker(hang=True)
    result = Sandbox(settings, audit, run=docker).run("j", ["sleep", "999"], timeout=1)
    assert result.timed_out and result.exit_code == 124
    name = docker.run_argv()[docker.run_argv().index("--name") + 1]
    assert ["docker", "kill", name] in docker.calls


def test_output_is_truncated(settings, audit):
    big = SimpleNamespace(returncode=0, stdout="x" * (MAX_OUTPUT + 500), stderr="")
    assert len(Sandbox(settings, audit, run=FakeDocker(run_result=big)).run("j", ["x"]).stdout) == MAX_OUTPUT


def test_empty_command_rejected(settings, audit):
    with pytest.raises(ValueError):
        Sandbox(settings, audit, run=FakeDocker()).run("j", [])


def test_runs_are_audited(settings, audit):
    Sandbox(settings, audit, run=FakeDocker()).run("j", ["true"])
    assert [e.action for e in audit.entries(job_id="j")] == ["sandbox_run", "sandbox_result"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_sandbox.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'watchtower.engine.sandbox'`

- [ ] **Step 3: Implement**

In `src/watchtower/config.py` add to `Settings` after `agent_slots`:
```python
    sandbox_image: str = "python:3.12-slim"
```

`src/watchtower/engine/sandbox.py`:
```python
from __future__ import annotations

import re
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from watchtower.config import Settings
from watchtower.engine.governor.audit import AuditLog

MAX_OUTPUT = 20_000
_JOB_ID = re.compile(r"[A-Za-z0-9_-]+")


class SandboxUnavailable(Exception):
    pass


@dataclass(frozen=True)
class SandboxResult:
    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool


class Sandbox:
    """Runs agent code in a locked-down Docker container. Only the job's own workspace
    (~/.watchtower/workspaces/<job>) is mounted — never the owner's files."""

    def __init__(self, settings: Settings, audit: AuditLog, run: Callable = subprocess.run):
        self._s = settings
        self._audit = audit
        self._run = run

    def workspace(self, job_id: str) -> Path:
        if not _JOB_ID.fullmatch(job_id or ""):
            raise ValueError(f"invalid job id {job_id!r}")
        path = self._s.home / "workspaces" / job_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def check(self) -> str | None:
        """Return what is wrong with Docker, or None if the sandbox is ready."""
        image = self._s.sandbox_image
        try:
            info = self._run(["docker", "info", "--format", "{{.ServerVersion}}"],
                             capture_output=True, text=True, timeout=15)
        except (OSError, subprocess.SubprocessError):
            return "Docker is not installed or not responding; install/start Docker Desktop, then resume"
        if info.returncode != 0:
            return "Docker is not running; start Docker Desktop, then resume"
        inspect = self._run(["docker", "image", "inspect", image], capture_output=True, text=True, timeout=15)
        if inspect.returncode != 0:
            return f"sandbox image {image} is missing; run: docker pull {image}"
        return None

    def run(self, job_id: str, command: list[str], timeout: float = 60.0) -> SandboxResult:
        if not command:
            raise ValueError("command must not be empty")
        workspace = self.workspace(job_id)
        problem = self.check()
        if problem:
            raise SandboxUnavailable(problem)
        name = f"wt-{job_id}-{uuid.uuid4().hex[:8]}"
        argv = [
            "docker", "run", "--rm", "--name", name, "--pull", "never",
            "--network", "none", "--read-only", "--tmpfs", "/tmp:rw,size=64m",
            "--memory", "512m", "--cpus", "1", "--pids-limit", "128",
            "--cap-drop", "ALL", "--security-opt", "no-new-privileges", "--user", "1000:1000",
            "-v", f"{workspace}:/work:rw", "-w", "/work",
            self._s.sandbox_image, *command,
        ]
        self._audit.append("sandbox", "sandbox_run", {"command": command[:20]}, job_id)
        try:
            proc = self._run(argv, capture_output=True, text=True, timeout=timeout)
            result = SandboxResult(proc.returncode, (proc.stdout or "")[-MAX_OUTPUT:],
                                   (proc.stderr or "")[-MAX_OUTPUT:], False)
        except subprocess.TimeoutExpired:
            self._kill(name)
            result = SandboxResult(124, "", f"timed out after {timeout}s", True)
        self._audit.append("sandbox", "sandbox_result",
                           {"exit_code": result.exit_code, "timed_out": result.timed_out}, job_id)
        return result

    def _kill(self, name: str) -> None:
        try:
            self._run(["docker", "kill", name], capture_output=True, text=True, timeout=15)
        except (OSError, subprocess.SubprocessError):
            pass
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest -q`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add src tests
git commit -m "feat(engine): add locked-down docker sandbox"
```

---

### Task 2: Knowledge store (SQLite FTS5)

**Files:**
- Modify: `src/watchtower/engine/db.py`
- Create: `src/watchtower/engine/knowledge.py`, `tests/test_knowledge.py`

**Interfaces:**
- Produces: migration 3 (`user_version == 3`); `Hit(doc_id: int, title: str, source: str, snippet: str, score: float, trusted: bool)`; `Knowledge(conn, workspace_id="default")` with `add(text: str, source: str, title: str = "", trusted: bool = False) -> int` (same text → same id), `search(query: str, limit: int = 5) -> list[Hit]` (best chunk per document, highest score first), `count() -> int`.

- [ ] **Step 1: Write the failing test**

`tests/test_knowledge.py`:
```python
import pytest

from watchtower.engine.knowledge import Knowledge

LIGHTHOUSE = "A lighthouse beacon rotates so ships see a flashing light from every direction."
BREAD = "Sourdough bread needs a starter, flour, water and salt."


def test_search_ranks_relevant_doc_first(conn):
    kb = Knowledge(conn)
    kb.add(BREAD, "https://bread.example", "Bread")
    lid = kb.add(LIGHTHOUSE, "https://lights.example", "Lighthouses")
    hits = kb.search("why does a lighthouse rotate its beacon")
    assert hits[0].doc_id == lid
    assert hits[0].source == "https://lights.example"
    assert "beacon" in hits[0].snippet


def test_web_content_is_untrusted_by_default(conn):
    kb = Knowledge(conn)
    kb.add(LIGHTHOUSE, "https://lights.example")
    kb.add(BREAD, "file:///notes/bread.md", trusted=True)
    trust = {h.source: h.trusted for h in kb.search("lighthouse bread")}
    assert trust == {"https://lights.example": False, "file:///notes/bread.md": True}


def test_same_text_is_stored_once(conn):
    kb = Knowledge(conn)
    assert kb.add(LIGHTHOUSE, "a") == kb.add(LIGHTHOUSE, "b")
    assert kb.count() == 1


@pytest.mark.parametrize("query", ['"', "*", "NEAR(", "AND OR NOT", "beacon\"; DROP TABLE x", "(((", "-"])
def test_fts_syntax_in_query_never_crashes(conn, query):
    kb = Knowledge(conn)
    kb.add(LIGHTHOUSE, "a")
    kb.search(query)


def test_empty_query_returns_nothing(conn):
    kb = Knowledge(conn)
    kb.add(LIGHTHOUSE, "a")
    assert kb.search("   ") == []


def test_long_document_chunked_one_hit_per_doc(conn):
    kb = Knowledge(conn)
    filler = "\n\n".join(f"Paragraph {i} about harbours and tides." * 10 for i in range(20))
    doc = kb.add(filler + "\n\nThe Fresnel lens was invented in 1822.", "long")
    hits = kb.search("fresnel lens harbours")
    assert [h.doc_id for h in hits] == [doc]


def test_workspaces_are_isolated(conn):
    Knowledge(conn, workspace_id="a").add(LIGHTHOUSE, "a")
    assert Knowledge(conn, workspace_id="b").search("lighthouse") == []


@pytest.mark.parametrize("text,source", [("", "a"), ("   ", "a"), ("x", ""), ("x", "  ")])
def test_rejects_blank_text_or_source(conn, text, source):
    with pytest.raises(ValueError):
        Knowledge(conn).add(text, source)


def test_unicode_search(conn):
    kb = Knowledge(conn)
    doc = kb.add("Le phare de Cordouan éclaire l'estuaire.", "fr")
    assert kb.search("phare")[0].doc_id == doc
```

Append to `tests/test_db.py` and update the two existing `== 2` user_version assertions in that file to `== 3`:
```python
def test_knowledge_tables_exist(conn):
    names = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master")}
    assert {"knowledge_docs", "knowledge_fts"} <= names
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_knowledge.py tests/test_db.py -q`
Expected: FAIL — `No module named 'watchtower.engine.knowledge'`, user_version 2 ≠ 3

- [ ] **Step 3: Implement**

In `src/watchtower/engine/db.py` append to `MIGRATIONS`:
```python
    """
    CREATE TABLE knowledge_docs(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        workspace_id TEXT NOT NULL,
        source TEXT NOT NULL,
        title TEXT NOT NULL,
        sha256 TEXT NOT NULL,
        trusted INTEGER NOT NULL,
        added_at TEXT NOT NULL,
        UNIQUE(workspace_id, sha256)
    );
    CREATE VIRTUAL TABLE knowledge_fts USING fts5(title, body, doc_id UNINDEXED, workspace_id UNINDEXED);
    """,
```

`src/watchtower/engine/knowledge.py`:
```python
from __future__ import annotations

import hashlib
import re
import sqlite3
from dataclasses import dataclass

from watchtower.engine.db import now

CHUNK_CHARS = 1200
MAX_TERMS = 16


@dataclass(frozen=True)
class Hit:
    doc_id: int
    title: str
    source: str
    snippet: str
    score: float
    trusted: bool


def _chunks(text: str) -> list[str]:
    chunks, current = [], ""
    for para in re.split(r"\n\s*\n", text):
        para = para.strip()
        while len(para) > CHUNK_CHARS:
            chunks.append(para[:CHUNK_CHARS])
            para = para[CHUNK_CHARS:]
        if current and len(current) + len(para) + 2 > CHUNK_CHARS:
            chunks.append(current)
            current = ""
        current = f"{current}\n\n{para}" if current else para
    if current:
        chunks.append(current)
    return chunks


class Knowledge:
    """Local knowledge store: chunked full-text search (SQLite FTS5, BM25) with provenance.
    Every chunk keeps its source and a trusted flag; web content is untrusted by default."""

    def __init__(self, conn: sqlite3.Connection, workspace_id: str = "default"):
        self._conn = conn
        self._ws = workspace_id

    def add(self, text: str, source: str, title: str = "", trusted: bool = False) -> int:
        text, source = text.strip(), source.strip()
        if not text or not source:
            raise ValueError("knowledge text and source must not be blank")
        digest = hashlib.sha256(text.encode()).hexdigest()
        row = self._conn.execute(
            "SELECT id FROM knowledge_docs WHERE workspace_id=? AND sha256=?", (self._ws, digest)
        ).fetchone()
        if row:
            return row["id"]
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            doc_id = self._conn.execute(
                "INSERT INTO knowledge_docs(workspace_id, source, title, sha256, trusted, added_at)"
                " VALUES (?,?,?,?,?,?)",
                (self._ws, source, title.strip() or source, digest, int(trusted), now()),
            ).lastrowid
            self._conn.executemany(
                "INSERT INTO knowledge_fts(title, body, doc_id, workspace_id) VALUES (?,?,?,?)",
                [(title, chunk, doc_id, self._ws) for chunk in _chunks(text)],
            )
            self._conn.execute("COMMIT")
        except BaseException:
            self._conn.execute("ROLLBACK")
            raise
        return doc_id

    def search(self, query: str, limit: int = 5) -> list[Hit]:
        terms = re.findall(r"\w+", query.lower())[:MAX_TERMS]
        if not terms:
            return []
        match = " OR ".join(f'"{t}"' for t in terms)
        rows = self._conn.execute(
            "SELECT d.id, d.title, d.source, d.trusted,"
            " snippet(knowledge_fts, 1, '[', ']', '…', 12) AS snip, bm25(knowledge_fts) AS rank"
            " FROM knowledge_fts JOIN knowledge_docs d ON d.id = knowledge_fts.doc_id"
            " WHERE knowledge_fts MATCH ? AND knowledge_fts.workspace_id = ?"
            " ORDER BY rank LIMIT ?",
            (match, self._ws, limit * 4),
        ).fetchall()
        hits, seen = [], set()
        for r in rows:
            if r["id"] in seen:
                continue
            seen.add(r["id"])
            hits.append(Hit(r["id"], r["title"], r["source"], r["snip"], -r["rank"], bool(r["trusted"])))
            if len(hits) == limit:
                break
        return hits

    def count(self) -> int:
        return self._conn.execute(
            "SELECT COUNT(*) FROM knowledge_docs WHERE workspace_id=?", (self._ws,)
        ).fetchone()[0]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest -q`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add src tests
git commit -m "feat(engine): add local full-text knowledge store with provenance"
```

---

### Task 3: Tool Hub (MCP, default-deny)

**Files:**
- Create: `src/watchtower/engine/tools/__init__.py` (empty), `src/watchtower/engine/tools/hub.py`, `tests/fixtures/echo_mcp_server.py`, `tests/test_tool_hub.py`
- Modify: `pyproject.toml`, `uv.lock` (via `uv add`)

**Interfaces:**
- Consumes: `AuditLog`.
- Produces: `ServerSpec(command: str, args: tuple[str, ...] = ())`; `ToolResult(ok: bool, text: str)`; `ToolDenied(PermissionError)`; `ToolError(Exception)`; `ToolHub(audit, servers: dict[str, ServerSpec], policy: dict[str, list[str]], timeout: float = 30.0)` with `allowed(role, server, tool) -> bool`, `list_tools(server: str) -> list[str]`, `call(role: str, job_id: str | None, server: str, tool: str, args: dict) -> ToolResult`. Policy entries are fnmatch patterns over `"<server>.<tool>"`.

- [ ] **Step 1: Add dependency**

Run: `uv add "mcp>=2.3,<3"`
Expected: installs `mcp` 2.x.

- [ ] **Step 2: Write the failing test**

`tests/fixtures/echo_mcp_server.py`:
```python
import time

from mcp.server.mcpserver import MCPServer

server = MCPServer("echo")


@server.tool()
def echo(text: str) -> str:
    """Echo text back."""
    return text


@server.tool()
def fail() -> str:
    """Always fails."""
    raise ValueError("nope")


@server.tool()
def sleep(seconds: float) -> str:
    """Sleep, to test timeouts."""
    time.sleep(seconds)
    return "woke"


if __name__ == "__main__":
    server.run()
```

`tests/test_tool_hub.py`:
```python
import sys
from pathlib import Path

import pytest

from watchtower.engine.governor.audit import AuditLog
from watchtower.engine.tools.hub import ServerSpec, ToolDenied, ToolError, ToolHub

ECHO = ServerSpec(sys.executable, (str(Path(__file__).parent / "fixtures" / "echo_mcp_server.py"),))


def hub(conn, policy=None, servers=None, timeout=30.0):
    return ToolHub(AuditLog(conn), servers or {"echo": ECHO},
                   policy if policy is not None else {"f1.worker": ["echo.echo"]}, timeout=timeout)


def test_allowed_call_returns_text(conn):
    result = hub(conn).call("f1.worker", "j", "echo", "echo", {"text": "hi 🗼"})
    assert (result.ok, result.text) == (True, "hi 🗼")


def test_list_tools(conn):
    assert set(hub(conn).list_tools("echo")) == {"echo", "fail", "sleep"}


def test_denied_before_server_starts(conn):
    never = {"echo": ServerSpec("/definitely/not/a/binary")}
    with pytest.raises(ToolDenied, match="may not call echo.echo"):
        hub(conn, servers=never).call("f2.worker", "j", "echo", "echo", {"text": "x"})


def test_default_deny_for_unknown_role(conn):
    assert hub(conn).allowed("nobody", "echo", "echo") is False


def test_wildcard_policy(conn):
    h = hub(conn, policy={"f5.reviewer": ["echo.*"]})
    assert h.allowed("f5.reviewer", "echo", "fail") is True
    assert h.allowed("f5.reviewer", "files", "read") is False


def test_tool_error_result_is_not_ok(conn):
    result = hub(conn, policy={"r": ["echo.*"]}).call("r", "j", "echo", "fail", {})
    assert result.ok is False


def test_broken_server_raises_tool_error(conn):
    broken = {"echo": ServerSpec("/definitely/not/a/binary")}
    with pytest.raises(ToolError):
        hub(conn, servers=broken).call("f1.worker", "j", "echo", "echo", {"text": "x"})


def test_unknown_server(conn):
    with pytest.raises(ToolError, match="unknown tool server"):
        hub(conn, policy={"r": ["*"]}).call("r", "j", "nope", "x", {})


def test_hanging_tool_times_out(conn):
    with pytest.raises(ToolError, match="TimeoutError"):
        hub(conn, policy={"r": ["echo.*"]}, timeout=2).call("r", "j", "echo", "sleep", {"seconds": 30})


def test_audit_never_contains_argument_values(conn):
    audit = AuditLog(conn)
    ToolHub(audit, {"echo": ECHO}, {"r": ["echo.*"]}).call("r", "j", "echo", "echo", {"text": "sk-secret-123"})
    assert [e.action for e in audit.entries(job_id="j")] == ["tool_call", "tool_result"]
    raw = " ".join(r[0] for r in conn.execute("SELECT detail FROM audit_log"))
    assert "sk-secret-123" not in raw
    assert "text" in raw
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/test_tool_hub.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'watchtower.engine.tools'`

- [ ] **Step 4: Implement**

`src/watchtower/engine/tools/hub.py`:
```python
from __future__ import annotations

import asyncio
import fnmatch
import os
from dataclasses import dataclass

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.types import CallToolResult

from watchtower.engine.governor.audit import AuditLog

MAX_TEXT = 20_000


@dataclass(frozen=True)
class ServerSpec:
    command: str
    args: tuple[str, ...] = ()


@dataclass(frozen=True)
class ToolResult:
    ok: bool
    text: str


class ToolDenied(PermissionError):
    pass


class ToolError(Exception):
    pass


class ToolHub:
    """Calls tools on MCP stdio servers. Default-deny: a role may only call tools its policy
    lists (fnmatch patterns over "<server>.<tool>"). Argument values are never audited."""

    def __init__(self, audit: AuditLog, servers: dict[str, ServerSpec], policy: dict[str, list[str]],
                 timeout: float = 30.0):
        self._audit = audit
        self._servers = servers
        self._policy = policy
        self._timeout = timeout

    def allowed(self, role: str, server: str, tool: str) -> bool:
        name = f"{server}.{tool}"
        return any(fnmatch.fnmatchcase(name, pattern) for pattern in self._policy.get(role, []))

    def list_tools(self, server: str) -> list[str]:
        spec = self._spec(server)
        try:
            return asyncio.run(self._with_session(spec, lambda s: s.list_tools()))
        except Exception as e:
            raise ToolError(f"{server}: list_tools failed ({type(e).__name__})") from e

    def call(self, role: str, job_id: str | None, server: str, tool: str, args: dict) -> ToolResult:
        spec = self._spec(server)
        meta = {"role": role, "server": server, "tool": tool}
        if not self.allowed(role, server, tool):
            self._audit.append("tool_hub", "tool_denied", meta, job_id)
            raise ToolDenied(f"role {role!r} may not call {server}.{tool}")
        self._audit.append("tool_hub", "tool_call", {**meta, "arg_keys": sorted(args)}, job_id)
        try:
            res = asyncio.run(self._with_session(spec, lambda s: s.call_tool(tool, args)))
        except Exception as e:
            self._audit.append("tool_hub", "tool_error", {**meta, "error": type(e).__name__}, job_id)
            raise ToolError(f"{server}.{tool} failed ({type(e).__name__})") from e
        if not isinstance(res, CallToolResult):
            raise ToolError(f"{server}.{tool} returned an unsupported result type")
        text = "\n".join(c.text for c in res.content if getattr(c, "text", None) is not None)[:MAX_TEXT]
        result = ToolResult(not res.is_error, text)
        self._audit.append("tool_hub", "tool_result", {**meta, "ok": result.ok}, job_id)
        return result

    def _spec(self, server: str) -> ServerSpec:
        if server not in self._servers:
            raise ToolError(f"unknown tool server {server!r}")
        return self._servers[server]

    async def _with_session(self, spec: ServerSpec, action):
        params = StdioServerParameters(command=spec.command, args=list(spec.args))
        with open(os.devnull, "w") as errlog:
            async with asyncio.timeout(self._timeout):
                async with stdio_client(params, errlog=errlog) as (read, write):
                    async with ClientSession(read, write) as session:
                        await session.initialize()
                        out = await action(session)
        if hasattr(out, "tools"):
            return [t.name for t in out.tools]
        return out
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest -q`
Expected: all pass

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml uv.lock src tests
git commit -m "feat(engine): add default-deny MCP tool hub"
```

---

### Task 4: Runner pause on sandbox, `doctor`, `knowledge` CLI

**Files:**
- Modify: `src/watchtower/engine/runner.py`, `src/watchtower/cli.py`, `tests/test_cli.py`

**Interfaces:**
- Consumes: `Sandbox.check`, `SandboxUnavailable` (Task 1), `Knowledge` (Task 2), `free_ram_pct` (1b).
- Produces: `PAUSE_ERRORS` includes `SandboxUnavailable`; CLI commands `doctor` (exit 0 all ok, 1 otherwise) and `knowledge add <path> [--source] [--title] [--trusted]`, `knowledge search <query> [--limit]`; module-level `ollama_status(settings) -> tuple[bool, str]` and `docker_status(settings, audit) -> tuple[bool, str]` (tests monkeypatch them).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_cli.py`:
```python
def test_doctor_all_ok(monkeypatch):
    monkeypatch.setattr(cli, "ollama_status", lambda s: (True, "Ollama 0.32 · models ok"))
    monkeypatch.setattr(cli, "docker_status", lambda s, a: (True, "ready"))
    monkeypatch.setattr(cli, "free_ram_pct", lambda: 55)
    result = runner.invoke(cli.app, ["doctor"])
    assert result.exit_code == 0, result.output
    for word in ("Ollama", "Docker", "RAM", "55%", "Audit chain"):
        assert word in result.output


def test_doctor_reports_docker_down(monkeypatch):
    monkeypatch.setattr(cli, "ollama_status", lambda s: (True, "ok"))
    monkeypatch.setattr(cli, "docker_status", lambda s, a: (False, "Docker is not running; start Docker Desktop"))
    monkeypatch.setattr(cli, "free_ram_pct", lambda: 55)
    result = runner.invoke(cli.app, ["doctor"])
    assert result.exit_code == 1
    assert "start Docker Desktop" in result.output


def test_knowledge_add_and_search(tmp_path):
    note = tmp_path / "lights.md"
    note.write_text("The Fresnel lens made lighthouse beams visible for miles.")
    added = runner.invoke(cli.app, ["knowledge", "add", str(note), "--title", "Lenses"])
    assert added.exit_code == 0, added.output
    found = runner.invoke(cli.app, ["knowledge", "search", "fresnel lens"])
    assert "Lenses" in found.output and "[Fresnel]" in found.output and "untrusted" in found.output
    assert "No matches" in runner.invoke(cli.app, ["knowledge", "search", "sourdough"]).output


def test_knowledge_add_rejects_missing_or_huge_files(tmp_path):
    assert runner.invoke(cli.app, ["knowledge", "add", str(tmp_path / "nope.md")]).exit_code == 2
    big = tmp_path / "big.txt"
    big.write_bytes(b"x" * (5 * 1024 * 1024 + 1))
    assert runner.invoke(cli.app, ["knowledge", "add", str(big)]).exit_code == 2
```

Append to `tests/test_runner.py`:
```python
def test_sandbox_unavailable_pauses(env):
    from watchtower.engine.sandbox import SandboxUnavailable
    runner, jobs, bus, model, unloaded, job = env

    def go():
        raise SandboxUnavailable("Docker is not running; start Docker Desktop, then resume")

    jobs.set_status(job.id, "running")
    out = runner._drive(job.id, go)
    assert out.status == "paused" and "Docker" in out.reason
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_cli.py tests/test_runner.py -q`
Expected: FAIL — `No such command 'doctor'`, `No such command 'knowledge'`, sandbox error marks job `failed`.

- [ ] **Step 3: Implement**

In `src/watchtower/engine/runner.py`: add `from watchtower.engine.sandbox import SandboxUnavailable` and change
```python
PAUSE_ERRORS = (ModelUnavailable, LowMemory, SchedulerBusy, SandboxUnavailable)
```

In `src/watchtower/cli.py` add imports:
```python
from pathlib import Path

from watchtower.engine.knowledge import Knowledge
from watchtower.engine.sandbox import Sandbox
from watchtower.engine.system import free_ram_pct
```
and append:
```python
MAX_KNOWLEDGE_BYTES = 5 * 1024 * 1024
knowledge_app = typer.Typer(help="Local knowledge store (full-text search with sources).")
app.add_typer(knowledge_app, name="knowledge")


def ollama_status(settings: Settings) -> tuple[bool, str]:
    import httpx

    try:
        version = httpx.get(f"{settings.ollama_url}/api/version", timeout=3).json()["version"]
        names = {m["name"] for m in httpx.get(f"{settings.ollama_url}/api/tags", timeout=3).json()["models"]}
    except Exception:
        return False, "not reachable — open the Ollama app"
    missing = sorted({m.removeprefix("ollama/") for m in settings.tiers.values()} - names)
    if missing:
        return True, f"{version} · missing models: {', '.join(missing)} (ollama pull <name>)"
    return True, f"{version} · all tier models present"


def docker_status(settings: Settings, audit: AuditLog) -> tuple[bool, str]:
    problem = Sandbox(settings, audit).check()
    return (problem is None), (problem or f"ready ({settings.sandbox_image})")


@app.command()
def doctor():
    """Check that the tower's engine parts are healthy."""
    settings, conn = _open()
    audit = AuditLog(conn)
    ram = free_ram_pct()
    checks = [
        ("Ollama", *ollama_status(settings)),
        ("Docker", *docker_status(settings, audit)),
        ("RAM", ram is None or ram >= settings.min_free_ram_pct,
         "unknown" if ram is None else f"{ram}% free (need {settings.min_free_ram_pct}%)"),
        ("Audit chain", audit.verify(), "ok" if audit.verify() else "BROKEN"),
    ]
    for name, ok, detail in checks:
        typer.echo(f"{'✓' if ok else '✗'} {name:<12} {detail}")
    raise typer.Exit(0 if all(ok for _, ok, _ in checks) else 1)


@knowledge_app.command("add")
def knowledge_add(
    path: Path,
    source: Optional[str] = typer.Option(None, help="Where this came from (default: the file URI)"),
    title: Optional[str] = typer.Option(None),
    trusted: bool = typer.Option(False, "--trusted", help="Mark as owner-verified"),
):
    """Add a text file to the knowledge store."""
    if not path.is_file():
        typer.echo(f"Error: {path} is not a file", err=True)
        raise typer.Exit(2)
    if path.stat().st_size > MAX_KNOWLEDGE_BYTES:
        typer.echo("Error: file is larger than 5 MB", err=True)
        raise typer.Exit(2)
    _, conn = _open()
    src = source or path.resolve().as_uri()
    try:
        doc_id = Knowledge(conn).add(path.read_text(errors="replace"), src, title or path.name, trusted)
    except ValueError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(2)
    AuditLog(conn).append("owner", "knowledge_added", {"doc_id": doc_id, "source": src, "trusted": trusted})
    typer.echo(f"Added document {doc_id} from {src}")


@knowledge_app.command("search")
def knowledge_search(query: str, limit: int = typer.Option(5, min=1, max=50)):
    """Search the knowledge store."""
    _, conn = _open()
    hits = Knowledge(conn).search(query, limit)
    if not hits:
        typer.echo("No matches.")
        return
    for h in hits:
        typer.echo(f"[{h.doc_id}] {h.title} — {h.source}{'' if h.trusted else ' (untrusted)'}")
        typer.echo(f"    {h.snippet}")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest -q`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add src tests
git commit -m "feat(cli): add doctor and knowledge commands; sandbox outages pause jobs"
```

---

### Task 5: Real smoke test

- [ ] **Step 1: Doctor with Docker off**

Run: `uv run watchtower doctor`
Expected: `✓ Ollama`, `✗ Docker  Docker is not running; start Docker Desktop, then resume`, exit 1.

- [ ] **Step 2: Knowledge round trip**

Run: `WATCHTOWER_HOME=$PWD/.superpowers/smoke uv run watchtower knowledge add docs/superpowers/specs/2026-10-12-watchtower-design.md --trusted`
Run: `WATCHTOWER_HOME=$PWD/.superpowers/smoke uv run watchtower knowledge search "glass layer injection"`
Expected: a hit from the spec with a `[...]`-highlighted snippet.

- [ ] **Step 3: Real sandbox (ASK OWNER FIRST: start Docker Desktop (~2 GB RAM) and `docker pull python:3.12-slim` (~50 MB))**

Run: `uv run python -c "from watchtower.config import load_settings; from watchtower.engine.db import connect; from watchtower.engine.governor.audit import AuditLog; from watchtower.engine.sandbox import Sandbox; s=load_settings(); r=Sandbox(s, AuditLog(connect(s.db_path))).run('smoke', ['python','-c','import socket; print(open(\"/etc/hostname\").read().strip()); socket.create_connection((\"1.1.1.1\",53),2)']); print(r)"`
Expected: `exit_code != 0` with a network error in stderr (proves `--network none`).

- [ ] **Step 4: Tag**

```bash
rm -rf .superpowers/smoke
git tag v0.3-phase-1c
```
