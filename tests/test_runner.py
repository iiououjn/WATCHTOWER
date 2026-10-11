import pytest

from conftest import fake_response
from watchtower.engine.bus import Bus
from watchtower.engine.governor.audit import AuditLog
from watchtower.engine.governor.budget import Budget
from watchtower.engine.jobs import JobStore
from watchtower.engine.memory import ContextStore
from watchtower.engine.model_socket import ModelSocket
from watchtower.engine.runner import JobRunner
from watchtower.engine.scheduler import Scheduler


class Model:
    """Fake completion: answers by step, can be told to fail or pause."""

    def __init__(self):
        self.calls = {"plan": 0, "answer": 0}
        self.fail_on = None
        self.on_plan = None

    def __call__(self, **kw):
        step = "plan" if "Do not answer it yet" in kw["messages"][-1]["content"] else "answer"
        self.calls[step] += 1
        if self.on_plan and step == "plan":
            self.on_plan()
        if self.fail_on == step:
            raise self.fail_exc("boom")
        return fake_response(f"{step}-text", 2, 3)


@pytest.fixture
def env(conn, settings):
    audit = AuditLog(conn)
    bus, budget, jobs = Bus(audit), Budget(conn), JobStore(conn)
    model, unloaded = Model(), []
    socket = ModelSocket(settings, budget, audit, completion_fn=model, unload_fn=unloaded.append,
                         resident_fn=lambda: ["ollama/llama3.2:3b"], free_ram_fn=lambda: 100)
    runner = JobRunner(settings, conn, socket, Scheduler(settings, ContextStore(conn), bus), bus)
    job = jobs.create("what is a lighthouse?")
    budget.open(job.id, 1000, 600, 0.0)
    yield runner, jobs, bus, model, unloaded, job
    runner.close()


def topics(bus, job_id):
    return [e.action for e in bus.events(job_id=job_id) if e.action.startswith("job.")]


def test_full_run_done(env):
    runner, jobs, bus, model, unloaded, job = env
    out = runner.start(job.id, "small")
    assert (out.status, out.answer) == ("done", "answer-text")
    assert jobs.get(job.id).status == "done"
    assert topics(bus, job.id) == ["job.started", "job.done"]
    assert model.calls == {"plan": 1, "answer": 1}
    assert unloaded == ["ollama/llama3.2:3b"]


def test_ollama_down_pauses_then_resume_skips_plan(env):
    runner, jobs, bus, model, unloaded, job = env
    model.fail_on, model.fail_exc = "answer", ConnectionError
    out = runner.start(job.id, "small")
    assert out.status == "paused" and "ollama pull" in out.reason
    assert jobs.get(job.id).status == "paused"
    model.fail_on = None
    assert runner.resume(job.id).answer == "answer-text"
    assert model.calls == {"plan": 1, "answer": 2}
    assert topics(bus, job.id) == ["job.started", "job.paused", "job.resumed", "job.done"]


def test_owner_pause_takes_effect_after_current_step(env):
    runner, jobs, bus, model, unloaded, job = env
    model.on_plan = lambda: jobs.request_pause(job.id)
    out = runner.start(job.id, "small")
    assert (out.status, out.reason) == ("paused", "pause requested by owner")
    assert model.calls == {"plan": 1, "answer": 0}
    assert runner.resume(job.id).status == "done"
    assert jobs.pause_requested(job.id) is False


def test_ctrl_c_pauses(env):
    runner, jobs, bus, model, unloaded, job = env
    model.fail_on, model.fail_exc = "plan", KeyboardInterrupt
    out = runner.start(job.id, "small")
    assert (out.status, out.reason) == ("paused", "interrupted by owner")


def test_budget_exceeded_fails(env, conn):
    runner, jobs, bus, model, unloaded, job = env
    tight = jobs.create("x")
    Budget(conn).open(tight.id, 4, 600, 0.0)
    out = runner.start(tight.id, "small")
    assert out.status == "failed" and "budget exceeded" in out.reason
    assert topics(bus, tight.id) == ["job.started", "job.failed"]


def test_any_completion_error_pauses_not_fails(env):
    runner, jobs, bus, model, unloaded, job = env
    model.fail_on, model.fail_exc = "plan", ValueError
    assert runner.start(job.id, "small").status == "paused"  # socket wraps completion errors as ModelUnavailable


def test_resume_requires_paused(env):
    runner, jobs, bus, model, unloaded, job = env
    runner.start(job.id, "small")
    with pytest.raises(ValueError, match="done"):
        runner.resume(job.id)
    with pytest.raises(KeyError):
        runner.resume("nope")


def test_force_resume_recovers_job_stuck_running(env):
    runner, jobs, bus, model, unloaded, job = env
    model.fail_on, model.fail_exc = "answer", ConnectionError
    runner.start(job.id, "small")
    jobs.set_status(job.id, "running")  # simulate power loss mid-job
    with pytest.raises(ValueError, match="--force"):
        runner.resume(job.id)
    model.fail_on = None
    assert runner.resume(job.id, force=True).status == "done"
    assert model.calls["plan"] == 1


def test_agents_restore_context_per_step(env, conn):
    runner, jobs, bus, model, unloaded, job = env
    runner.start(job.id, "small")
    planner = ContextStore(conn).load("ground.planner", job.id)
    assert planner["messages"][-1] == {"role": "assistant", "content": "plan-text"}
