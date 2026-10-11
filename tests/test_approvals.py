import pytest

from watchtower.engine.governor.approvals import Approvals


def test_request_and_pending(conn):
    a = Approvals(conn)
    aid = a.request("j1", "spec", "Title: X")
    got = a.pending_for("j1")
    assert (got.id, got.kind, got.summary, got.status) == (aid, "spec", "Title: X", "pending")
    assert [p.id for p in a.pending()] == [aid]


def test_decide_approve_and_reject(conn):
    a = Approvals(conn)
    yes, no = a.request("j1", "spec", "s"), a.request("j2", "spec", "s")
    a.decide(yes, True)
    a.decide(no, False)
    assert (a.get(yes).status, a.get(no).status) == ("approved", "rejected")
    assert a.get(yes).decided_at is not None
    assert a.pending_for("j1") is None and a.pending() == []


def test_cannot_decide_twice(conn):
    a = Approvals(conn)
    aid = a.request("j", "spec", "s")
    a.decide(aid, True)
    with pytest.raises(ValueError, match="already"):
        a.decide(aid, False)


def test_unknown_approval(conn):
    a = Approvals(conn)
    with pytest.raises(KeyError):
        a.get(999)
    with pytest.raises(KeyError):
        a.decide(999, True)
