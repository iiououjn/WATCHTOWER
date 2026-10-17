import pytest

from watchtower.engine.governor.budget import Budget, BudgetExceeded


def test_record_within_limits(conn):
    b = Budget(conn)
    b.open("j", max_tokens=100, max_seconds=60, max_usd=0.0)
    b.record("j", tokens=40, seconds=1.5)
    u = b.usage("j")
    assert u["used_tokens"] == 40 and u["used_seconds"] == 1.5 and u["max_tokens"] == 100
    b.check("j")


def test_token_limit_exceeded_raises_and_records(conn):
    b = Budget(conn)
    b.open("j", max_tokens=10, max_seconds=60, max_usd=0.0)
    b.record("j", tokens=11)
    assert b.usage("j")["used_tokens"] == 11
    with pytest.raises(BudgetExceeded, match="tokens"):
        b.check("j")


def test_zero_usd_budget_blocks_any_spend(conn):
    b = Budget(conn)
    b.open("j", max_tokens=100, max_seconds=60, max_usd=0.0)
    b.record("j", usd=0.0001)
    with pytest.raises(BudgetExceeded, match="usd"):
        b.check("j")


def test_seconds_limit(conn):
    b = Budget(conn)
    b.open("j", max_tokens=100, max_seconds=5, max_usd=0.0)
    b.record("j", seconds=6)
    with pytest.raises(BudgetExceeded, match="seconds"):
        b.check("j")


def test_unknown_job(conn):
    with pytest.raises(KeyError):
        Budget(conn).usage("missing")


def test_check_blocks_when_exactly_at_token_cap(conn):
    b = Budget(conn)
    b.open("j", max_tokens=10, max_seconds=60, max_usd=0.0)
    b.record("j", tokens=10)
    with pytest.raises(BudgetExceeded, match="tokens"):
        b.check("j")


def test_zero_usd_cap_still_allows_free_calls(conn):
    b = Budget(conn)
    b.open("j", max_tokens=10, max_seconds=60, max_usd=0.0)
    b.check("j")
