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
    assert sock.loaded == "ollama/qwen2.5-coder:7b"


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
    assert [e.action for e in audit.entries(job_id="j")] == ["model_call"] + ["model_error"] * 3  # 8b: retried


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




def test_unload_all_only_unloads_this_process_model(parts):
    unloaded = []
    sock = low_ram_socket(parts, resident=["ollama/llama3.2:3b", "ollama/other-process"], pct=100,
                          unloaded=unloaded)
    sock.ask("small", [{"role": "user", "content": "x"}], "j")
    unloaded.clear()
    sock.unload_all("j")
    assert unloaded == ["ollama/llama3.2:3b"]


def test_unload_all_without_a_loaded_model_does_nothing(parts):
    unloaded = []
    low_ram_socket(parts, resident=["ollama/other-process"], pct=100, unloaded=unloaded).unload_all("j")
    assert unloaded == []


from watchtower.engine.model_socket import BadModelOutput, parse_json


@pytest.mark.parametrize("text,expected", [
    ('{"a": 1}', {"a": 1}),
    ('Sure! Here it is:\n```json\n{"a": 1}\n```\nHope that helps.', {"a": 1}),
    ('prefix {"a": {"b": 2}} suffix', {"a": {"b": 2}}),
])
def test_parse_json_tolerates_wrapping(text, expected):
    assert parse_json(text) == expected


@pytest.mark.parametrize("text", ["", "no json here", "[1, 2]", "{broken"])
def test_parse_json_rejects_non_objects(text):
    with pytest.raises(ValueError):
        parse_json(text)


def scripted_socket(parts, texts, calls):
    settings, budget, audit = parts
    replies = iter(texts)

    def completion(**kw):
        calls.append(kw)
        return fake_response(next(replies), 2, 2)

    return ModelSocket(settings, budget, audit, completion_fn=completion, unload_fn=lambda m: None,
                       resident_fn=lambda: [], free_ram_fn=lambda: 100)


def test_ask_json_uses_json_mode(parts):
    calls = []
    sock = scripted_socket(parts, ['{"ok": true}'], calls)
    assert sock.ask_json("small", [{"role": "user", "content": "x"}], "j") == {"ok": True}
    assert calls[0]["response_format"] == {"type": "json_object"}


def test_ask_json_retries_once_with_feedback(parts):
    calls = []
    sock = scripted_socket(parts, ["not json", '{"ok": 1}'], calls)
    assert sock.ask_json("small", [{"role": "user", "content": "x"}], "j") == {"ok": 1}
    assert "not valid JSON" in calls[1]["messages"][-1]["content"]


def test_ask_json_gives_up(parts):
    sock = scripted_socket(parts, ["nope", "still nope"], [])
    with pytest.raises(BadModelOutput, match="valid JSON"):
        sock.ask_json("small", [{"role": "user", "content": "x"}], "j")


def test_plain_ask_has_no_json_mode(parts):
    calls = []
    scripted_socket(parts, ["hi"], calls).ask("small", [{"role": "user", "content": "x"}], "j")
    assert "response_format" not in calls[0]


def test_waits_for_ram_to_settle_after_unloading(parts):
    settings, budget, audit = parts
    readings = iter([12, 15, 35])
    slept = []
    sock = ModelSocket(settings, budget, audit, completion_fn=lambda **kw: fake_response(),
                       unload_fn=lambda m: None, resident_fn=lambda: ["ollama/qwen2.5-coder:3b"],
                       free_ram_fn=lambda: next(readings), sleep=slept.append)
    assert sock.ask("small", [{"role": "user", "content": "x"}], "j").text == "hi"
    assert slept == [0.5, 0.5]


def test_gives_up_when_ram_never_settles(parts):
    settings, budget, audit = parts
    sock = ModelSocket(settings, budget, audit, completion_fn=lambda **kw: fake_response(),
                       unload_fn=lambda m: None, resident_fn=lambda: ["ollama/qwen2.5-coder:3b"],
                       free_ram_fn=lambda: 10, sleep=lambda s: None)
    with pytest.raises(LowMemory):
        sock.ask("small", [{"role": "user", "content": "x"}], "j")


def test_no_wait_when_nothing_was_unloaded(parts):
    settings, budget, audit = parts
    slept = []
    sock = ModelSocket(settings, budget, audit, completion_fn=lambda **kw: fake_response(),
                       unload_fn=lambda m: None, resident_fn=lambda: [],
                       free_ram_fn=lambda: 10, sleep=slept.append)
    with pytest.raises(LowMemory):
        sock.ask("small", [{"role": "user", "content": "x"}], "j")
    assert slept == []


def test_local_calls_set_context_window_and_cap_output(parts):
    calls = []
    parts[1].open("big", max_tokens=100_000, max_seconds=600, max_usd=0.0)
    sock = scripted_socket(parts, ['{"a": 1}'], calls)
    sock.ask("small", [{"role": "user", "content": "x"}], "big")
    assert calls[0]["num_ctx"] == 6144
    assert calls[0]["max_tokens"] == 2048


def test_json_retry_never_grows_the_context_with_the_broken_reply(parts):
    calls = []
    broken = '{"files": [{"path": "a.py", "content": "print("hi")"}]}' + "x" * 5000
    sock = scripted_socket(parts, [broken, '{"ok": 1}'], calls)
    sock.ask_json("small", [{"role": "user", "content": "write code"}], "j")
    retry = calls[1]["messages"]
    assert len(retry) == 1 and broken not in str(retry)
    assert retry[0]["content"].startswith("write code") and "escape" in retry[0]["content"]


def test_make_room_unloads_the_model_before_the_sandbox_when_ram_is_low(parts):
    unloaded, ram = [], [100]
    settings, budget, audit = parts
    sock = ModelSocket(settings, budget, audit, completion_fn=lambda **kw: fake_response(),
                       unload_fn=unloaded.append, resident_fn=lambda: [], free_ram_fn=lambda: ram[0])
    sock.ask("small", [{"role": "user", "content": "x"}], "j")
    assert sock.make_room("j") is False and unloaded == []  # plenty of RAM: keep the model warm
    ram[0] = 12
    assert sock.make_room("j") is True and unloaded == ["ollama/llama3.2:3b"] and sock.loaded is None
    assert sock.make_room("j") is False  # nothing loaded any more
    assert any(e.action == "make_room" for e in audit.entries(job_id="j"))
