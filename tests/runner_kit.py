"""Shared helpers and fixtures for test_runner*.py (split from one file to stay under 500 lines)."""
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

from conftest import TOWER_REPLIES, RoleModel

from watchtower.engine.governor.approvals import Approvals

from watchtower.engine.knowledge import Knowledge

@pytest.fixture
def tower(conn, settings):
    audit = AuditLog(conn)
    bus, budget, jobs = Bus(audit), Budget(conn), JobStore(conn)

    def make(replies=None):
        model = RoleModel({**TOWER_REPLIES, **(replies or {})})
        socket = ModelSocket(settings, budget, audit, completion_fn=model, unload_fn=lambda m: None,
                             resident_fn=lambda: [], free_ram_fn=lambda: 100)
        runner = JobRunner(settings, conn, socket, Scheduler(settings, ContextStore(conn), bus), bus)
        job = jobs.create("compare lighthouse lenses", pipeline="tower")
        budget.open(job.id, 100_000, 3600, 0.0)
        return runner, model, job

    return make, jobs, bus

from watchtower.beacon.search import SearchUnavailable

class FakeBeacon:
    def __init__(self, conn, fail=False):
        self.conn, self.fail, self.tasks = conn, fail, []

    def research(self, task, job_id):
        if self.fail:
            raise SearchUnavailable("web search failed; check your internet connection, then resume")
        self.tasks.append(task)
        kb = Knowledge(self.conn)
        return [kb.add(f"{task}: Fresnel lenses web fact one.", "https://a.example/1"),
                kb.add(f"{task}: Fresnel lenses web fact two.", "https://b.example/2")]

@pytest.fixture
def online_tower(conn, settings):
    audit = AuditLog(conn)
    bus, budget, jobs = Bus(audit), Budget(conn), JobStore(conn)

    def make(beacon, replies=None):
        model = RoleModel({**TOWER_REPLIES, **(replies or {})})
        socket = ModelSocket(settings, budget, audit, completion_fn=model, unload_fn=lambda m: None,
                             resident_fn=lambda: [], free_ram_fn=lambda: 100)
        runner = JobRunner(settings, conn, socket, Scheduler(settings, ContextStore(conn), bus), bus,
                           beacon_factory=lambda ask, floor="f1": beacon)
        job = jobs.create("compare lighthouse lenses", pipeline="tower")
        budget.open(job.id, 100_000, 3600, 0.0)
        return runner, model, job

    return make

from conftest import APP_REPLIES, FakeSandbox

@pytest.fixture
def app_tower(conn, settings, tmp_path):
    audit = AuditLog(conn)
    bus, budget, jobs = Bus(audit), Budget(conn), JobStore(conn)

    def make(replies=None, **sandbox_kw):
        model = RoleModel({**TOWER_REPLIES, **APP_REPLIES, **(replies or {})})
        socket = ModelSocket(settings, budget, audit, completion_fn=model, unload_fn=lambda m: None,
                             resident_fn=lambda: [], free_ram_fn=lambda: 100)
        sandbox = FakeSandbox(tmp_path / "ws", **sandbox_kw)
        runner = JobRunner(settings, conn, socket, Scheduler(settings, ContextStore(conn), bus), bus, sandbox=sandbox)
        job = jobs.create("a todo web app", pipeline="app")
        budget.open(job.id, 200_000, 3600, 0.0)
        return runner, model, sandbox, job

    return make

def _to_signoff(app_tower, conn):
    from watchtower.engine.governor.approvals import Approvals
    runner, model, sandbox, job = app_tower()
    approvals = Approvals(conn)
    runner.start(job.id)
    approvals.decide(approvals.pending_for(job.id).id, True)
    runner.resume(job.id)
    return runner, model, sandbox, job, approvals

class LookoutFactory:
    def __init__(self, conn):
        self.conn, self.calls = conn, []

    def __call__(self, ask, floor="f1"):
        factory = self

        class B:
            def research(self, query, job_id):
                factory.calls.append((floor, query))
                kb = Knowledge(factory.conn)
                return [kb.add(("Reference for " + query + ": use send_response(200). ") * 5,
                               "https://docs.python.org/3/ref/" + floor),
                        kb.add(("Reference for " + query + ": see stackoverflow. ") * 5,
                               "https://stackoverflow.com/q/" + floor),
                        kb.add(("Reference for " + query + ": owasp says. ") * 5, "https://owasp.org/" + floor)]
        return B()

@pytest.fixture
def lookout_tower(conn, settings, tmp_path):
    audit = AuditLog(conn)
    bus, budget, jobs = Bus(audit), Budget(conn), JobStore(conn)

    def make(replies=None, **sandbox_kw):
        factory = LookoutFactory(conn)
        model = RoleModel({**TOWER_REPLIES, **APP_REPLIES, **(replies or {})})
        socket = ModelSocket(settings, budget, audit, completion_fn=model, unload_fn=lambda m: None,
                             resident_fn=lambda: [], free_ram_fn=lambda: 100)
        sandbox = FakeSandbox(tmp_path / "ws", **sandbox_kw)
        runner = JobRunner(settings, conn, socket, Scheduler(settings, ContextStore(conn), bus), bus,
                           beacon_factory=factory, sandbox=sandbox)
        job = jobs.create("a todo web app", pipeline="app")
        budget.open(job.id, 200_000, 3600, 0.0)
        return runner, model, sandbox, job, factory
    return make

ONE = {"title": "Todo", "goal": "a todo app", "acceptance": ["users can add a todo"], "out_of_scope": []}


__all__ = ['APP_REPLIES', 'Approvals', 'AuditLog', 'Budget', 'Bus', 'ContextStore', 'FakeBeacon', 'FakeSandbox', 'JobRunner', 'JobStore', 'Knowledge', 'LookoutFactory', 'Model', 'ModelSocket', 'ONE', 'RoleModel', 'Scheduler', 'SearchUnavailable', 'TOWER_REPLIES', '_to_signoff', 'app_tower', 'env', 'fake_response', 'lookout_tower', 'online_tower', 'pytest', 'topics', 'tower']
