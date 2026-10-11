from dataclasses import replace

import pytest

from watchtower.engine.bus import Bus
from watchtower.engine.governor.audit import AuditLog
from watchtower.engine.memory import ContextStore
from watchtower.engine.scheduler import Scheduler, SchedulerBusy


@pytest.fixture
def parts(conn, settings):
    return settings, ContextStore(conn), Bus(AuditLog(conn))


def test_wake_restores_and_idle_saves_context(parts):
    settings, memory, bus = parts
    memory.save("f1.worker", "j", {"notes": ["old"]})
    sched = Scheduler(settings, memory, bus)
    with sched.agent("f1.worker", "j") as s:
        assert s.context == {"notes": ["old"]}
        s.context["notes"].append("new")
    assert memory.load("f1.worker", "j") == {"notes": ["old", "new"]}


def test_new_agent_starts_with_empty_context(parts):
    settings, memory, bus = parts
    with Scheduler(settings, memory, bus).agent("a", "j") as s:
        assert s.context == {}


def test_publishes_wake_then_idle(parts):
    settings, memory, bus = parts
    with Scheduler(settings, memory, bus).agent("a", "j"):
        pass
    assert [(e.action, e.detail) for e in bus.events(job_id="j")] == [
        ("agent.wake", {"agent": "a"}), ("agent.idle", {"agent": "a"})]


def test_context_saved_and_slot_released_on_error(parts):
    settings, memory, bus = parts
    sched = Scheduler(settings, memory, bus)
    with pytest.raises(RuntimeError):
        with sched.agent("a", "j") as s:
            s.context["half"] = True
            raise RuntimeError("boom")
    assert memory.load("a", "j") == {"half": True}
    with sched.agent("b", "j"):
        pass


def test_single_slot_blocks_second_agent(parts):
    settings, memory, bus = parts
    sched = Scheduler(settings, memory, bus, sleep=lambda s: None)
    with sched.agent("a", "j"):
        with pytest.raises(SchedulerBusy):
            with sched.agent("b", "j", wait_seconds=0):
                pass


def test_slot_is_shared_across_scheduler_instances(parts):
    settings, memory, bus = parts
    other_process = Scheduler(settings, memory, bus, sleep=lambda s: None)
    with Scheduler(settings, memory, bus).agent("a", "j"):
        with pytest.raises(SchedulerBusy):
            with other_process.agent("b", "j", wait_seconds=0):
                pass


def test_two_slots_allow_two_agents(parts):
    settings, memory, bus = parts
    sched = Scheduler(replace(settings, agent_slots=2), memory, bus)
    with sched.agent("a", "j"), sched.agent("b", "j", wait_seconds=0):
        pass


def test_waits_then_gives_up(parts):
    settings, memory, bus = parts
    ticks = iter([0.0, 0.0, 0.6, 1.2])
    slept = []
    sched = Scheduler(settings, memory, bus, sleep=slept.append, clock=lambda: next(ticks))
    with Scheduler(settings, memory, bus).agent("a", "j"):
        with pytest.raises(SchedulerBusy, match="1.0s"):
            with sched.agent("b", "j", wait_seconds=1.0):
                pass
    assert slept == [0.5, 0.5]
