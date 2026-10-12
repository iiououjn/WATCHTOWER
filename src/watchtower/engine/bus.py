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

    def events(self, after: int = 0, job_id: str | None = None, limit: int = 500,
               topic: str | None = None) -> list[AuditEntry]:
        return self._audit.since(after, job_id=job_id, actor="bus", limit=limit, action=topic)
