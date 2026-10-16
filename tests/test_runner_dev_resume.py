"""8b: the dev floor checkpoints every attempt. A crash or pause resumes after the last finished attempt with
no re-plan and the send-back counter kept; only an owner's resume after the send-backs ran out starts afresh."""
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
