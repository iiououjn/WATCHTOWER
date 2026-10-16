"""8b: a killed or crashed run is recovered (dead owner = free job lock) and never left 'running'."""
import fcntl
import os
import signal

from runner_kit import *  # noqa: F403 — helpers and fixtures
from runner_kit import app_tower, env, topics  # noqa: F401


def test_running_job_with_a_free_lock_resumes_without_force(env):
    runner, jobs, bus, model, unloaded, job = env
    model.fail_on, model.fail_exc = "answer", ConnectionError
    runner.start(job.id, "small")
    jobs.set_status(job.id, "running")  # the process was killed (SIGKILL / jetsam): the kernel freed its lock
    model.fail_on = None
    assert runner.resume(job.id).status == "done"
    assert model.calls["plan"] == 1
    assert "job.recovered" in topics(bus, job.id)


def test_running_job_with_a_held_lock_is_never_resumed(env, settings):
    runner, jobs, bus, model, unloaded, job = env
    jobs.set_status(job.id, "running")
    (settings.home / "jobs").mkdir(exist_ok=True)
    with open(settings.home / "jobs" / f"{job.id}.lock", "w") as other:
        fcntl.flock(other, fcntl.LOCK_EX)
        with pytest.raises(ValueError, match="another process"):
            runner.resume(job.id)
    assert model.calls == {"plan": 0, "answer": 0}


def test_finished_job_still_cannot_be_resumed(env):
    runner, jobs, bus, model, unloaded, job = env
    runner.start(job.id, "small")
    with pytest.raises(ValueError, match="done"):
        runner.resume(job.id, force=True)


def test_sigterm_during_a_run_pauses_the_job(env):
    runner, jobs, bus, model, unloaded, job = env
    model.on_plan = lambda: os.kill(os.getpid(), signal.SIGTERM)
    before = signal.getsignal(signal.SIGTERM)
    out = runner.start(job.id, "small")
    assert out.status == "paused" and "terminated" in out.reason
    assert jobs.get(job.id).status == "paused"
    assert signal.getsignal(signal.SIGTERM) is before  # the handler is the run's only
    model.on_plan = None
    assert runner.resume(job.id).status == "done"


def test_sighup_during_a_run_pauses_the_job(env):
    runner, jobs, bus, model, unloaded, job = env
    model.on_plan = lambda: os.kill(os.getpid(), signal.SIGHUP)
    assert runner.start(job.id, "small").status == "paused"



def test_an_ignored_sighup_stays_ignored(env):
    # `nohup watchtower run ...`: the owner chose to outlive the terminal
    runner, jobs, bus, model, unloaded, job = env
    model.on_plan = lambda: os.kill(os.getpid(), signal.SIGHUP)
    before = signal.signal(signal.SIGHUP, signal.SIG_IGN)
    try:
        assert runner.start(job.id, "small").status == "done"
        assert signal.getsignal(signal.SIGHUP) is signal.SIG_IGN
    finally:
        signal.signal(signal.SIGHUP, before)


def test_a_locked_audit_during_unload_never_hides_the_outcome(env):
    import sqlite3
    runner, jobs, bus, model, unloaded, job = env
    socket = runner._socket

    def unload(m):
        raise ConnectionError("ollama gone")

    def append(*a, **kw):
        raise sqlite3.OperationalError("database is locked")
    socket._unload = unload
    real_end = runner._end

    def end(*a, **kw):  # the run itself is fine; only the cleanup's audit row hits a busy DB
        socket._audit.append = append
        return real_end(*a, **kw)
    runner._end = end
    assert runner.start(job.id, "small").status == "done"
    assert jobs.get(job.id).status == "done"

def test_a_failing_start_event_never_leaves_the_job_running(env):
    runner, jobs, bus, model, unloaded, job = env
    real = bus.publish

    def publish(topic, payload, job_id=None):
        if topic == "job.started":
            raise OSError("disk full")
        return real(topic, payload, job_id)

    bus.publish = publish
    assert runner.start(job.id, "small").status != "running"
    assert jobs.get(job.id).status != "running"


def test_owner_alive_reads_the_job_lock(env, settings):
    from watchtower.engine.runner import owner_alive
    runner, jobs, bus, model, unloaded, job = env
    assert owner_alive(settings.home, job.id) is False
    (settings.home / "jobs").mkdir(exist_ok=True)
    with open(settings.home / "jobs" / f"{job.id}.lock", "w") as other:
        fcntl.flock(other, fcntl.LOCK_EX)
        assert owner_alive(settings.home, job.id) is True
    assert owner_alive(settings.home, job.id) is False


def test_an_unexpected_error_pauses_with_the_error_recorded(env):
    import sqlite3
    runner, jobs, bus, model, unloaded, job = env
    real = runner._socket.ask

    def locked(*a, **kw):
        runner._socket.ask = real  # the database is busy once (A-F9), then fine again
        raise sqlite3.OperationalError("database is locked")
    runner._socket.ask = locked
    out = runner.start(job.id, "small")
    assert out.status == "paused" and out.reason.startswith("unexpected error: OperationalError: database is locked")
    error = bus.events(job_id=job.id, topic="job.error")[-1].detail
    assert error["type"] == "OperationalError" and "database is locked" in error["error"]
    assert "runner.py:" in error["where"]
    assert runner.resume(job.id).status == "done"


def test_a_busy_slot_pauses_an_advisory_role_instead_of_skipping_it(app_tower):
    # 8b (A-F10): a second job used to lose HR/QA-office/memo roles silently when the slot stayed busy
    from contextlib import contextmanager
    from watchtower.engine.advisory import ADVISORY_ERRORS
    from watchtower.engine.scheduler import SchedulerBusy
    assert SchedulerBusy not in ADVISORY_ERRORS
    runner, model, sandbox, job = app_tower()
    real = runner._scheduler.agent

    @contextmanager
    def agent(agent_id, job_id, *a, **kw):
        if agent_id == "f3.lead":  # advisory: the Build Lead's expected text
            raise SchedulerBusy("all 1 agent slot(s) busy; another job is running — resume this one later")
        with real(agent_id, job_id, *a, **kw) as session:
            yield session
    runner._scheduler.agent = agent
    out = runner.start(job.id, extra={"auto_approve": True})
    assert out.status == "paused" and "another job is running" in out.reason
    runner.close()


def test_a_job_paused_before_its_first_checkpoint_fails_on_resume(env):
    # review r4: no graph state to resume from; it must end, not pause again on a KeyError
    runner, jobs, bus, model, unloaded, job = env
    real = bus.publish

    def publish(topic, payload, job_id=None):
        if topic == "job.started":
            raise OSError("disk full")
        return real(topic, payload, job_id)

    bus.publish = publish
    assert runner.start(job.id, "small").status == "paused"
    bus.publish = real
    out = runner.resume(job.id)
    assert out.status == "failed" and "start a new job" in out.reason
    assert jobs.get(job.id).status == "failed"
    assert model.calls == {"plan": 0, "answer": 0}
