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
