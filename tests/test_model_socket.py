from dataclasses import replace

import pytest

from conftest import fake_response
from watchtower.engine.governor.audit import AuditLog
from watchtower.engine.governor.budget import Budget, BudgetExceeded
from watchtower.engine.model_socket import CloudDisabled, ModelSocket, ModelUnavailable


@pytest.fixture
def parts(conn, settings):
    budget = Budget(conn)
    budget.open("j", max_tokens=1000, max_seconds=600, max_usd=0.0)
    return settings, budget, AuditLog(conn)


def make(parts, completion=None, unloaded=None):
    settings, budget, audit = parts
    calls = []

    def fake_completion(**kw):
        calls.append(kw)
        return fake_response("hello", 4, 6)

    sock = ModelSocket(
        settings, budget, audit,
        completion_fn=completion or fake_completion,
        unload_fn=(unloaded.append if unloaded is not None else lambda m: None),
        resident_fn=lambda: [sock.loaded] if sock.loaded else [],
        free_ram_fn=lambda: 100,
        clock=iter([0.0, 2.0, 10.0, 12.0, 20.0, 22.0]).__next__,
    )
    return sock, calls


def test_ask_routes_tier_and_returns_reply(parts):
    sock, calls = make(parts)
    reply = sock.ask("small", [{"role": "user", "content": "hi"}], "j")
    assert reply.text == "hello"
    assert reply.model == "ollama/llama3.2:3b"
    assert (reply.prompt_tokens, reply.completion_tokens, reply.seconds, reply.usd) == (4, 6, 2.0, 0.0)
    assert calls[0]["model"] == "ollama/llama3.2:3b"
    assert calls[0]["api_base"] == "http://localhost:11434"


def test_ask_charges_budget_and_audits(parts):
    _, budget, audit = parts
    sock, _ = make(parts)
    sock.ask("small", [{"role": "user", "content": "hi"}], "j")
    assert budget.usage("j")["used_tokens"] == 10
    actions = [e.action for e in audit.entries(job_id="j")]
    assert actions == ["model_call", "model_reply"]


def test_only_one_local_model_loaded(parts):
    unloaded = []
    sock, _ = make(parts, unloaded=unloaded)
    sock.ask("small", [{"role": "user", "content": "a"}], "j")
    sock.ask("small", [{"role": "user", "content": "b"}], "j")
    assert unloaded == []
    sock.ask("work", [{"role": "user", "content": "c"}], "j")
    assert unloaded == ["ollama/llama3.2:3b"]
    assert sock.loaded == "ollama/qwen2.5-coder:3b"


def test_unknown_tier(parts):
    sock, _ = make(parts)
    with pytest.raises(ValueError, match="tier"):
        sock.ask("giant", [], "j")


def test_cloud_model_blocked_by_default(parts):
    settings, budget, audit = parts
    cloud = replace(settings, tiers={**settings.tiers, "cloud": "anthropic/claude-haiku"})
    sock, calls = make((cloud, budget, audit))
    with pytest.raises(CloudDisabled):
        sock.ask("cloud", [{"role": "user", "content": "x"}], "j")
    assert calls == []


def test_ollama_down_gives_actionable_error_and_audit(parts):
    _, _, audit = parts

    def broken(**kw):
        raise ConnectionError("Connection refused")

    sock, _ = make(parts, completion=broken)
    with pytest.raises(ModelUnavailable, match="ollama pull llama3.2:3b"):
        sock.ask("small", [{"role": "user", "content": "x"}], "j")
    assert [e.action for e in audit.entries(job_id="j")] == ["model_call", "model_error"]


def test_budget_exceeded_stops(parts):
    settings, budget, audit = parts
    budget.open("tiny", max_tokens=5, max_seconds=600, max_usd=0.0)
    sock, _ = make(parts)
    with pytest.raises(BudgetExceeded):
        sock.ask("small", [{"role": "user", "content": "x"}], "tiny")


def test_default_completion_silences_litellm_banner(monkeypatch):
    import litellm

    from watchtower.engine import model_socket

    monkeypatch.setattr(litellm, "suppress_debug_info", False)
    monkeypatch.setattr(litellm, "completion", lambda **kw: "ok")
    assert model_socket._litellm_completion(model="m", messages=[]) == "ok"
    assert litellm.suppress_debug_info is True


def test_passes_remaining_budget_as_hard_limits(conn, settings):
    budget = Budget(conn)
    budget.open("b", max_tokens=100, max_seconds=60, max_usd=0.0)
    budget.charge("b", tokens=30, seconds=10)
    calls = []
    sock = ModelSocket(settings, budget, AuditLog(conn),
                       completion_fn=lambda **kw: calls.append(kw) or fake_response("x", 1, 1),
                       unload_fn=lambda m: None, resident_fn=lambda: [],
                       free_ram_fn=lambda: 100)
    sock.ask("small", [{"role": "user", "content": "x"}], "b")
    assert calls[0]["max_tokens"] == 70
    assert calls[0]["timeout"] == 50


def test_unloads_models_left_resident_by_other_processes(parts):
    settings, budget, audit = parts
    unloaded = []
    sock = ModelSocket(settings, budget, audit, completion_fn=lambda **kw: fake_response(),
                       unload_fn=unloaded.append,
                       resident_fn=lambda: ["ollama/qwen2.5-coder:3b", "ollama/llama3.2:3b"],
                       free_ram_fn=lambda: 100)
    sock.ask("small", [{"role": "user", "content": "x"}], "j")
    assert unloaded == ["ollama/qwen2.5-coder:3b"]


@pytest.mark.parametrize("bad", [
    __import__("types").SimpleNamespace(choices=[], usage=None),
    __import__("types").SimpleNamespace(choices=None, usage=__import__("types").SimpleNamespace(
        prompt_tokens=1, completion_tokens=1)),
])
def test_malformed_response_is_model_unavailable(parts, bad):
    sock, _ = make(parts, completion=lambda **kw: bad)
    with pytest.raises(ModelUnavailable, match="malformed"):
        sock.ask("small", [{"role": "user", "content": "x"}], "j")


from watchtower.engine.model_socket import LowMemory


def low_ram_socket(parts, resident, pct, unloaded=None, calls=None):
    settings, budget, audit = parts
    return ModelSocket(
        settings, budget, audit,
        completion_fn=lambda **kw: (calls.append(kw) if calls is not None else None) or fake_response(),
        unload_fn=(unloaded.append if unloaded is not None else lambda m: None),
        resident_fn=lambda: list(resident),
        free_ram_fn=lambda: pct,
    )


def test_low_memory_blocks_loading_a_new_model(parts):
    calls = []
    sock = low_ram_socket(parts, resident=[], pct=10, calls=calls)
    with pytest.raises(LowMemory, match="10%"):
        sock.ask("small", [{"role": "user", "content": "x"}], "j")
    assert calls == []


def test_low_memory_ignored_when_model_already_resident(parts):
    sock = low_ram_socket(parts, resident=["ollama/llama3.2:3b"], pct=10)
    assert sock.ask("small", [{"role": "user", "content": "x"}], "j").text == "hi"


def test_unknown_ram_does_not_block(parts):
    sock = low_ram_socket(parts, resident=[], pct=None)
    assert sock.ask("small", [{"role": "user", "content": "x"}], "j").text == "hi"


def test_unload_all_frees_every_resident_model(parts):
    unloaded = []
    sock = low_ram_socket(parts, resident=["ollama/a", "ollama/b"], pct=100, unloaded=unloaded)
    sock.unload_all("j")
    assert unloaded == ["ollama/a", "ollama/b"]
    assert sock.loaded is None
