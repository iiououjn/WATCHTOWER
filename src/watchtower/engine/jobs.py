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
