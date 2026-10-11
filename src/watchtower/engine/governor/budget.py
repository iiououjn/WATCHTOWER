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
