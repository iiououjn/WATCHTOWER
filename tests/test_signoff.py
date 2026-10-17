"""8a (audit D-M1, B-M1): --yes covers the CPO questions and the spec only. Every app is released and deployed
only after an owner approval of its sign-off; no model verdict stands in for it."""
from runner_kit import *  # noqa: F403 — helpers and fixtures

from watchtower.engine.governor.approvals import Approvals
from watchtower.floors.f4_qa_deploy.releases import Releases, manifest_of
from watchtower.tower import NeedsOwner

SPEC = {"title": "Todo", "goal": "a todo app", "acceptance": ["add a todo"], "out_of_scope": []}


def test_yes_approves_the_spec_but_the_app_waits_for_the_owner(app_tower, conn):
    runner, model, sandbox, job = app_tower()
    out = runner.start(job.id, extra={"auto_approve": True})
    pending = Approvals(conn).pending_for(job.id)
    assert out.status == "paused" and pending.kind == "signoff" and Releases(conn).get(job.id) is None
    assert "Title: " in pending.summary  # the owner never approved the spec: it is shown with the app
    Approvals(conn).decide(pending.id, True)
    assert runner.resume(job.id).status == "done" and Releases(conn).get(job.id) is not None
    runner.close()


def test_yes_with_a_silent_ceo_still_waits(app_tower, conn):
    runner, model, sandbox, job = app_tower({"ceo": ["not json"]})
    assert runner.start(job.id, extra={"auto_approve": True}).status == "paused"
    assert Approvals(conn).pending_for(job.id).kind == "signoff" and Releases(conn).get(job.id) is None
    runner.close()


def _legacy(job_id, tmp_path):
    ws = tmp_path / "legacy"
    ws.mkdir()
    (ws / "app.py").write_text("print('app')\n")
    return {"job_id": job_id, "signoff_id": None, "auto_approve": True, "workspace": str(ws), "entry": "app.py",
            "files": ["app.py"], "manifest": manifest_of(ws, ["app.py"]), "answer": "App ready", "spec": SPEC,
            "evidence": "QA: pass", "ceo": {"approve": True, "note": ""}, "objection": ""}


def test_a_checkpoint_saved_before_8a_still_needs_the_owner(app_tower, conn, tmp_path):
    runner, model, sandbox, job = app_tower()
    data, approvals = _legacy(job.id, tmp_path), Approvals(conn)
    for _ in range(2):  # resumed twice: one request, not two
        with pytest.raises(NeedsOwner, match="sign-off"):
            runner._tower._signoff(data)
    pending = approvals.pending_for(job.id)
    assert pending.kind == "signoff" and len(approvals.pending()) == 1 and Releases(conn).get(job.id) is None
    approvals.decide(pending.id, True)
    assert runner._tower._signoff(data)["released"] and Releases(conn).get(job.id) is not None
    runner.close()


PRE_8A = ("App ready in /tmp/ws\nFiles: app.py\n"
          "Run it: cd /tmp/ws && python app.py  (then open http://127.0.0.1:8000)\n"
          "Safer — deploy it isolated, with no internet: watchtower deploy {}")


def test_a_pre_8a_answer_never_tells_the_owner_to_run_the_app_on_the_host(app_tower, conn, tmp_path):
    runner, model, sandbox, job = app_tower()  # review r3: the checkpoint still holds the old host-run line
    data, approvals = {**_legacy(job.id, tmp_path), "answer": PRE_8A.format(job.id)}, Approvals(conn)
    with pytest.raises(NeedsOwner, match="sign-off"):
        runner._tower._signoff(data)
    summary = approvals.pending_for(job.id).summary
    assert "python " not in summary and "Safer" not in summary
    assert f"After you approve: watchtower deploy {job.id}" in summary
    approvals.decide(approvals.pending_for(job.id).id, True)
    answer = runner._tower._signoff(data)["answer"]  # the step's answer replaces the stored one for the CLI
    assert "python " not in answer and "Safer" not in answer
    assert f"Deploy it isolated, with no internet: watchtower deploy {job.id}" in answer and "Files: app.py" in answer
    runner.close()


def test_signed_off_needs_an_approved_signoff_row(conn):
    a = Approvals(conn)
    assert not a.signed_off("j1")
    spec = a.request("j1", "spec", "s")
    a.decide(spec, True)
    assert not a.signed_off("j1")  # an approved spec is not an approved app
    first = a.request("j1", "signoff", "app")
    assert not a.signed_off("j1")
    a.decide(first, False)
    assert not a.signed_off("j1")
    a.decide(a.request("j1", "signoff", "app again"), True)
    assert a.signed_off("j1") and not a.signed_off("j2")


def test_a_later_rejection_or_pending_signoff_withdraws_the_approval(conn):
    """8e (phase-8 minor 1): the newest sign-off row decides, not any older approved one."""
    a = Approvals(conn)
    a.decide(a.request("j1", "signoff", "app"), True)
    assert a.signed_off("j1")
    a.decide(a.request("j1", "signoff", "changed app"), False)
    assert not a.signed_off("j1")  # owner rejected the newer app: deploy must not use the old approval
    a.request("j2", "signoff", "app")
    a.decide(a.latest("j2", "signoff").id, True)
    a.request("j2", "signoff", "new request")
    assert not a.signed_off("j2")  # a fresh pending request withdraws the old approval until decided


def test_the_request_step_itself_never_skips_the_owner(app_tower, conn, tmp_path):
    runner, model, sandbox, job = app_tower()
    data = _legacy(job.id, tmp_path)  # --yes, CEO approves, no objection: once the auto sign-off case
    signoff_id = runner._tower._signoff_request(data)["signoff_id"]
    assert signoff_id is not None and Approvals(conn).get(signoff_id).kind == "signoff"
    runner.close()
