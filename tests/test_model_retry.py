"""8b: transient model failures (connection reset, timeout, 5xx) are retried with backoff at the socket's own
call boundary, so the retry outlives the library behind it (litellm today, httpx later)."""
import pytest

from conftest import fake_response
from watchtower.engine import model_socket
from watchtower.engine.governor.audit import AuditLog
from watchtower.engine.governor.budget import Budget, BudgetExceeded
from watchtower.engine.model_socket import ModelSocket, ModelUnavailable, transient


class APIConnectionError(Exception):  # litellm's name for a dropped connection
    pass


class ReadTimeout(APIConnectionError):  # a subclass: matched through the MRO
    pass


class Status(Exception):
    def __init__(self, code, on_response=False):
        super().__init__(f"HTTP {code}")
        if on_response:  # httpx.HTTPStatusError carries it on .response
            self.response = type("R", (), {"status_code": code})()
        else:  # litellm's errors carry it on the exception
            self.status_code = code


def socket(conn, settings, script, sleeps, budget=None):
    budget = budget or Budget(conn)
    try:
        budget.open("j", max_tokens=10_000, max_seconds=600, max_usd=0.0)
    except Exception:  # noqa: BLE001 — already open
        pass
    calls = []

    def complete(**kw):
        calls.append(kw)
        step = script.pop(0)
        if isinstance(step, BaseException):
            raise step
        return fake_response("ok", 1, 1)
    sock = ModelSocket(settings, budget, AuditLog(conn), completion_fn=complete, unload_fn=lambda m: None,
                       resident_fn=lambda: [], free_ram_fn=lambda: 100, sleep=sleeps.append)
    return sock, calls


@pytest.fixture(autouse=True)
def real_delays(monkeypatch):
    monkeypatch.setattr(model_socket, "RETRY_DELAYS", (2.0, 4.0))


@pytest.mark.parametrize("error", [ConnectionError("reset by peer"), TimeoutError("timed out"),
                                   APIConnectionError("refused"), ReadTimeout("slow"),
                                   Status(503), Status(500, on_response=True)])
def test_transient_errors_are_retried_with_backoff(conn, settings, error):
    sleeps = []
    sock, calls = socket(conn, settings, [error, error, "ok"], sleeps)
    assert sock.ask("small", [{"role": "user", "content": "x"}], "j").text == "ok"
    assert len(calls) == 3 and sleeps == [2.0, 4.0]
    actions = [e.action for e in AuditLog(conn).entries(job_id="j")]
    assert actions == ["model_call", "model_error", "model_error", "model_reply"]


def test_gives_up_after_the_last_retry(conn, settings):
    sleeps = []
    sock, calls = socket(conn, settings, [ConnectionError("down")] * 3, sleeps)
    with pytest.raises(ModelUnavailable, match="ollama pull"):
        sock.ask("small", [{"role": "user", "content": "x"}], "j")
    assert len(calls) == 3 and sleeps == [2.0, 4.0]


@pytest.mark.parametrize("error", [ValueError("bad request"), Status(404), Status(400, on_response=True),
                                   KeyError("model")])
def test_other_errors_are_not_retried(conn, settings, error):
    sleeps = []
    sock, calls = socket(conn, settings, [error, "ok"], sleeps)
    with pytest.raises(ModelUnavailable):
        sock.ask("small", [{"role": "user", "content": "x"}], "j")
    assert len(calls) == 1 and sleeps == []


def test_the_budget_is_checked_again_before_a_retry(conn, settings):
    budget, sleeps = Budget(conn), []
    budget.open("j", max_tokens=10_000, max_seconds=600, max_usd=0.0)

    class SpentError(ConnectionError):
        def __init__(self):
            budget.charge("j", seconds=600)  # the time cap ran out while the call failed
            super().__init__("reset")
    sock, calls = socket(conn, settings, [], sleeps, budget=budget)
    sock._complete = lambda **kw: (calls.append(kw), (_ for _ in ()).throw(SpentError()))
    with pytest.raises(BudgetExceeded):
        sock.ask("small", [{"role": "user", "content": "x"}], "j")
    assert len(calls) == 1


def test_classifier_reads_builtins_status_codes_and_names():
    assert transient(ConnectionResetError()) and transient(Status(502)) and transient(ReadTimeout())
    assert not transient(Status(401)) and not transient(RuntimeError("x")) and not transient(Status(None))
