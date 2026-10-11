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
