"""8b: the dev floor checkpoints every attempt. A crash or pause resumes after the last finished attempt with
no re-plan and the send-back counter kept; only an owner's resume after the send-backs ran out starts afresh."""
import pytest

from runner_kit import *  # noqa: F403 — helpers and fixtures
from runner_kit import app_tower  # noqa: F401

from watchtower.engine.sandbox import SandboxUnavailable

REJECT = {"pass": False, "reasons": ["show the count of todos"], "send_back_to": "code"}
PLANNING = ("f2.architect", "cto", "f4.lead", "f4.qa", "focus")  # plan, CTO review, QA plan, F5 audit focus


def planned(model):
    calls = {role: model.calls.count(role) for role in PLANNING[:4]}
    return {**calls, "focus": sum("must verify in the finished app" in p for p in model.prompts)}


def dev_attempts(conn, job_id):
    return [e.detail["attempt"] for e in Bus(AuditLog(conn)).events(job_id=job_id, topic="gate.verdict")
            if e.detail.get("floor") == "dev"]


def crash_once_after_gate(sandbox, model, gate_calls=1):
    """Docker goes away on the first sandbox run after the gate's n-th verdict (mid-attempt), once."""
    real, state = sandbox.run, {"done": False}

    def run(job_id, command, timeout=60.0):
        if not state["done"] and model.calls.count("f5.dev_gate") == gate_calls:
            state["done"] = True
            raise SandboxUnavailable("Docker is not running; start Docker Desktop, then resume")
        return real(job_id, command, timeout)
    sandbox.run = run


def test_crash_mid_attempt_resumes_that_attempt_without_replanning(app_tower, conn):
    runner, model, sandbox, job = app_tower({"f5.dev_gate": [REJECT, {"pass": True, "reasons": []}]})
    crash_once_after_gate(sandbox, model)
    out = runner.start(job.id, extra={"auto_approve": True})
    assert out.status == "paused" and "Docker" in out.reason
    before = planned(model)
    runner._tower._known.clear()  # a new process: the memo context comes back from the checkpoint
    assert runner.resume(job.id).status == "done"
    assert planned(model) == before
    assert dev_attempts(conn, job.id) == [0, 1]  # attempt 1 re-ran; attempt 0 was kept
    assert '"entry": "app.py"' in runner._tower._known[(job.id, "f2")]
    runner.close()


def test_crash_in_the_first_attempt_keeps_the_approved_plan(app_tower, conn):
    runner, model, sandbox, job = app_tower()
    crash_once_after_gate(sandbox, model, gate_calls=0)
    assert runner.start(job.id, extra={"auto_approve": True}).status == "paused"
    before = planned(model)
    assert runner.resume(job.id).status == "done"
    assert planned(model) == before and dev_attempts(conn, job.id) == [0]
    runner.close()


def test_resume_keeps_what_the_coder_already_heard(app_tower, conn):
    # 6v: a lone model objection is sent back once; the second goes to the owner. A resume must not reset that,
    # nor the tower's server (7a owned paths) written at planning.
    from conftest import APP_REPLIES, STORE_CODER
    arch = dict(APP_REPLIES["f2.architect"][0])
    arch["routes"] = arch["routes"] + [{"method": "POST", "path": "/add", "fields": ["item"], "shows": "added"}]
    runner, model, sandbox, job = app_tower({"f2.architect": [arch], "f2.coder": STORE_CODER, "f5.dev_gate": [
        {"pass": False, "reasons": ["The user views all items in the todo list."], "send_back_to": "code"}]})
    crash_once_after_gate(sandbox, model)
    runner.start(job.id, extra={"auto_approve": True})
    out = runner.resume(job.id)
    pending = Approvals(conn).pending_for(job.id)
    assert out.status == "paused" and pending.kind == "signoff"
    assert "objected though every tower check passed" in pending.summary
    assert "the tower wrote the web server" in pending.summary  # the owned server survived the resume
    assert dev_attempts(conn, job.id) == [0, 1] and model.calls.count("f2.architect") == 1
    runner.close()


def test_owner_pause_acts_after_the_current_attempt(app_tower, conn):
    runner, model, sandbox, job = app_tower({"f5.dev_gate": [REJECT, {"pass": True, "reasons": []}]})
    real = sandbox.run

    def run(job_id, command, timeout=60.0):
        if model.calls.count("f5.dev_gate") == 0:
            JobStore(conn).request_pause(job_id)  # the owner runs `watchtower pause` during attempt 0
        return real(job_id, command, timeout)
    sandbox.run = run
    out = runner.start(job.id, extra={"auto_approve": True})
    assert out.status == "paused" and out.reason == "pause requested by owner"
    assert dev_attempts(conn, job.id) == [0]
    sandbox.run = real
    before = planned(model)
    assert runner.resume(job.id).status == "done"
    assert planned(model) == before
    assert dev_attempts(conn, job.id) == [0, 1]
    runner.close()


def test_resume_after_the_send_backs_ran_out_starts_a_fresh_round(app_tower, conn):
    runner, model, sandbox, job = app_tower(http="None")
    out = runner.start(job.id, extra={"auto_approve": True})
    assert out.status == "paused" and "reality check failed" in out.reason
    assert dev_attempts(conn, job.id) == [0, 1, 2, 3]
    assert runner.resume(job.id).status == "paused"
    assert dev_attempts(conn, job.id) == [0, 1, 2, 3] * 2
    assert model.calls.count("f2.architect") == 2
    runner.close()


@pytest.mark.parametrize("owned_first", [True, False])
def test_a_crash_in_the_qa_office_after_a_replan_resumes_with_the_new_plan(app_tower, conn, owned_first):
    # review r3: the re-plan rewrote the workspace (the tower's server dropped, or the AI's files deleted); a crash
    # before the attempt's end must not restore the old plan, owned paths and units flag against the new workspace
    from conftest import APP_REPLIES, STORE_CODER
    from watchtower.engine.runner import Terminated
    owned = dict(APP_REPLIES["f2.architect"][0])
    owned["routes"] = owned["routes"] + [{"method": "POST", "path": "/add", "fields": ["item"], "shows": "added"}]
    both = {"files": STORE_CODER[0]["files"] + APP_REPLIES["f2.coder"][0]["files"]}  # fits either plan
    runner, model, sandbox, job = app_tower({
        "f2.architect": [owned, APP_REPLIES["f2.architect"][0]][::1 if owned_first else -1], "f2.coder": [both],
        "f5.dev_gate": [{"pass": False, "reasons": ["use a plain page"], "send_back_to": "design"},
                        {"pass": True, "reasons": []}]})
    real, state = runner._socket._complete, {"done": False}

    def complete(**kw):  # the process dies in the QA office's first call after the re-plan, once
        role = kw["messages"][0]["content"].split("]")[0].removeprefix("[role:")
        if not state["done"] and role == "f4.lead" and model.calls.count("f2.architect") == 2:
            state["done"] = True
            raise Terminated("terminated by signal")
        return real(**kw)
    runner._socket._complete = complete
    out = runner.start(job.id, extra={"auto_approve": True})
    assert state["done"] and out.status == "paused"
    again = runner.resume(job.id)
    assert again.status == "done", again.reason
    assert dev_attempts(conn, job.id) == [0, 1] and model.calls.count("f2.architect") == 2
    assert model.calls.count("f4.lead") == 2  # the new plan's QA was written on resume, not the old plan's kept
    assert "app.py" in [p.name for p in (sandbox.root / job.id).iterdir()]
    runner.close()


def test_a_resume_keeps_each_floors_web_lookups_used(lookout_tower):
    # review r3: the per-floor search cap holds across a crash and resume, as it does in one run
    from watchtower.beacon.lookout import MAX_PER_FLOOR
    runner, model, sandbox, job, factory = lookout_tower(
        {"f1.lead": [{"tasks": ["todo apps"]}], "f1.worker": [{"result": "todo", "sources": []}]},
        qa_ok=[False, False, False, True])
    real, state = sandbox.run, {"done": False}

    def run(job_id, command, timeout=60.0):  # Docker goes away once, in the attempt after F4's first lookup
        if not state["done"] and any(f == "f4" for f, q in factory.calls):
            state["done"] = True
            raise SandboxUnavailable("Docker is not running; start Docker Desktop, then resume")
        return real(job_id, command, timeout)
    sandbox.run = run
    assert runner.start(job.id, extra={"auto_approve": True, "research": True}).status == "paused"
    assert runner.resume(job.id).status == "done"
    assert [f for f, q in factory.calls].count("f4") == MAX_PER_FLOOR
    runner.close()
