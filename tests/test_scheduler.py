from dataclasses import replace

import pytest

from watchtower.engine.bus import Bus
from watchtower.engine.governor.audit import AuditLog
from watchtower.engine.scheduler import Scheduler, SchedulerBusy


@pytest.fixture
def parts(conn, settings):
    return settings, Bus(AuditLog(conn))


def test_publishes_wake_then_idle(parts):
    settings, bus = parts
    with Scheduler(settings, bus).agent("a", "j"):
        pass
    assert [(e.action, e.detail) for e in bus.events(job_id="j")] == [
        ("agent.wake", {"agent": "a"}), ("agent.idle", {"agent": "a"})]


def test_slot_released_on_error(parts):
    settings, bus = parts
    sched = Scheduler(settings, bus)
    with pytest.raises(RuntimeError):
        with sched.agent("a", "j"):
            raise RuntimeError("boom")
    with sched.agent("b", "j", wait_seconds=0):
        pass


def test_single_slot_blocks_second_agent(parts):
    settings, bus = parts
    sched = Scheduler(settings, bus, sleep=lambda s: None)
    with sched.agent("a", "j"):
        with pytest.raises(SchedulerBusy):
            with sched.agent("b", "j", wait_seconds=0):
                pass


def test_slot_is_shared_across_scheduler_instances(parts):
    settings, bus = parts
    other_process = Scheduler(settings, bus, sleep=lambda s: None)
    with Scheduler(settings, bus).agent("a", "j"):
        with pytest.raises(SchedulerBusy):
            with other_process.agent("b", "j", wait_seconds=0):
                pass


def test_two_slots_allow_two_agents(parts):
    settings, bus = parts
    sched = Scheduler(replace(settings, agent_slots=2), bus)
    with sched.agent("a", "j"), sched.agent("b", "j", wait_seconds=0):
        pass


def test_waits_then_gives_up(parts):
    settings, bus = parts
    ticks = iter([0.0, 0.0, 0.6, 1.2])
    slept = []
    sched = Scheduler(settings, bus, sleep=slept.append, clock=lambda: next(ticks))
    with Scheduler(settings, bus).agent("a", "j"):
        with pytest.raises(SchedulerBusy, match="1.0s"):
            with sched.agent("b", "j", wait_seconds=1.0):
                pass
    assert slept == [0.5, 0.5]


def test_default_wait_outlasts_a_long_model_call(parts):
    # 8b (A-F10): model calls took 78-327 s; a 30 s wait made a second job skip or pause at once
    settings, bus = parts
    now, slept = [0.0], []

    def sleep(s):
        slept.append(s)
        now[0] += s
    sched = Scheduler(settings, bus, sleep=sleep, clock=lambda: now[0])
    with Scheduler(settings, bus).agent("a", "j"):
        with pytest.raises(SchedulerBusy, match="600"):
            with sched.agent("b", "j"):
                pass
    assert settings.slot_wait_s == 600 and sum(slept) >= 600


def test_a_failing_idle_event_never_replaces_the_real_error(parts):
    from watchtower.engine.model_socket import LowMemory
    settings, bus = parts
    real = bus.publish

    def publish(topic, payload, job_id=None):
        if topic == "agent.idle":
            raise OSError("disk full")
        return real(topic, payload, job_id)
    bus.publish = publish
    with pytest.raises(LowMemory):
        with Scheduler(settings, bus).agent("a", "j"):
            raise LowMemory("9% free")
    with Scheduler(settings, bus).agent("b", "j"):  # no error in flight: the cleanup failure is only reported
        pass
    assert [e.detail["agent"] for e in bus.events(job_id="j", topic="agent.cleanup_failed")] == ["a", "b"]


def test_an_unusable_audit_log_during_cleanup_never_replaces_the_real_error(parts):
    from watchtower.engine.model_socket import LowMemory
    settings, bus = parts
    real = bus.publish

    def publish(topic, payload, job_id=None):
        if topic in ("agent.idle", "agent.cleanup_failed"):
            raise OSError("disk full")
        return real(topic, payload, job_id)
    bus.publish = publish
    with pytest.raises(LowMemory):
        with Scheduler(settings, bus).agent("a", "j"):
            raise LowMemory("9% free")
