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


def test_a_bad_audit_row_cannot_take_the_dashboard_down(conn, settings):
    AuditLog(conn).append("bus", "good", {"x": 1}, None)
    conn.execute("INSERT INTO audit_log(ts,job_id,actor,action,detail,prev_hash,hash) VALUES('t',NULL,'a','bad','{oops','p','h')")
    conn.execute("INSERT INTO audit_log(ts,job_id,actor,action,detail,prev_hash,hash)"
                 " VALUES('t',NULL,'a','bytes',CAST(x'ff7b' AS TEXT),'p','h')")
    s = state(settings.db_path)
    assert [e["action"] for e in s["audit"]][-2:] == ["bad", "bytes"] and s["chain_ok"] is False
    assert "{oops" in s["audit"][-2]["detail"]


def test_strange_numbers_in_budget_rows_are_made_safe(conn, settings):
    job = _job(conn)
    conn.execute("INSERT INTO budgets(job_id,max_tokens,max_seconds,max_usd,used_tokens,used_seconds)"
                 " VALUES(?,?,?,0,CAST(x'00' AS BLOB),'x')", (job.id, 1, 1))
    b = state(settings.db_path)["budgets"][0]
    assert b["used_tokens"] == 0 and b["used_seconds"] == 0
    conn.execute("UPDATE budgets SET used_seconds=9e999")
    import json
    json.dumps(state(settings.db_path), allow_nan=False)  # inf must not reach the page as Infinity


def test_the_chain_check_can_be_skipped_to_save_work(conn, settings):
    AuditLog(conn).append("bus", "a", {}, None)
    assert state(settings.db_path, check_chain=False)["chain_ok"] is None


def test_a_deeply_nested_audit_detail_cannot_crash_the_page(conn, settings):
    job = _job(conn, status="running")
    deep = "[" * 200_000 + '"floor"' 
    conn.execute("INSERT INTO audit_log(ts,job_id,actor,action,detail,prev_hash,hash) VALUES('t',?,'a','agent.wake',?,'p','h')",
                 (job.id, deep))
    assert state(settings.db_path)["jobs"][0]["floor"] is None


def test_a_legacy_run_it_line_in_an_approval_summary_is_dropped_like_in_the_cli(conn, settings):
    job = _job(conn)
    Approvals(conn).request(job.id, "signoff", "Files: app.py\nRun it: cd /w && python app.py\nTitle: Todo")
    summary = state(settings.db_path)["approvals"][0]["summary"]
    assert "Run it" not in summary and "Title: Todo" in summary


def test_floor_and_agent_lookups_only_scan_a_recent_window(conn, settings, monkeypatch):
    from watchtower.dashboard import data
    monkeypatch.setattr(data, "WINDOW", 5)
    old, new = _job(conn, status="running"), _job(conn, status="running")
    log = AuditLog(conn)
    log.append("bus", "board.note", {"floor": "f1"}, old.id)
    for i in range(10):
        log.append("bus", "noise", {"i": i}, None)
    log.append("bus", "board.note", {"floor": "f3"}, new.id)
    floors = {j["id"]: j["floor"] for j in state(settings.db_path)["jobs"]}
    assert floors[new.id] == "f3" and floors[old.id] is None


def test_the_pending_approvals_list_is_capped(conn, settings):
    job = _job(conn)
    for i in range(70):
        Approvals(conn).request(job.id, "spec", f"s{i}")
    assert len(state(settings.db_path)["approvals"]) == 50


def test_both_read_only_layers_hold_on_their_own(conn, settings):
    from watchtower.dashboard.data import open_readonly
    ro = open_readonly(settings.db_path)
    assert ro.execute("PRAGMA query_only").fetchone()[0] == 1
    ro.execute("PRAGMA query_only=OFF")  # even with that layer off, the read-only open itself refuses writes
    with pytest.raises(sqlite3.OperationalError):
        ro.execute("DELETE FROM jobs")


def _deploy(conn, name, job_id, port, status="active"):
    conn.execute("INSERT INTO deployments(name,job_id,image,port,status,created_at) VALUES(?,?,?,?,?,'2026-10-17T10:00:00')",
                 (name, job_id, "img:1", port, status))


def test_active_deployments_are_listed_without_the_image(conn, settings):
    job = _job(conn)
    _deploy(conn, "todo", job.id, 8100)
    _deploy(conn, "old", job.id, 8101, status="replaced")
    deps = state(settings.db_path)["deployments"]
    assert [d["name"] for d in deps] == ["todo"]
    assert set(deps[0]) == {"name", "job_id", "port", "status", "created_at", "ended_at"}
    assert deps[0]["port"] == 8100 and deps[0]["ended_at"] is None


def test_deployment_text_is_tidied_and_the_port_is_a_number(conn, settings):
    home = str(Path.home())
    dirty = "\x1b[31m" + home + "a‮b"
    _deploy(conn, dirty + "x" * 5000, dirty, "8100; <b>", status="active")
    conn.execute("UPDATE deployments SET created_at=?", (dirty,))
    d = state(settings.db_path)["deployments"][0]
    for key in ("name", "job_id", "created_at"):
        assert "\x1b" not in d[key] and home not in d[key] and "‮" not in d[key] and len(d[key]) <= 2003
    assert d["port"] == 0


def test_the_deployments_list_is_capped(conn, settings):
    for i in range(70):
        _deploy(conn, f"app{i}", "j", 8000 + i)
    deps = state(settings.db_path)["deployments"]
    assert len(deps) == 50 and deps[0]["name"] == "app69" and deps[-1]["name"] == "app20"


def test_the_page_has_a_deployments_panel_with_text_only_127_0_0_1_port():
    from watchtower.dashboard.page import render_page
    html = render_page("n")
    assert 'id="deployments"' in html and "s.deployments" in html and "127.0.0.1:' + " in html
    assert "<a " not in html and ".href" not in html and "innerHTML" not in html
