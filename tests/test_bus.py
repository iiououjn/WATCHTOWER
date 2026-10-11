import pytest

from watchtower.engine.bus import Bus
from watchtower.engine.governor.audit import AuditLog


def test_publish_and_read_in_order(conn):
    bus = Bus(AuditLog(conn))
    bus.publish("job.started", {"tier": "small"}, job_id="j")
    bus.publish("job.done", {}, job_id="j")
    assert [(e.action, e.detail) for e in bus.events()] == [("job.started", {"tier": "small"}), ("job.done", {})]


def test_events_cursor_and_job_filter(conn):
    audit = AuditLog(conn)
    bus = Bus(audit)
    first = bus.publish("job.started", {}, job_id="a")
    audit.append("owner", "job_created", {}, job_id="a")
    bus.publish("job.started", {}, job_id="b")
    bus.publish("job.done", {}, job_id="a")
    assert [e.action for e in bus.events(after=first)] == ["job.started", "job.done"]
    assert [e.action for e in bus.events(job_id="a")] == ["job.started", "job.done"]


def test_events_are_in_the_tamper_evident_chain(conn):
    audit = AuditLog(conn)
    Bus(audit).publish("agent.wake", {"agent": "x"})
    assert audit.verify() is True


@pytest.mark.parametrize("bad", ["", "paused", "  "])
def test_topic_must_be_namespaced(conn, bad):
    with pytest.raises(ValueError):
        Bus(AuditLog(conn)).publish(bad, {})
