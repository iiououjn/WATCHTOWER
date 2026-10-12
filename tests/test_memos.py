import pytest

from conftest import APP_REPLIES, TOWER_REPLIES, FakeSandbox, RoleModel
from watchtower.engine.board import Board
from watchtower.engine.bus import Bus
from watchtower.engine.governor.audit import AuditLog
from watchtower.engine.governor.budget import Budget
from watchtower.engine.jobs import JobStore
from watchtower.engine.memory import ContextStore
from watchtower.engine.model_socket import ModelSocket
from watchtower.engine.runner import JobRunner
from watchtower.engine.scheduler import Scheduler

PLAN = APP_REPLIES["f2.architect"][0]


@pytest.fixture
def tower(conn, settings, tmp_path):
    audit = AuditLog(conn)
    bus = Bus(audit)

    def make(replies=None):
        model = RoleModel({**TOWER_REPLIES, **APP_REPLIES, **(replies or {})})
        socket = ModelSocket(settings, Budget(conn), audit, completion_fn=model, unload_fn=lambda m: None,
                             resident_fn=lambda: [], free_ram_fn=lambda: 100)
        runner = JobRunner(settings, conn, socket, Scheduler(settings, ContextStore(conn), bus), bus,
                           sandbox=FakeSandbox(tmp_path / "ws"))
        job = JobStore(conn).create("a todo web app", pipeline="app")
        Budget(conn).open(job.id, 300_000, 3600, 0.0)
        return runner, model, job, Board(bus)
    return make


def prompts_of(model, role):
    return [p for c, p in zip(model.calls, model.prompts) if c == role]


def test_every_floor_agent_gets_the_tower_board_brief(tower):
    runner, model, job, board = tower()
    assert runner.start(job.id, extra={"auto_approve": True}).status == "done"
    coder = prompts_of(model, "f2.coder")[0]
    assert '<untrusted source="board">' in coder and "app.py" in coder  # architect's plan is on the board
    gate = prompts_of(model, "f5.dev_gate")[0]
    assert '<untrusted source="board">' in gate and "F3 Build" in gate
    kinds = {(n["floor"], n["kind"]) for n in board.notes(job.id)}
    assert {("f2", "doing"), ("f3", "done"), ("f4", "done"), ("f5", "done")} <= kinds
    runner.close()


def test_memo_is_answered_by_the_target_floor_lead_and_shared(tower):
    runner, model, job, board = tower({
        "f2.architect": [{**PLAN, "memo": {"to": "f1", "question": "which storage did research pick?"}}],
        "f1.lead": [{"answer": "sqlite3 file storage"}]})
    runner.start(job.id, extra={"auto_approve": True})
    lead = prompts_of(model, "f1.lead")
    assert len(lead) == 1 and "which storage did research pick?" in lead[0]
    assert '<untrusted source="f2">' in lead[0]
    assert any("sqlite3 file storage" in p for p in prompts_of(model, "f2.coder"))
    assert [n for n in board.notes(job.id) if n["kind"] == "memo"][0]["floor"] == "f2"
    runner.close()


def test_memos_are_capped_per_floor_and_answers_cannot_send_memos(tower):
    memo = {"to": "f1", "question": "anything new?"}
    runner, model, job, board = tower({
        "f2.coder": [{**APP_REPLIES["f2.coder"][0], "memo": memo}],
        "f5.dev_gate": [{"pass": False, "reasons": ["again"], "send_back_to": "code"}] * 3
                       + [{"pass": True, "reasons": []}],
        "f1.lead": [{"answer": "no", "memo": {"to": "f2", "question": "loop?"}}]})
    runner.start(job.id, extra={"auto_approve": True})
    assert model.calls.count("f1.lead") == 3
    assert model.calls.count("f2.architect") == 1  # the answer's memo was never routed
    runner.close()


@pytest.mark.parametrize("memo", [{"to": "f2", "question": "self?"}, {"to": "f9", "question": "who?"},
                                  {"to": "f1", "question": ""}, "f1: hi", {"to": "f1"}])
def test_bad_memos_are_ignored(tower, memo):
    runner, model, job, board = tower({"f2.architect": [{**PLAN, "memo": memo}]})
    assert runner.start(job.id, extra={"auto_approve": True}).status == "done"
    assert "f1.lead" not in model.calls
    runner.close()


def test_roles_that_may_not_send_memos_are_ignored(tower):
    runner, model, job, board = tower({"f5.dev_gate": [{"pass": True, "reasons": [],
                                                        "memo": {"to": "f1", "question": "hi"}}]})
    runner.start(job.id, extra={"auto_approve": True})
    assert "f1.lead" not in model.calls
    runner.close()


def test_unanswerable_memo_does_not_pause_the_job(tower):
    runner, model, job, board = tower({
        "f2.architect": [{**PLAN, "memo": {"to": "f1", "question": "storage?"}}], "f1.lead": ["not json"]})
    assert runner.start(job.id, extra={"auto_approve": True}).status == "done"
    assert "no answer" in [n for n in board.notes(job.id) if n["kind"] == "memo"][0]["text"]
    runner.close()
