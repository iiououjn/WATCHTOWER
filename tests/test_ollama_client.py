"""8d (audit E-S1, owner decision a): one direct httpx call to Ollama replaces litellm. Same response shape for
the socket, the same retry classes, and nothing leaves the Mac."""
import json
import re
import tomllib
from dataclasses import replace
from pathlib import Path

import httpx
import pytest

from watchtower.engine import ollama_client
from watchtower.engine.governor.audit import AuditLog
from watchtower.engine.governor.budget import Budget
from watchtower.engine.model_socket import CloudDisabled, ModelSocket, transient

ROOT = Path(__file__).resolve().parents[1]
REPLY = {"model": "llama3.2:3b", "message": {"role": "assistant", "content": "hello"}, "done": True,
         "prompt_eval_count": 7, "eval_count": 5}


def transport(sent, status=200, body=REPLY):
    def handle(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return httpx.Response(status, json=body)
    return httpx.MockTransport(handle)


def call(sent, **kw):
    args = dict(model="ollama/llama3.2:3b", messages=[{"role": "user", "content": "hi"}],
                api_base="http://localhost:11434", timeout=42.0, max_tokens=100, num_ctx=6144)
    via = kw.pop("transport", None) or transport(sent)
    return ollama_client.chat(**{**args, **kw}, transport=via)


def test_one_non_streaming_chat_request_with_the_call_limits():
    sent = []
    resp = call(sent)
    request = sent[0]
    assert (request.method, str(request.url)) == ("POST", "http://localhost:11434/api/chat")
    body = json.loads(request.content)
    assert body == {"model": "llama3.2:3b", "messages": [{"role": "user", "content": "hi"}], "stream": False,
                    "options": {"num_ctx": 6144, "num_predict": 100}}
    assert request.extensions["timeout"]["read"] == 42.0
    assert resp.choices[0].message.content == "hello"
    assert (resp.usage.prompt_tokens, resp.usage.completion_tokens) == (7, 5)


def test_json_mode_asks_ollama_for_json():
    sent = []
    call(sent, response_format={"type": "json_object"})
    assert json.loads(sent[0].content)["format"] == "json"


def test_missing_counts_are_zero_and_a_missing_message_reads_as_malformed():
    sent = []
    resp = call(sent, transport=transport(sent, body={"message": {"content": "x"}}))
    assert (resp.usage.prompt_tokens, resp.usage.completion_tokens) == (0, 0)
    resp = call(sent, transport=transport(sent, body={"error": "?"}))
    assert resp.choices == []  # the socket's malformed-reply path: choices[0] raises IndexError


@pytest.mark.parametrize("url", ["http://example.com:11434", "http://10.0.0.5:11434", "https://ollama.com",
                                 "http://localhost.example.com:11434", "file:///tmp/x"])
def test_only_a_loopback_ollama_is_ever_called(url):
    sent = []
    with pytest.raises(ollama_client.NotLocal):
        call(sent, api_base=url)
    with pytest.raises(ollama_client.NotLocal):
        ollama_client.resident(url, transport=transport(sent))
    with pytest.raises(ollama_client.NotLocal):
        ollama_client.unload(url, "ollama/llama3.2:3b", transport=transport(sent))
    assert sent == []


@pytest.mark.parametrize("url", ["http://localhost:11434", "http://127.0.0.1:11434", "http://[::1]:11434"])
def test_loopback_names_are_accepted(url):
    sent = []
    call(sent, api_base=url)
    assert len(sent) == 1


def test_http_errors_keep_their_retry_class():
    sent = []
    with pytest.raises(httpx.HTTPStatusError) as missing:  # model not pulled: not worth a retry
        call(sent, transport=transport(sent, 404, {"error": "model not found"}))
    with pytest.raises(httpx.HTTPStatusError) as busy:
        call(sent, transport=transport(sent, 503, {"error": "busy"}))
    refused = httpx.MockTransport(lambda r: (_ for _ in ()).throw(httpx.ConnectError("refused", request=r)))
    with pytest.raises(httpx.ConnectError) as down:
        call(sent, transport=refused)
    assert not transient(missing.value) and transient(busy.value) and transient(down.value)
    assert transient(httpx.ReadTimeout("slow"))


def test_resident_and_unload_use_the_ps_and_generate_endpoints():
    sent = []
    names = ollama_client.resident("http://localhost:11434",
                                   transport=transport(sent, body={"models": [{"name": "qwen2.5-coder:7b"}]}))
    ollama_client.unload("http://localhost:11434", "ollama/qwen2.5-coder:7b", transport=transport(sent, body={}))
    assert names == ["ollama/qwen2.5-coder:7b"]
    assert [str(r.url) for r in sent] == ["http://localhost:11434/api/ps", "http://localhost:11434/api/generate"]
    assert json.loads(sent[1].content) == {"model": "qwen2.5-coder:7b", "keep_alive": 0}


def test_the_socket_calls_ollama_directly_and_has_no_cloud_client(conn, settings):
    budget = Budget(conn)
    budget.open("j", max_tokens=100, max_seconds=60, max_usd=1.0)
    sock = ModelSocket(settings, budget, AuditLog(conn))
    assert sock._complete is ollama_client.chat
    cloud = replace(settings, cloud_enabled=True, tiers={**settings.tiers, "cloud": "anthropic/claude-haiku"})
    with pytest.raises(CloudDisabled, match="no cloud client"):
        ModelSocket(cloud, budget, AuditLog(conn), resident_fn=lambda: [], free_ram_fn=lambda: 100).ask(
            "cloud", [{"role": "user", "content": "x"}], "j")


def test_litellm_is_gone_from_the_code_and_the_dependencies():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())
    assert not any(d.startswith("litellm") for d in project["project"]["dependencies"])
    assert 'name = "litellm"' not in (ROOT / "uv.lock").read_text()
    assert not [p for p in (ROOT / "src").rglob("*.py") if re.search(r"^\s*(import|from) litellm", p.read_text(), re.M)]
