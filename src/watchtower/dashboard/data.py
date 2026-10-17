"""9a: what the dashboard shows, read from the tower's database through a read-only connection.
Everything returned is plain, capped and free of terminal/bidi control characters; nothing here can write."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from watchtower.engine.db import now
from watchtower.engine.governor.audit import AuditLog
from watchtower.interface.shell import clean

CAP = 2000
JOBS = 20
AUDIT = 50


def open_readonly(db_path: Path) -> sqlite3.Connection:
    """A connection that cannot write: SQLite read-only URI plus query_only. A missing file is an error, never a new DB."""
    db_path = Path(db_path)
    if not db_path.is_file():
        raise FileNotFoundError(f"no tower database at {db_path}")
    conn = sqlite3.connect(f"{db_path.resolve().as_uri()}?mode=ro", uri=True, timeout=5, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.text_factory = lambda raw: raw.decode("utf-8", "replace")  # a bad byte in one row must not take the page down
    conn.execute("PRAGMA query_only=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def _num(value: object) -> int | float:
    """A budget figure the page can draw: anything that is not a finite number becomes 0 (text, blobs, inf, nan)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value != value or value in (float("inf"), float("-inf")):
        return 0
    return value


def _tidy(value: object) -> str:
    """Untrusted text for the page: control/bidi characters out, the home folder as ~, and a hard length cap."""
    text = clean(str(value if value is not None else ""))
    home = str(Path.home())
    if home and home != "/":
        text = text.replace(home, "~")
    return text if len(text) <= CAP else text[:CAP] + "..."


def _floor_of(conn: sqlite3.Connection, job_id: str) -> str | None:
    row = conn.execute("SELECT detail FROM audit_log WHERE job_id=? AND detail LIKE '%\"floor\"%' ORDER BY seq DESC LIMIT 1",
                       (job_id,)).fetchone()
    if row is None:
        return None
    try:
        floor = json.loads(row["detail"]).get("floor")
    except (ValueError, AttributeError, RecursionError):
        return None
    return _tidy(floor) if floor else None


def _awake(conn: sqlite3.Connection, job_id: str) -> list[str]:
    awake: dict[str, bool] = {}
    rows = conn.execute("SELECT action, detail FROM audit_log WHERE job_id=? AND action IN ('agent.wake','agent.idle')"
                        " ORDER BY seq DESC LIMIT 200", (job_id,)).fetchall()
    for r in reversed(rows):
        try:
            name = _tidy(json.loads(r["detail"]).get("agent"))
        except (ValueError, AttributeError, RecursionError):
            continue
        awake[name] = r["action"] == "agent.wake"
    return sorted(n for n, on in awake.items() if on)


def _chain_ok(conn: sqlite3.Connection) -> bool:
    try:
        return AuditLog(conn).verify()
    except (sqlite3.Error, ValueError, TypeError):
        return False  # an unreadable row is exactly what a broken chain looks like


def state(db_path: Path, check_chain: bool = True) -> dict:
    conn = open_readonly(db_path)
    try:
        jobs = []
        for r in conn.execute("SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (JOBS,)).fetchall():
            running = r["status"] == "running"
            jobs.append({"id": _tidy(r["id"]), "status": _tidy(r["status"]), "prompt": _tidy(r["prompt"]),
                         "error": _tidy(r["error"]) or None, "updated_at": _tidy(r["updated_at"]),
                         "floor": _floor_of(conn, r["id"]), "awake": _awake(conn, r["id"]) if running else []})
        approvals = [{"id": r["id"], "job_id": _tidy(r["job_id"]), "kind": _tidy(r["kind"]),
                      "summary": _tidy(r["summary"]), "created_at": _tidy(r["created_at"])}
                     for r in conn.execute("SELECT * FROM approvals WHERE status='pending' ORDER BY id").fetchall()]
        audit = [{"seq": r["seq"], "ts": _tidy(r["ts"]), "job_id": _tidy(r["job_id"]) or None, "actor": _tidy(r["actor"]),
                  "action": _tidy(r["action"]), "detail": _tidy(r["detail"])}
                 for r in conn.execute("SELECT seq, ts, job_id, actor, action, detail FROM (SELECT * FROM audit_log"
                                       " ORDER BY seq DESC LIMIT ?) ORDER BY seq", (AUDIT,)).fetchall()]
        budgets = [{"job_id": _tidy(r["job_id"]), "used_tokens": _num(r["used_tokens"]), "max_tokens": _num(r["max_tokens"]),
                    "used_seconds": round(_num(r["used_seconds"]), 1), "max_seconds": _num(r["max_seconds"])}
                   for r in conn.execute("SELECT * FROM budgets WHERE job_id IN (SELECT id FROM jobs ORDER BY created_at"
                                         " DESC LIMIT ?)", (JOBS,)).fetchall()]
        return {"jobs": jobs, "approvals": approvals, "audit": audit, "budgets": budgets,
                "chain_ok": _chain_ok(conn) if check_chain else None, "now": now()}
    finally:
        conn.close()
