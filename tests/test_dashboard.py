"""9a: the read-only dashboard's data layer. It opens the DB read-only and returns plain, capped, tidy dicts."""
import sqlite3
from pathlib import Path

import pytest

from watchtower.dashboard.data import state
from watchtower.engine.governor.approvals import Approvals
from watchtower.engine.governor.audit import AuditLog
from watchtower.engine.governor.budget import Budget
from watchtower.engine.jobs import JobStore


def _job(conn, prompt="make a todo app", status=None):
    job = JobStore(conn).create(prompt)
    if status:
        JobStore(conn).set_status(job.id, status)
    return job


def test_state_lists_jobs_approvals_audit_and_budgets(conn, settings):
    job = _job(conn, status="paused")
    AuditLog(conn).append("bus", "board.note", {"floor": "f2", "text": "hi"}, job.id)
    Approvals(conn).request(job.id, "signoff", "Title: Todo")
    Budget(conn).open(job.id, max_tokens=1000, max_seconds=60, max_usd=0)
    s = state(settings.db_path)
    assert [j["id"] for j in s["jobs"]] == [job.id] and s["jobs"][0]["status"] == "paused"
    assert s["jobs"][0]["floor"] == "f2"
    assert [a["job_id"] for a in s["approvals"]] == [job.id] and s["approvals"][0]["kind"] == "signoff"
    assert s["audit"][-1]["action"] == "board.note" and s["chain_ok"] is True
    assert s["budgets"][0]["max_tokens"] == 1000


def test_a_job_with_no_floor_yet_is_planning(conn, settings):
    _job(conn)
    assert state(settings.db_path)["jobs"][0]["floor"] is None


def test_only_pending_approvals_are_listed(conn, settings):
    job = _job(conn)
    a = Approvals(conn)
    a.decide(a.request(job.id, "spec", "s"), True)
    assert state(settings.db_path)["approvals"] == []


def test_awake_agents_are_those_woken_and_not_yet_idle(conn, settings):
    job = _job(conn, status="running")
    log = AuditLog(conn)
    log.append("bus", "agent.wake", {"agent": "cpo"}, job.id)
    log.append("bus", "agent.wake", {"agent": "coder"}, job.id)
    log.append("bus", "agent.idle", {"agent": "cpo"}, job.id)
    assert state(settings.db_path)["jobs"][0]["awake"] == ["coder"]


def test_strings_are_capped_and_cleaned_and_home_paths_shortened(conn, settings):
    home = str(Path.home())
    _job(conn, prompt="x" * 5000 + "\x1b[31m")
    AuditLog(conn).append("bus", "note", {"path": f"{home}/secret/app.py", "bidi": "a‮b"}, None)
    s = state(settings.db_path)
    assert len(s["jobs"][0]["prompt"]) <= 2000 + 3 and "\x1b" not in s["jobs"][0]["prompt"]
    detail = s["audit"][-1]["detail"]
    assert home not in detail and "~/secret/app.py" in detail and "‮" not in detail


def test_the_connection_is_read_only(conn, settings):
    _job(conn)
    from watchtower.dashboard.data import open_readonly
    ro = open_readonly(settings.db_path)
    with pytest.raises(sqlite3.OperationalError):
        ro.execute("INSERT INTO jobs(id,user_id,workspace_id,prompt,status,created_at,updated_at) VALUES('x','u','w','p','s','t','t')")
    with pytest.raises(sqlite3.OperationalError):
        ro.execute("DELETE FROM jobs")


def test_a_tampered_audit_chain_shows_as_broken(conn, settings):
    AuditLog(conn).append("bus", "a", {}, None)
    AuditLog(conn).append("bus", "b", {}, None)
    conn.execute("DROP TRIGGER audit_no_update")
    conn.execute("UPDATE audit_log SET actor='evil' WHERE seq=1")
    assert state(settings.db_path)["chain_ok"] is False


def test_a_missing_database_is_an_error_not_a_new_empty_one(tmp_path):
    with pytest.raises(FileNotFoundError):
        state(tmp_path / "nope.db")
    assert not (tmp_path / "nope.db").exists()


def test_a_huge_audit_detail_is_capped(conn, settings):
    AuditLog(conn).append("bus", "big", {"blob": "y" * 1_000_000}, None)
    assert len(state(settings.db_path)["audit"][-1]["detail"]) <= 2003
