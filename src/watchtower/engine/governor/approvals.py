from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from watchtower.engine.db import now


@dataclass(frozen=True)
class Approval:
    id: int
    job_id: str
    kind: str
    summary: str
    status: str  # pending | approved | rejected
    created_at: str
    decided_at: str | None


class Approvals:
    """The owner's approval queue. A job waiting on approval is paused, never blocked."""

    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def request(self, job_id: str, kind: str, summary: str) -> int:
        return self._conn.execute(
            "INSERT INTO approvals(job_id, kind, summary, status, created_at) VALUES (?,?,?,?,?)",
            (job_id, kind, summary, "pending", now()),
        ).lastrowid

    def get(self, approval_id: int) -> Approval:
        row = self._conn.execute("SELECT * FROM approvals WHERE id=?", (approval_id,)).fetchone()
        if row is None:
            raise KeyError(approval_id)
        return Approval(**dict(row))

    def pending_for(self, job_id: str) -> Approval | None:
        row = self._conn.execute(
            "SELECT * FROM approvals WHERE job_id=? AND status='pending' ORDER BY id DESC LIMIT 1", (job_id,)
        ).fetchone()
        return Approval(**dict(row)) if row else None

    def latest(self, job_id: str, kind: str) -> Approval | None:
        row = self._conn.execute("SELECT * FROM approvals WHERE job_id=? AND kind=? ORDER BY id DESC LIMIT 1",
                                 (job_id, kind)).fetchone()
        return Approval(**dict(row)) if row else None

    def signed_off(self, job_id: str) -> bool:
        """8a: the owner approved this job's finished app (not only its spec). Only `approve` sets this.
        8e: the newest sign-off row decides, so a later rejection or a fresh pending request withdraws an old approval."""
        latest = self.latest(job_id, "signoff")
        return latest is not None and latest.status == "approved"

    def pending(self) -> list[Approval]:
        rows = self._conn.execute("SELECT * FROM approvals WHERE status='pending' ORDER BY id").fetchall()
        return [Approval(**dict(r)) for r in rows]

    def decide(self, approval_id: int, approved: bool) -> None:
        cur = self._conn.execute(
            "UPDATE approvals SET status=?, decided_at=? WHERE id=? AND status='pending'",
            ("approved" if approved else "rejected", now(), approval_id),
        )
        if cur.rowcount == 0:
            existing = self.get(approval_id)
            raise ValueError(f"approval {approval_id} was already {existing.status}")
