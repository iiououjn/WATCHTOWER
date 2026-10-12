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

    def since(
        self, seq: int = 0, job_id: str | None = None, actor: str | None = None, limit: int = 500,
        action: str | None = None,
    ) -> list[AuditEntry]:
        sql, args = "SELECT * FROM audit_log WHERE seq > ?", [seq]
        if action is not None:
            sql, args = sql + " AND action = ?", args + [action]
        if job_id is not None:
            sql, args = sql + " AND job_id = ?", args + [job_id]
        if actor is not None:
            sql, args = sql + " AND actor = ?", args + [actor]
        rows = self._conn.execute(sql + " ORDER BY seq LIMIT ?", args + [limit]).fetchall()
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
