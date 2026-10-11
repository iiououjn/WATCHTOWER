# Phase 1b — Scheduler, Bus, Workflow (pause/resume) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Jobs run as multi-step workflows that checkpoint after every step, can be paused (by the owner, low RAM, Ollama down, Ctrl-C) and resumed from the last finished step — with agent slots enforced across processes and every event on one stream.

**Architecture:** Builds on Phase 1a. `Bus` publishes topics into the existing hash-chained audit log. `Scheduler` hands out agent slots via `fcntl.flock` lock files (works across processes) and wakes/idles agents through `ContextStore`. `Workflow` wraps LangGraph (SQLite checkpointer, separate `checkpoints.db`) behind `run`/`resume`; nothing else imports LangGraph. `JobRunner` runs a demo **plan → answer** job and maps errors to `paused` or `failed`. `ModelSocket` gains a RAM gate and `unload_all`.

**Tech Stack:** Python 3.12, LangGraph 1.x + langgraph-checkpoint-sqlite 3.x, SQLite, fcntl, Typer, pytest.

**Spec:** `docs/superpowers/specs/2026-10-12-watchtower-design.md` (§4 Bus/Scheduler/Workflow rows, §5 idle agents, §10 error handling, §12 phase 1b)

## Global Constraints

- $0 default, cloud disabled, one local model in RAM (Phase 1a constraints still hold).
- Agent slots default **1**, enforced across processes.
- RAM gate: refuse to load a model that is not already resident when free RAM < **20%** (`min_free_ram_pct`, env `WATCHTOWER_MIN_FREE_RAM_PCT`); unknown RAM reading never blocks.
- Pause takes effect **between steps**; resume only from status `paused`.
- Only `src/watchtower/engine/workflow.py` imports LangGraph.
- Exit codes: 0 done, 1 failed, 2 bad input, 3 paused.
- Files under 500 lines.

## Review Focus

1. **Ctrl-C mid-step** → job `paused`; **power loss / kill -9** → job stuck `running`, recoverable with `resume --force`; finished steps never re-run. (Task 5, Task 6, Task 7)
2. **Two terminals running jobs at once** → second waits for the slot, then pauses with `SchedulerBusy` instead of loading a second model. (Task 4)
3. **Low RAM measured while our own model is loaded** → no self-block; gate applies only to loading a non-resident model. (Task 3)
4. **Old Phase 1a database** → migrates in place, no data loss, safe if two processes start together. (Task 1)
5. **`resume` on a job that is done/running/unknown** → exit 2 with a clear message, nothing re-runs. (Task 7)

---

## File Structure

```
src/watchtower/config.py                 # MODIFY: min_free_ram_pct, agent_slots, env override
src/watchtower/engine/db.py              # MODIFY: migrations via user_version + file lock
src/watchtower/engine/jobs.py            # MODIFY: paused status, pause_requested flag
src/watchtower/engine/governor/budget.py # MODIFY: pre-call check is ">=" for tokens/seconds
src/watchtower/engine/governor/audit.py  # MODIFY: since() cursor read
src/watchtower/engine/bus.py             # CREATE: Bus over audit log
src/watchtower/engine/system.py          # CREATE: free_ram_pct()
src/watchtower/engine/model_socket.py    # MODIFY: LowMemory gate, unload_all()
src/watchtower/engine/scheduler.py       # CREATE: Scheduler, AgentSession, SchedulerBusy
src/watchtower/engine/workflow.py        # CREATE: Workflow, Step, WorkflowResult, PauseRequested
src/watchtower/engine/runner.py          # CREATE: JobRunner, RunOutcome
src/watchtower/cli.py                    # MODIFY: run via runner, pause, resume, tier check
tests/test_db.py tests/test_jobs.py tests/test_budget.py tests/test_bus.py tests/test_system.py
tests/test_model_socket.py tests/test_scheduler.py tests/test_workflow.py tests/test_runner.py tests/test_cli.py
```

---

### Task 1: Schema migrations, paused status, pause flag, budget `>=`

**Files:**
- Modify: `src/watchtower/engine/db.py`, `src/watchtower/engine/jobs.py`, `src/watchtower/engine/governor/budget.py`
- Test: `tests/test_db.py`, `tests/test_jobs.py`, `tests/test_budget.py`

**Interfaces:**
- Produces: `connect(path)` (now also migrates; `PRAGMA user_version == 2`); `Job.pause_requested: int`; `STATUSES` includes `"paused"`; `JobStore.request_pause(job_id) -> None`, `JobStore.clear_pause(job_id) -> None`, `JobStore.pause_requested(job_id) -> bool` (all `KeyError` on unknown job); `Budget.check` raises when tokens/seconds used `>=` max (usd stays `>`), `Budget.charge` raises only when `>`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_db.py`:
```python
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
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 2
    row = conn.execute("SELECT prompt, pause_requested FROM jobs WHERE id='j1'").fetchone()
    assert tuple(row) == ("keep me", 0)
    conn.close()


def test_migration_runs_once(settings):
    connect(settings.db_path).close()
    conn = connect(settings.db_path)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 2
    conn.close()
```

Append to `tests/test_jobs.py`:
```python
def test_paused_status_allowed(conn):
    store = JobStore(conn)
    job = store.create("x")
    store.set_status(job.id, "paused", "low memory")
    assert store.get(job.id).status == "paused"


def test_pause_flag_roundtrip(conn):
    store = JobStore(conn)
    job = store.create("x")
    assert store.pause_requested(job.id) is False
    store.request_pause(job.id)
    assert store.pause_requested(job.id) is True
    store.clear_pause(job.id)
    assert store.pause_requested(job.id) is False


def test_pause_flag_unknown_job(conn):
    store = JobStore(conn)
    with pytest.raises(KeyError):
        store.request_pause("nope")
    with pytest.raises(KeyError):
        store.pause_requested("nope")
```

Append to `tests/test_budget.py`:
```python
def test_check_blocks_when_exactly_at_token_cap(conn):
    b = Budget(conn)
    b.open("j", max_tokens=10, max_seconds=60, max_usd=0.0)
    b.charge("j", tokens=10)
    with pytest.raises(BudgetExceeded, match="tokens"):
        b.check("j")


def test_zero_usd_cap_still_allows_free_calls(conn):
    b = Budget(conn)
    b.open("j", max_tokens=10, max_seconds=60, max_usd=0.0)
    b.check("j")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_db.py tests/test_jobs.py tests/test_budget.py -q`
Expected: FAIL — `no such column: pause_requested`, `unknown status 'paused'`, `AttributeError: ... request_pause`, and `DID NOT RAISE` for the exact-cap test.

- [ ] **Step 3: Implement**

In `src/watchtower/engine/db.py`: remove the `PRAGMA journal_mode=WAL;` line from `SCHEMA`, rename `SCHEMA` to `SCHEMA_V1`, add `import fcntl`, and replace `connect` with:
```python
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
```

In `src/watchtower/engine/jobs.py`: set `STATUSES = {"queued", "running", "paused", "done", "failed"}`; add field `pause_requested: int` as the **last** field of `Job`; add to `JobStore`:
```python
    def request_pause(self, job_id: str) -> None:
        self._set_pause(job_id, 1)

    def clear_pause(self, job_id: str) -> None:
        self._set_pause(job_id, 0)

    def pause_requested(self, job_id: str) -> bool:
        job = self.get(job_id)
        if job is None:
            raise KeyError(job_id)
        return bool(job.pause_requested)

    def _set_pause(self, job_id: str, value: int) -> None:
        cur = self._conn.execute(
            "UPDATE jobs SET pause_requested=?, updated_at=? WHERE id=? AND user_id=? AND workspace_id=?",
            (value, now(), job_id, self._user, self._ws),
        )
        if cur.rowcount == 0:
            raise KeyError(job_id)
```
Change the `INSERT` in `create` to name its columns:
```python
        self._conn.execute(
            "INSERT INTO jobs(id, user_id, workspace_id, prompt, status, error, created_at, updated_at)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (job_id, self._user, self._ws, prompt, "queued", None, ts, ts),
        )
```

In `src/watchtower/engine/governor/budget.py` replace `charge`'s final line and `check` with:
```python
        self._enforce(job_id, before_call=False)

    def check(self, job_id: str) -> None:
        """Before a call: no room left (tokens/seconds at cap) means stop. USD cap 0 still allows free calls."""
        self._enforce(job_id, before_call=True)

    def _enforce(self, job_id: str, before_call: bool) -> None:
        u = self.usage(job_id)
        for name in ("tokens", "seconds", "usd"):
            used, cap = u[f"used_{name}"], u[f"max_{name}"]
            at_cap = before_call and name != "usd" and used >= cap
            if used > cap or at_cap:
                raise BudgetExceeded(f"budget exceeded: {name} used {used} of max {cap}")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest -q`
Expected: all pass (59 previous + 7 new = 66)

- [ ] **Step 5: Commit**

```bash
git add src tests
git commit -m "feat(engine): schema migrations, paused status, pause flag, budget at-cap check"
```

---

### Task 2: Bus over the audit log

**Files:**
- Modify: `src/watchtower/engine/governor/audit.py`
- Create: `src/watchtower/engine/bus.py`, `tests/test_bus.py`

**Interfaces:**
- Consumes: `AuditLog`, `AuditEntry` (Phase 1a).
- Produces: `AuditLog.since(seq: int = 0, job_id: str | None = None, actor: str | None = None, limit: int = 500) -> list[AuditEntry]` (ascending, `seq > seq`); `Bus(audit)` with `publish(topic: str, payload: dict, job_id: str | None = None) -> int` (topic must contain a `.`, else `ValueError`) and `events(after: int = 0, job_id: str | None = None, limit: int = 500) -> list[AuditEntry]` (only `actor == "bus"`).

- [ ] **Step 1: Write the failing test**

`tests/test_bus.py`:
```python
import pytest

from watchtower.engine.bus import Bus
from watchtower.engine.governor.audit import AuditLog


def test_publish_and_read_in_order(conn):
    bus = Bus(AuditLog(conn))
    bus.publish("job.started", {"tier": "small"}, job_id="j")
    bus.publish("job.done", {}, job_id="j")
    assert [(e.action, e.detail) for e in bus.events()] == [("job.started", {"tier": "small"}), ("job.done", {})]


def test_events_cursor_and_job_filter(conn):
    audit = AuditLog(conn)
    bus = Bus(audit)
    first = bus.publish("job.started", {}, job_id="a")
    audit.append("owner", "job_created", {}, job_id="a")
    bus.publish("job.started", {}, job_id="b")
    bus.publish("job.done", {}, job_id="a")
    assert [e.action for e in bus.events(after=first)] == ["job.started", "job.done"]
    assert [e.action for e in bus.events(job_id="a")] == ["job.started", "job.done"]


def test_events_are_in_the_tamper_evident_chain(conn):
    audit = AuditLog(conn)
    Bus(audit).publish("agent.wake", {"agent": "x"})
    assert audit.verify() is True


@pytest.mark.parametrize("bad", ["", "paused", "  "])
def test_topic_must_be_namespaced(conn, bad):
    with pytest.raises(ValueError):
        Bus(AuditLog(conn)).publish(bad, {})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_bus.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'watchtower.engine.bus'`

- [ ] **Step 3: Implement**

Add to `AuditLog` in `src/watchtower/engine/governor/audit.py`:
```python
    def since(
        self, seq: int = 0, job_id: str | None = None, actor: str | None = None, limit: int = 500
    ) -> list[AuditEntry]:
        sql, args = "SELECT * FROM audit_log WHERE seq > ?", [seq]
        if job_id is not None:
            sql, args = sql + " AND job_id = ?", args + [job_id]
        if actor is not None:
            sql, args = sql + " AND actor = ?", args + [actor]
        rows = self._conn.execute(sql + " ORDER BY seq LIMIT ?", args + [limit]).fetchall()
        return [AuditEntry(**{**dict(r), "detail": json.loads(r["detail"])}) for r in rows]
```

`src/watchtower/engine/bus.py`:
```python
from __future__ import annotations

from watchtower.engine.governor.audit import AuditEntry, AuditLog


class Bus:
    """The tower's event stream. v1 writes topics into the audit log: one ordered,
    tamper-evident stream that any process (CLI now, dashboard later) can read."""

    def __init__(self, audit: AuditLog):
        self._audit = audit

    def publish(self, topic: str, payload: dict, job_id: str | None = None) -> int:
        topic = topic.strip()
        if "." not in topic:
            raise ValueError(f"topic must be namespaced like 'job.paused', got {topic!r}")
        return self._audit.append("bus", topic, payload, job_id)

    def events(self, after: int = 0, job_id: str | None = None, limit: int = 500) -> list[AuditEntry]:
        return self._audit.since(after, job_id=job_id, actor="bus", limit=limit)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest -q`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add src/watchtower/engine/bus.py src/watchtower/engine/governor/audit.py tests/test_bus.py
git commit -m "feat(engine): add bus publishing topics into the audit log"
```

---

### Task 3: RAM gate and unload_all in the Model Socket

**Files:**
- Create: `src/watchtower/engine/system.py`, `tests/test_system.py`
- Modify: `src/watchtower/config.py`, `src/watchtower/engine/model_socket.py`, `tests/test_model_socket.py`, `tests/test_cli.py`

**Interfaces:**
- Produces: `free_ram_pct(run=subprocess.run) -> int | None`; `Settings.min_free_ram_pct: int = 20`, `Settings.agent_slots: int = 1`; `load_settings()` reads `WATCHTOWER_MIN_FREE_RAM_PCT`; `LowMemory(Exception)`; `ModelSocket(..., free_ram_fn: Callable[[], int | None] | None = None)` (default `free_ram_pct`); `ModelSocket.unload_all(job_id: str | None = None) -> None`.

- [ ] **Step 1: Write the failing tests**

`tests/test_system.py`:
```python
import subprocess
from types import SimpleNamespace

from watchtower.engine.system import free_ram_pct


def test_parses_memory_pressure():
    out = "The system has 8589934592 (2097152 pages)...\nSystem-wide memory free percentage: 41%\n"
    assert free_ram_pct(run=lambda *a, **k: SimpleNamespace(stdout=out)) == 41


def test_unreadable_output_is_none():
    assert free_ram_pct(run=lambda *a, **k: SimpleNamespace(stdout="garbage")) is None


def test_missing_tool_is_none():
    def missing(*a, **k):
        raise FileNotFoundError("memory_pressure")

    assert free_ram_pct(run=missing) is None


def test_timeout_is_none():
    def slow(*a, **k):
        raise subprocess.TimeoutExpired("memory_pressure", 10)

    assert free_ram_pct(run=slow) is None
```

Append to `tests/test_db.py`:
```python
def test_min_free_ram_env_override(tmp_path, monkeypatch):
    monkeypatch.setenv("WATCHTOWER_HOME", str(tmp_path))
    monkeypatch.setenv("WATCHTOWER_MIN_FREE_RAM_PCT", "99")
    assert load_settings().min_free_ram_pct == 99
```

In `tests/test_model_socket.py`, change `make()` so it passes `free_ram_fn=lambda: 100` (add the line after `resident_fn=...`). In `test_passes_remaining_budget_as_hard_limits` and `test_unloads_models_left_resident_by_other_processes`, add `free_ram_fn=lambda: 100` to the `ModelSocket(...)` call. Then append:
```python
from watchtower.engine.model_socket import LowMemory


def low_ram_socket(parts, resident, pct, unloaded=None, calls=None):
    settings, budget, audit = parts
    return ModelSocket(
        settings, budget, audit,
        completion_fn=lambda **kw: (calls.append(kw) if calls is not None else None) or fake_response(),
        unload_fn=(unloaded.append if unloaded is not None else lambda m: None),
        resident_fn=lambda: list(resident),
        free_ram_fn=lambda: pct,
    )


def test_low_memory_blocks_loading_a_new_model(parts):
    calls = []
    sock = low_ram_socket(parts, resident=[], pct=10, calls=calls)
    with pytest.raises(LowMemory, match="10%"):
        sock.ask("small", [{"role": "user", "content": "x"}], "j")
    assert calls == []


def test_low_memory_ignored_when_model_already_resident(parts):
    sock = low_ram_socket(parts, resident=["ollama/llama3.2:3b"], pct=10)
    assert sock.ask("small", [{"role": "user", "content": "x"}], "j").text == "hi"


def test_unknown_ram_does_not_block(parts):
    sock = low_ram_socket(parts, resident=[], pct=None)
    assert sock.ask("small", [{"role": "user", "content": "x"}], "j").text == "hi"


def test_unload_all_frees_every_resident_model(parts):
    unloaded = []
    sock = low_ram_socket(parts, resident=["ollama/a", "ollama/b"], pct=100, unloaded=unloaded)
    sock.unload_all("j")
    assert unloaded == ["ollama/a", "ollama/b"]
    assert sock.loaded is None
```

In `tests/test_cli.py`, change `use_completion` so the socket gets `resident_fn=lambda: [], free_ram_fn=lambda: 100`:
```python
def use_completion(monkeypatch, fn):
    monkeypatch.setattr(
        cli, "build_socket",
        lambda s, b, a: ModelSocket(s, b, a, completion_fn=fn, unload_fn=lambda m: None,
                                    resident_fn=lambda: [], free_ram_fn=lambda: 100),
    )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest -q`
Expected: FAIL — `No module named 'watchtower.engine.system'`, `unexpected keyword argument 'free_ram_fn'`, `cannot import name 'LowMemory'`, `no attribute 'min_free_ram_pct'`.

- [ ] **Step 3: Implement**

`src/watchtower/engine/system.py`:
```python
from __future__ import annotations

import re
import subprocess

_FREE = re.compile(r"free percentage:\s*(\d+)%")


def free_ram_pct(run=subprocess.run) -> int | None:
    """System-wide free memory % from macOS `memory_pressure`; None if it cannot be read."""
    try:
        out = run(["memory_pressure"], capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    match = _FREE.search(out or "")
    return int(match.group(1)) if match else None
```

In `src/watchtower/config.py` add to `Settings` (after `default_max_usd`):
```python
    min_free_ram_pct: int = 20
    agent_slots: int = 1
```
and make `load_settings` return:
```python
    return Settings(
        home=home,
        tiers=dict(DEFAULT_TIERS),
        min_free_ram_pct=int(os.environ.get("WATCHTOWER_MIN_FREE_RAM_PCT", 20)),
    )
```

In `src/watchtower/engine/model_socket.py`:
- add `from watchtower.engine.system import free_ram_pct` and:
```python
class LowMemory(Exception):
    pass
```
- add constructor parameter `free_ram_fn: Callable[[], int | None] | None = None,` after `resident_fn`, and `self._free_ram = free_ram_fn or free_ram_pct` in the body.
- replace `_swap_to` with:
```python
    def _swap_to(self, model: str, job_id: str) -> None:
        """Unload every other resident local model, then refuse to load a new one into low RAM."""
        resident = self._resident_safe(job_id)
        for other in resident:
            if other != model:
                self._unload_safe(other, job_id)
        if model not in resident:
            pct = self._free_ram()
            if pct is not None and pct < self._s.min_free_ram_pct:
                self._audit.append("model_socket", "low_memory", {"model": model, "free_pct": pct}, job_id)
                raise LowMemory(
                    f"only {pct}% RAM free (need {self._s.min_free_ram_pct}%) to load {model}; "
                    "close some apps, then resume"
                )
        self._loaded = model

    def unload_all(self, job_id: str | None = None) -> None:
        """Free RAM after a job: unload every resident local model."""
        for model in self._resident_safe(job_id):
            self._unload_safe(model, job_id)
        self._loaded = None

    def _resident_safe(self, job_id: str | None) -> list[str]:
        try:
            return self._resident()
        except Exception as e:
            self._audit.append("model_socket", "resident_check_failed", {"error": str(e)[:200]}, job_id)
            return []

    def _unload_safe(self, model: str, job_id: str | None) -> None:
        try:
            self._unload(model)
        except Exception as e:
            self._audit.append("model_socket", "unload_failed", {"model": model, "error": str(e)[:200]}, job_id)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest -q`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add src tests
git commit -m "feat(engine): RAM gate for loading models, unload_all after jobs"
```

---

### Task 4: Scheduler — cross-process agent slots, wake/idle

**Files:**
- Create: `src/watchtower/engine/scheduler.py`, `tests/test_scheduler.py`

**Interfaces:**
- Consumes: `Settings` (`home`, `agent_slots`), `ContextStore` (1a), `Bus` (Task 2).
- Produces: `SchedulerBusy(Exception)`; `AgentSession` dataclass (`agent_id: str`, `job_id: str`, `context: dict`); `Scheduler(settings, memory, bus, sleep=time.sleep, clock=time.monotonic)` with context manager `agent(agent_id: str, job_id: str, wait_seconds: float = 30.0) -> Iterator[AgentSession]`. On enter: takes a slot (waits up to `wait_seconds`, polling every 0.5 s, then `SchedulerBusy`), loads context (`{}` if none), publishes `agent.wake`. On exit (even on exception): saves `session.context`, publishes `agent.idle`, releases the slot.

- [ ] **Step 1: Write the failing test**

`tests/test_scheduler.py`:
```python
from dataclasses import replace

import pytest

from watchtower.engine.bus import Bus
from watchtower.engine.governor.audit import AuditLog
from watchtower.engine.memory import ContextStore
from watchtower.engine.scheduler import Scheduler, SchedulerBusy


@pytest.fixture
def parts(conn, settings):
    return settings, ContextStore(conn), Bus(AuditLog(conn))


def test_wake_restores_and_idle_saves_context(parts):
    settings, memory, bus = parts
    memory.save("f1.worker", "j", {"notes": ["old"]})
    sched = Scheduler(settings, memory, bus)
    with sched.agent("f1.worker", "j") as s:
        assert s.context == {"notes": ["old"]}
        s.context["notes"].append("new")
    assert memory.load("f1.worker", "j") == {"notes": ["old", "new"]}


def test_new_agent_starts_with_empty_context(parts):
    settings, memory, bus = parts
    with Scheduler(settings, memory, bus).agent("a", "j") as s:
        assert s.context == {}


def test_publishes_wake_then_idle(parts):
    settings, memory, bus = parts
    with Scheduler(settings, memory, bus).agent("a", "j"):
        pass
    assert [(e.action, e.detail) for e in bus.events(job_id="j")] == [
        ("agent.wake", {"agent": "a"}), ("agent.idle", {"agent": "a"})]


def test_context_saved_and_slot_released_on_error(parts):
    settings, memory, bus = parts
    sched = Scheduler(settings, memory, bus)
    with pytest.raises(RuntimeError):
        with sched.agent("a", "j") as s:
            s.context["half"] = True
            raise RuntimeError("boom")
    assert memory.load("a", "j") == {"half": True}
    with sched.agent("b", "j"):
        pass


def test_single_slot_blocks_second_agent(parts):
    settings, memory, bus = parts
    sched = Scheduler(settings, memory, bus, sleep=lambda s: None)
    with sched.agent("a", "j"):
        with pytest.raises(SchedulerBusy):
            with sched.agent("b", "j", wait_seconds=0):
                pass


def test_slot_is_shared_across_scheduler_instances(parts):
    settings, memory, bus = parts
    other_process = Scheduler(settings, memory, bus, sleep=lambda s: None)
    with Scheduler(settings, memory, bus).agent("a", "j"):
        with pytest.raises(SchedulerBusy):
            with other_process.agent("b", "j", wait_seconds=0):
                pass


def test_two_slots_allow_two_agents(parts):
    settings, memory, bus = parts
    sched = Scheduler(replace(settings, agent_slots=2), memory, bus)
    with sched.agent("a", "j"), sched.agent("b", "j", wait_seconds=0):
        pass


def test_waits_then_gives_up(parts):
    settings, memory, bus = parts
    ticks = iter([0.0, 0.0, 0.6, 1.2])
    slept = []
    sched = Scheduler(settings, memory, bus, sleep=slept.append, clock=lambda: next(ticks))
    with Scheduler(settings, memory, bus).agent("a", "j"):
        with pytest.raises(SchedulerBusy, match="1.0s"):
            with sched.agent("b", "j", wait_seconds=1.0):
                pass
    assert slept == [0.5, 0.5]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_scheduler.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'watchtower.engine.scheduler'`

- [ ] **Step 3: Implement**

`src/watchtower/engine/scheduler.py`:
```python
from __future__ import annotations

import fcntl
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Callable, Iterator, TextIO

from watchtower.config import Settings
from watchtower.engine.bus import Bus
from watchtower.engine.memory import ContextStore

POLL_SECONDS = 0.5


class SchedulerBusy(Exception):
    pass


@dataclass
class AgentSession:
    agent_id: str
    job_id: str
    context: dict = field(default_factory=dict)


class Scheduler:
    """Hands out agent slots (file locks, so the limit holds across processes) and
    wakes/idles agents: context is restored on wake and saved on idle."""

    def __init__(
        self,
        settings: Settings,
        memory: ContextStore,
        bus: Bus,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ):
        self._s = settings
        self._memory = memory
        self._bus = bus
        self._sleep = sleep
        self._clock = clock
        self._slot_dir = settings.home / "slots"
        self._slot_dir.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def agent(self, agent_id: str, job_id: str, wait_seconds: float = 30.0) -> Iterator[AgentSession]:
        slot = self._acquire(wait_seconds)
        try:
            session = AgentSession(agent_id, job_id, self._memory.load(agent_id, job_id) or {})
            self._bus.publish("agent.wake", {"agent": agent_id}, job_id)
            try:
                yield session
            finally:
                self._memory.save(agent_id, job_id, session.context)
                self._bus.publish("agent.idle", {"agent": agent_id}, job_id)
        finally:
            fcntl.flock(slot, fcntl.LOCK_UN)
            slot.close()

    def _acquire(self, wait_seconds: float) -> TextIO:
        deadline = self._clock() + wait_seconds
        while True:
            for i in range(self._s.agent_slots):
                handle = open(self._slot_dir / f"{i}.lock", "w")
                try:
                    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    return handle
                except BlockingIOError:
                    handle.close()
            if self._clock() >= deadline:
                raise SchedulerBusy(
                    f"all {self._s.agent_slots} agent slot(s) busy after {wait_seconds}s; "
                    "another job is running — resume this one later"
                )
            self._sleep(POLL_SECONDS)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest -q`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add src/watchtower/engine/scheduler.py tests/test_scheduler.py
git commit -m "feat(engine): add scheduler with cross-process agent slots and wake/idle"
```

---

### Task 5: Workflow — LangGraph behind run/resume with checkpoints

**Files:**
- Create: `src/watchtower/engine/workflow.py`, `tests/test_workflow.py`
- Modify: `pyproject.toml`, `uv.lock` (via `uv add`)

**Interfaces:**
- Produces: `PauseRequested(Exception)`; `Step(name: str, fn: Callable[[dict], dict])`; `WorkflowResult(status: str, data: dict, reason: str | None = None)` with status `"done"` or `"paused"`; `Workflow(steps: list[Step], checkpoint_db: Path, should_pause: Callable[[str], bool] = lambda job_id: False)` with `run(job_id: str, data: dict) -> WorkflowResult`, `resume(job_id: str) -> WorkflowResult` (`KeyError` if the job never ran), `close() -> None`. Each step receives a copy of `data` and returns keys to merge into it. Before each step, `should_pause(job_id)` is checked; `True` → `WorkflowResult("paused", data_so_far, "pause requested by owner")`. Any other exception (including `KeyboardInterrupt`) propagates; the last finished step stays checkpointed.

- [ ] **Step 1: Add dependencies**

Run: `uv add "langgraph>=1.0" "langgraph-checkpoint-sqlite>=3.0"`
Expected: `pyproject.toml` lists both; install succeeds.

- [ ] **Step 2: Write the failing test**

`tests/test_workflow.py`:
```python
import pytest

from watchtower.engine.workflow import Step, Workflow


@pytest.fixture
def db(tmp_path):
    return tmp_path / "checkpoints.db"


def counting_steps(calls, fail_b=None):
    def a(data):
        calls["a"] += 1
        return {"a": data["x"] + 1}

    def b(data):
        calls["b"] += 1
        if fail_b and fail_b["on"]:
            raise fail_b["exc"]("boom")
        return {"b": data["a"] + 1}

    return [Step("a", a), Step("b", b)]


def test_runs_steps_in_order_and_merges_data(db):
    calls = {"a": 0, "b": 0}
    wf = Workflow(counting_steps(calls), db)
    result = wf.run("j", {"x": 0})
    assert (result.status, result.data) == ("done", {"x": 0, "a": 1, "b": 2})


@pytest.mark.parametrize("exc", [RuntimeError, KeyboardInterrupt])
def test_crash_then_resume_skips_finished_steps(db, exc):
    calls = {"a": 0, "b": 0}
    fail = {"on": True, "exc": exc}
    wf = Workflow(counting_steps(calls, fail), db)
    with pytest.raises(exc):
        wf.run("j", {"x": 0})
    fail["on"] = False
    result = wf.resume("j")
    assert result.status == "done" and result.data["b"] == 2
    assert calls == {"a": 1, "b": 2}


def test_resume_in_a_new_process_uses_checkpoint(db):
    calls = {"a": 0, "b": 0}
    fail = {"on": True, "exc": RuntimeError}
    first = Workflow(counting_steps(calls, fail), db)
    with pytest.raises(RuntimeError):
        first.run("j", {"x": 5})
    first.close()
    fail["on"] = False
    second = Workflow(counting_steps(calls, fail), db)
    assert second.resume("j").data == {"x": 5, "a": 6, "b": 7}
    assert calls["a"] == 1


def test_pause_between_steps_then_resume(db):
    calls = {"a": 0, "b": 0}
    flag = {"pause": False}

    def a(data):
        calls["a"] += 1
        flag["pause"] = True
        return {"a": 1}

    def b(data):
        calls["b"] += 1
        return {"b": 2}

    wf = Workflow([Step("a", a), Step("b", b)], db, should_pause=lambda job_id: flag["pause"])
    paused = wf.run("j", {})
    assert (paused.status, paused.data, paused.reason) == ("paused", {"a": 1}, "pause requested by owner")
    assert calls == {"a": 1, "b": 0}
    flag["pause"] = False
    assert wf.resume("j").data == {"a": 1, "b": 2}
    assert calls == {"a": 1, "b": 1}


def test_jobs_are_isolated(db):
    calls = {"a": 0, "b": 0}
    wf = Workflow(counting_steps(calls), db)
    assert wf.run("one", {"x": 1}).data["b"] == 3
    assert wf.run("two", {"x": 10}).data["b"] == 12


def test_resume_unknown_job(db):
    wf = Workflow(counting_steps({"a": 0, "b": 0}), db)
    with pytest.raises(KeyError):
        wf.resume("never-ran")


@pytest.mark.parametrize("steps", [[], [Step("a", dict), Step("a", dict)]])
def test_rejects_bad_step_lists(db, steps):
    with pytest.raises(ValueError):
        Workflow(steps, db)
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/test_workflow.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'watchtower.engine.workflow'`

- [ ] **Step 4: Implement**

`src/watchtower/engine/workflow.py`:
```python
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, TypedDict

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph


class PauseRequested(Exception):
    pass


@dataclass(frozen=True)
class Step:
    name: str
    fn: Callable[[dict], dict]


@dataclass(frozen=True)
class WorkflowResult:
    status: str  # "done" | "paused"
    data: dict
    reason: str | None = None


class _State(TypedDict):
    job_id: str
    data: dict


class Workflow:
    """Runs steps in order and checkpoints after each one, so a crashed or paused job
    resumes from its last finished step. LangGraph stays behind this interface."""

    def __init__(
        self,
        steps: list[Step],
        checkpoint_db: Path,
        should_pause: Callable[[str], bool] = lambda job_id: False,
    ):
        names = [s.name for s in steps]
        if not steps or len(set(names)) != len(names):
            raise ValueError("workflow needs at least one step and unique step names")
        self._should_pause = should_pause
        self._conn = sqlite3.connect(checkpoint_db, check_same_thread=False)
        graph = StateGraph(_State)
        previous = START
        for step in steps:
            graph.add_node(step.name, self._node(step))
            graph.add_edge(previous, step.name)
            previous = step.name
        graph.add_edge(previous, END)
        self._graph = graph.compile(checkpointer=SqliteSaver(self._conn))

    def run(self, job_id: str, data: dict) -> WorkflowResult:
        return self._invoke({"job_id": job_id, "data": data}, job_id)

    def resume(self, job_id: str) -> WorkflowResult:
        if not self._graph.get_state(self._config(job_id)).values:
            raise KeyError(job_id)
        return self._invoke(None, job_id)

    def close(self) -> None:
        self._conn.close()

    def _node(self, step: Step):
        def node(state: _State) -> dict:
            if self._should_pause(state["job_id"]):
                raise PauseRequested("pause requested by owner")
            return {"data": {**state["data"], **step.fn(dict(state["data"]))}}

        return node

    def _invoke(self, payload: dict | None, job_id: str) -> WorkflowResult:
        config = self._config(job_id)
        try:
            out = self._graph.invoke(payload, config)
        except PauseRequested as e:
            return WorkflowResult("paused", self._graph.get_state(config).values.get("data", {}), str(e))
        return WorkflowResult("done", out["data"])

    @staticmethod
    def _config(job_id: str) -> dict:
        return {"configurable": {"thread_id": job_id}}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest -q`
Expected: all pass

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml uv.lock src/watchtower/engine/workflow.py tests/test_workflow.py
git commit -m "feat(engine): add checkpointed workflow with pause/resume (LangGraph behind interface)"
```

---

### Task 6: JobRunner — demo plan → answer job

**Files:**
- Create: `src/watchtower/engine/runner.py`, `tests/test_runner.py`

**Interfaces:**
- Consumes: `JobStore` (incl. `pause_requested`, `clear_pause`), `ModelSocket` (+ `unload_all`, `LowMemory`, `ModelUnavailable`, `CloudDisabled`), `BudgetExceeded`, `Scheduler`/`SchedulerBusy`, `Bus`, `Workflow`/`Step`.
- Produces: `RunOutcome(job_id: str, status: str, answer: str | None, reason: str | None)`; `JobRunner(settings, conn, socket, scheduler, bus)` with `start(job_id: str, tier: str) -> RunOutcome` and `resume(job_id: str, force: bool = False) -> RunOutcome` (`KeyError` unknown job, `ValueError` if status ≠ `paused`; with `force=True` a stuck `running` job is also accepted), `close() -> None`. Pause-type errors (`ModelUnavailable`, `LowMemory`, `SchedulerBusy`, `KeyboardInterrupt`, owner pause) → status `paused`, topic `job.paused`. `BudgetExceeded`, `CloudDisabled`, anything else → `failed`, topic `job.failed`. Success → `done`, topic `job.done`. Every outcome unloads models (`socket.unload_all`).

- [ ] **Step 1: Write the failing test**

`tests/test_runner.py`:
```python
import pytest

from conftest import fake_response
from watchtower.engine.bus import Bus
from watchtower.engine.governor.audit import AuditLog
from watchtower.engine.governor.budget import Budget
from watchtower.engine.jobs import JobStore
from watchtower.engine.memory import ContextStore
from watchtower.engine.model_socket import ModelSocket
from watchtower.engine.runner import JobRunner
from watchtower.engine.scheduler import Scheduler


class Model:
    """Fake completion: answers by step, can be told to fail or pause."""

    def __init__(self):
        self.calls = {"plan": 0, "answer": 0}
        self.fail_on = None
        self.on_plan = None

    def __call__(self, **kw):
        step = "plan" if "Do not answer it yet" in kw["messages"][-1]["content"] else "answer"
        self.calls[step] += 1
        if self.on_plan and step == "plan":
            self.on_plan()
        if self.fail_on == step:
            raise self.fail_exc("boom")
        return fake_response(f"{step}-text", 2, 3)


@pytest.fixture
def env(conn, settings):
    audit = AuditLog(conn)
    bus, budget, jobs = Bus(audit), Budget(conn), JobStore(conn)
    model, unloaded = Model(), []
    socket = ModelSocket(settings, budget, audit, completion_fn=model, unload_fn=unloaded.append,
                         resident_fn=lambda: ["ollama/llama3.2:3b"], free_ram_fn=lambda: 100)
    runner = JobRunner(settings, conn, socket, Scheduler(settings, ContextStore(conn), bus), bus)
    job = jobs.create("what is a lighthouse?")
    budget.open(job.id, 1000, 600, 0.0)
    yield runner, jobs, bus, model, unloaded, job
    runner.close()


def topics(bus, job_id):
    return [e.action for e in bus.events(job_id=job_id) if e.action.startswith("job.")]


def test_full_run_done(env):
    runner, jobs, bus, model, unloaded, job = env
    out = runner.start(job.id, "small")
    assert (out.status, out.answer) == ("done", "answer-text")
    assert jobs.get(job.id).status == "done"
    assert topics(bus, job.id) == ["job.started", "job.done"]
    assert model.calls == {"plan": 1, "answer": 1}
    assert unloaded == ["ollama/llama3.2:3b"]


def test_ollama_down_pauses_then_resume_skips_plan(env):
    runner, jobs, bus, model, unloaded, job = env
    model.fail_on, model.fail_exc = "answer", ConnectionError
    out = runner.start(job.id, "small")
    assert out.status == "paused" and "ollama pull" in out.reason
    assert jobs.get(job.id).status == "paused"
    model.fail_on = None
    assert runner.resume(job.id).answer == "answer-text"
    assert model.calls == {"plan": 1, "answer": 2}
    assert topics(bus, job.id) == ["job.started", "job.paused", "job.resumed", "job.done"]


def test_owner_pause_takes_effect_after_current_step(env):
    runner, jobs, bus, model, unloaded, job = env
    model.on_plan = lambda: jobs.request_pause(job.id)
    out = runner.start(job.id, "small")
    assert (out.status, out.reason) == ("paused", "pause requested by owner")
    assert model.calls == {"plan": 1, "answer": 0}
    assert runner.resume(job.id).status == "done"
    assert jobs.pause_requested(job.id) is False


def test_ctrl_c_pauses(env):
    runner, jobs, bus, model, unloaded, job = env
    model.fail_on, model.fail_exc = "plan", KeyboardInterrupt
    out = runner.start(job.id, "small")
    assert (out.status, out.reason) == ("paused", "interrupted by owner")


def test_budget_exceeded_fails(env, conn):
    runner, jobs, bus, model, unloaded, job = env
    tight = jobs.create("x")
    Budget(conn).open(tight.id, 4, 600, 0.0)
    out = runner.start(tight.id, "small")
    assert out.status == "failed" and "budget exceeded" in out.reason
    assert topics(bus, tight.id) == ["job.started", "job.failed"]


def test_any_completion_error_pauses_not_fails(env):
    runner, jobs, bus, model, unloaded, job = env
    model.fail_on, model.fail_exc = "plan", ValueError
    assert runner.start(job.id, "small").status == "paused"  # socket wraps completion errors as ModelUnavailable


def test_resume_requires_paused(env):
    runner, jobs, bus, model, unloaded, job = env
    runner.start(job.id, "small")
    with pytest.raises(ValueError, match="done"):
        runner.resume(job.id)
    with pytest.raises(KeyError):
        runner.resume("nope")


def test_force_resume_recovers_job_stuck_running(env):
    runner, jobs, bus, model, unloaded, job = env
    model.fail_on, model.fail_exc = "answer", ConnectionError
    runner.start(job.id, "small")
    jobs.set_status(job.id, "running")  # simulate power loss mid-job
    with pytest.raises(ValueError, match="--force"):
        runner.resume(job.id)
    model.fail_on = None
    assert runner.resume(job.id, force=True).status == "done"
    assert model.calls["plan"] == 1


def test_agents_restore_context_per_step(env, conn):
    runner, jobs, bus, model, unloaded, job = env
    runner.start(job.id, "small")
    planner = ContextStore(conn).load("ground.planner", job.id)
    assert planner["messages"][-1] == {"role": "assistant", "content": "plan-text"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_runner.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'watchtower.engine.runner'`

- [ ] **Step 3: Implement**

`src/watchtower/engine/runner.py`:
```python
from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from watchtower.config import Settings
from watchtower.engine.bus import Bus
from watchtower.engine.governor.budget import BudgetExceeded
from watchtower.engine.jobs import JobStore
from watchtower.engine.model_socket import CloudDisabled, LowMemory, ModelSocket, ModelUnavailable
from watchtower.engine.scheduler import Scheduler, SchedulerBusy
from watchtower.engine.workflow import Step, Workflow, WorkflowResult

PLAN_PROMPT = (
    "Write a short numbered plan (max 3 steps) for answering this request. "
    "Do not answer it yet.\n\nRequest: {prompt}"
)
ANSWER_PROMPT = "Request: {prompt}\n\nPlan:\n{plan}\n\nFollow the plan and answer the request concisely."
PAUSE_ERRORS = (ModelUnavailable, LowMemory, SchedulerBusy)
FAIL_ERRORS = (BudgetExceeded, CloudDisabled)


@dataclass(frozen=True)
class RunOutcome:
    job_id: str
    status: str
    answer: str | None
    reason: str | None


class JobRunner:
    """Runs a job as a checkpointed plan → answer workflow and decides paused vs failed."""

    def __init__(self, settings: Settings, conn: sqlite3.Connection, socket: ModelSocket,
                 scheduler: Scheduler, bus: Bus):
        self._jobs = JobStore(conn)
        self._socket = socket
        self._scheduler = scheduler
        self._bus = bus
        self._wf = Workflow(
            [Step("plan", self._plan), Step("answer", self._answer)],
            settings.home / "checkpoints.db",
            should_pause=self._jobs.pause_requested,
        )

    def start(self, job_id: str, tier: str) -> RunOutcome:
        job = self._jobs.get(job_id)
        if job is None:
            raise KeyError(job_id)
        self._jobs.set_status(job_id, "running")
        self._bus.publish("job.started", {"tier": tier}, job_id)
        data = {"job_id": job_id, "prompt": job.prompt, "tier": tier}
        return self._drive(job_id, lambda: self._wf.run(job_id, data))

    def resume(self, job_id: str, force: bool = False) -> RunOutcome:
        """Resume from the last finished step. force=True also accepts a job stuck in
        'running' after power loss or kill -9 (the owner asserts its process is gone)."""
        job = self._jobs.get(job_id)
        if job is None:
            raise KeyError(job_id)
        allowed = {"paused", "running"} if force else {"paused"}
        if job.status not in allowed:
            hint = " (use --force if its process died)" if job.status == "running" else ""
            raise ValueError(f"job {job_id} is {job.status}; only paused jobs can be resumed{hint}")
        self._jobs.clear_pause(job_id)
        self._jobs.set_status(job_id, "running")
        self._bus.publish("job.resumed", {}, job_id)
        return self._drive(job_id, lambda: self._wf.resume(job_id))

    def close(self) -> None:
        self._wf.close()

    def _drive(self, job_id: str, go) -> RunOutcome:
        try:
            result: WorkflowResult = go()
        except PAUSE_ERRORS as e:
            return self._end(job_id, "paused", str(e))
        except KeyboardInterrupt:
            return self._end(job_id, "paused", "interrupted by owner")
        except FAIL_ERRORS as e:
            return self._end(job_id, "failed", str(e))
        except Exception as e:
            return self._end(job_id, "failed", f"unexpected error: {type(e).__name__}: {str(e)[:200]}")
        if result.status == "paused":
            return self._end(job_id, "paused", result.reason)
        return self._end(job_id, "done", None, result.data.get("answer"))

    def _end(self, job_id: str, status: str, reason: str | None, answer: str | None = None) -> RunOutcome:
        self._socket.unload_all(job_id)
        self._jobs.set_status(job_id, status, reason)
        self._bus.publish(f"job.{status}", {"reason": reason} if reason else {}, job_id)
        return RunOutcome(job_id, status, answer, reason)

    def _ask(self, agent_id: str, data: dict, content: str) -> str:
        with self._scheduler.agent(agent_id, data["job_id"]) as session:
            session.context["messages"] = [{"role": "user", "content": content}]
            reply = self._socket.ask(data["tier"], session.context["messages"], data["job_id"])
            session.context["messages"].append({"role": "assistant", "content": reply.text})
            return reply.text

    def _plan(self, data: dict) -> dict:
        return {"plan": self._ask("ground.planner", data, PLAN_PROMPT.format(prompt=data["prompt"]))}

    def _answer(self, data: dict) -> dict:
        content = ANSWER_PROMPT.format(prompt=data["prompt"], plan=data["plan"])
        return {"answer": self._ask("ground.answerer", data, content)}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest -q`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add src/watchtower/engine/runner.py tests/test_runner.py
git commit -m "feat(engine): add job runner for checkpointed plan→answer jobs"
```

---

### Task 7: CLI — run via runner, pause, resume, tier check

**Files:**
- Modify: `src/watchtower/cli.py`, `tests/test_cli.py`

**Interfaces:**
- Consumes: `JobRunner`, `RunOutcome` (Task 6), `Bus` (Task 2), `Scheduler` (Task 4).
- Produces: commands `run`, `status`, `logs`, `budget`, `pause <id>`, `resume <id>`; exit codes 0 done, 1 failed, 2 bad input, 3 paused. `build_socket` keeps its signature.

- [ ] **Step 1: Update and write the failing tests**

In `tests/test_cli.py`:
- In `test_run_ollama_down`: expect `result.exit_code == 3`, keep `"ollama pull" in result.output`, and assert `"paused" in runner.invoke(cli.app, ["status"]).output` instead of `"failed"`.
- In `test_logs_and_budget`: change `"job_done"` to `"job.done"` and `"tokens: 2 / 50000"` to `"tokens: 4 / 50000"` (two model calls).
- Replace `test_unexpected_error_never_leaves_job_running` with:
```python
@pytest.mark.parametrize("exc,code,status", [(KeyboardInterrupt, 3, "paused"), (RuntimeError, 1, "failed")])
def test_unexpected_error_never_leaves_job_running(monkeypatch, exc, code, status):
    class Exploding:
        def ask(self, *a, **kw):
            raise exc("boom")

        def unload_all(self, job_id=None):
            pass

    monkeypatch.setattr(cli, "build_socket", lambda s, b, a: Exploding())
    result = runner.invoke(cli.app, ["run", "hello"])
    assert result.exit_code == code
    assert runner.invoke(cli.app, ["status"]).output.split()[1] == status
    assert f"job.{status}" in runner.invoke(cli.app, ["logs"]).output
```
- Append:
```python
def latest_job_id():
    from watchtower.config import load_settings
    from watchtower.engine.db import connect
    from watchtower.engine.jobs import JobStore
    return JobStore(connect(load_settings().db_path)).list()[0].id


def test_run_rejects_unknown_tier_before_creating_job(monkeypatch):
    use_completion(monkeypatch, lambda **kw: fake_response())
    result = runner.invoke(cli.app, ["run", "hello", "--tier", "giant"])
    assert result.exit_code == 2
    assert "No jobs" in runner.invoke(cli.app, ["status"]).output


def test_paused_job_resumes_to_done(monkeypatch):
    state = {"down": True}

    def flaky(**kw):
        if state["down"]:
            raise ConnectionError("refused")
        return fake_response("final answer", 1, 1)

    use_completion(monkeypatch, flaky)
    assert runner.invoke(cli.app, ["run", "hello"]).exit_code == 3
    job_id = latest_job_id()
    state["down"] = False
    result = runner.invoke(cli.app, ["resume", job_id])
    assert result.exit_code == 0, result.output
    assert "final answer" in result.output


def test_resume_rejects_unknown_and_done_jobs(monkeypatch):
    use_completion(monkeypatch, lambda **kw: fake_response("ok", 1, 1))
    assert runner.invoke(cli.app, ["resume", "nope"]).exit_code == 2
    runner.invoke(cli.app, ["run", "hello"])
    result = runner.invoke(cli.app, ["resume", latest_job_id()])
    assert result.exit_code == 2
    assert "only paused jobs" in result.output


def test_force_resume_stuck_running_job(monkeypatch):
    state = {"down": True}

    def flaky(**kw):
        if state["down"]:
            raise ConnectionError("refused")
        return fake_response("recovered", 1, 1)

    use_completion(monkeypatch, flaky)
    runner.invoke(cli.app, ["run", "hello"])
    job_id = latest_job_id()
    from watchtower.config import load_settings
    from watchtower.engine.db import connect
    from watchtower.engine.jobs import JobStore
    JobStore(connect(load_settings().db_path)).set_status(job_id, "running")
    state["down"] = False
    assert runner.invoke(cli.app, ["resume", job_id]).exit_code == 2
    result = runner.invoke(cli.app, ["resume", job_id, "--force"])
    assert result.exit_code == 0 and "recovered" in result.output


def test_pause_requires_running_job(monkeypatch):
    use_completion(monkeypatch, lambda **kw: fake_response("ok", 1, 1))
    assert runner.invoke(cli.app, ["pause", "nope"]).exit_code == 2
    runner.invoke(cli.app, ["run", "hello"])
    result = runner.invoke(cli.app, ["pause", latest_job_id()])
    assert result.exit_code == 2
    assert "not running" in result.output


def test_pause_flags_running_job():
    from watchtower.config import load_settings
    from watchtower.engine.db import connect
    from watchtower.engine.jobs import JobStore
    store = JobStore(connect(load_settings().db_path))
    job = store.create("long job")
    store.set_status(job.id, "running")
    result = runner.invoke(cli.app, ["pause", job.id])
    assert result.exit_code == 0
    assert "after its current step" in result.output
    assert store.pause_requested(job.id) is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_cli.py -q`
Expected: FAIL — exit code 1 instead of 3 for Ollama down, `No such command 'resume'`, `No such command 'pause'`, unknown tier creates a job.

- [ ] **Step 3: Implement**

Replace `src/watchtower/cli.py` with:
```python
from __future__ import annotations

from typing import Optional

import typer

from watchtower.config import Settings, load_settings
from watchtower.engine.bus import Bus
from watchtower.engine.db import connect
from watchtower.engine.governor.audit import AuditLog
from watchtower.engine.governor.budget import Budget
from watchtower.engine.jobs import JobStore
from watchtower.engine.memory import ContextStore
from watchtower.engine.model_socket import ModelSocket
from watchtower.engine.runner import JobRunner, RunOutcome
from watchtower.engine.scheduler import Scheduler

app = typer.Typer(no_args_is_help=True, help="THE WATCHTOWER — local agentic ecosystem.")
EXIT = {"done": 0, "failed": 1, "paused": 3}


def build_socket(settings: Settings, budget: Budget, audit: AuditLog) -> ModelSocket:
    return ModelSocket(settings, budget, audit)


def _open():
    settings = load_settings()
    return settings, connect(settings.db_path)


def _runner(settings: Settings, conn) -> JobRunner:
    audit = AuditLog(conn)
    bus = Bus(audit)
    socket = build_socket(settings, Budget(conn), audit)
    return JobRunner(settings, conn, socket, Scheduler(settings, ContextStore(conn), bus), bus)


def _report(outcome: RunOutcome, conn) -> None:
    if outcome.status == "done":
        used = Budget(conn).usage(outcome.job_id)
        typer.echo(outcome.answer or "")
        typer.echo(f"\n[job {outcome.job_id} · {used['used_tokens']} tokens · ${used['used_usd']:.4f}]")
    elif outcome.status == "paused":
        typer.echo(f"Job {outcome.job_id} paused: {outcome.reason}", err=True)
        typer.echo(f"Resume with: watchtower resume {outcome.job_id}", err=True)
    else:
        typer.echo(f"Job {outcome.job_id} failed: {outcome.reason}", err=True)
    raise typer.Exit(EXIT[outcome.status])


@app.command()
def run(
    prompt: str,
    tier: str = typer.Option("small", help="Model tier: small | work | review"),
    max_tokens: Optional[int] = typer.Option(None, min=1, help="Token budget for this job"),
):
    """Run a prompt as a checkpointed plan → answer job."""
    if not prompt.strip():
        typer.echo("Error: prompt must not be empty", err=True)
        raise typer.Exit(2)
    settings, conn = _open()
    if tier not in settings.tiers:
        typer.echo(f"Error: unknown tier {tier!r}; choose from {sorted(settings.tiers)}", err=True)
        raise typer.Exit(2)
    job = JobStore(conn).create(prompt)
    Budget(conn).open(job.id, settings.default_max_tokens if max_tokens is None else max_tokens,
                      settings.default_max_seconds, settings.default_max_usd)
    AuditLog(conn).append("owner", "job_created", {"prompt": job.prompt, "tier": tier}, job.id)
    runner = _runner(settings, conn)
    try:
        outcome = runner.start(job.id, tier)
    finally:
        runner.close()
    _report(outcome, conn)


@app.command()
def pause(job_id: str):
    """Ask a running job to pause after its current step."""
    _, conn = _open()
    jobs = JobStore(conn)
    job = jobs.get(job_id)
    if job is None or job.status != "running":
        state = "unknown" if job is None else job.status
        typer.echo(f"Error: job {job_id} is not running ({state})", err=True)
        raise typer.Exit(2)
    jobs.request_pause(job_id)
    AuditLog(conn).append("owner", "pause_requested", {}, job_id)
    typer.echo(f"Pause requested; job {job_id} will pause after its current step.")


@app.command()
def resume(
    job_id: str,
    force: bool = typer.Option(False, "--force", help="Also resume a job stuck 'running' after power loss"),
):
    """Resume a paused job from its last finished step."""
    settings, conn = _open()
    runner = _runner(settings, conn)
    try:
        outcome = runner.resume(job_id, force=force)
    except KeyError:
        typer.echo(f"Error: no job {job_id}", err=True)
        raise typer.Exit(2)
    except ValueError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(2)
    finally:
        runner.close()
    _report(outcome, conn)


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
        typer.echo(f"#{e.seq} {e.ts[:19]} {e.actor:<13} {e.action:<14} {e.detail}")
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

Run: `uv run pytest -q`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add src/watchtower/cli.py tests/test_cli.py
git commit -m "feat(cli): run jobs as checkpointed workflows; add pause and resume"
```

---

### Task 8: Real smoke test with Ollama

No new code.

- [ ] **Step 1: Real two-step job**

Run: `WATCHTOWER_HOME=$PWD/.superpowers/smoke uv run watchtower run "In two sentences, why do lighthouses rotate?"`
Expected: an answer, `[job <id> · N tokens · $0.0000]`, exit 0.

- [ ] **Step 2: Model unloaded after job**

Run: `curl -s http://localhost:11434/api/ps`
Expected: `{"models":[]}`

- [ ] **Step 3: Real pause (low-RAM) and resume**

Run: `WATCHTOWER_HOME=$PWD/.superpowers/smoke WATCHTOWER_MIN_FREE_RAM_PCT=99 uv run watchtower run "What is a beacon?"`
Expected: exit 3, `paused: only N% RAM free (need 99%) ...`, `Resume with: watchtower resume <id>`.
Run: `WATCHTOWER_HOME=$PWD/.superpowers/smoke uv run watchtower resume <id>`
Expected: answer, exit 0.

- [ ] **Step 4: Inspect events**

Run: `WATCHTOWER_HOME=$PWD/.superpowers/smoke uv run watchtower logs <id>`
Expected: `job.started`, `low_memory`, `job.paused`, `job.resumed`, `agent.wake`/`agent.idle` pairs, `job.done`, `chain: ok`.

- [ ] **Step 5: Clean up and tag**

```bash
rm -rf .superpowers/smoke
git tag v0.2-phase-1b
```
