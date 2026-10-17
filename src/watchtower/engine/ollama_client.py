"""The tower's only model client (8d, audit E-S1): one non-streaming request to the local Ollama server.

It replaces litellm, which was a third of the install, 4.4 s of import and fetched a price file from the
internet on every run. Only a loopback Ollama is ever called, so no prompt can leave the Mac."""
from __future__ import annotations

from types import SimpleNamespace
from urllib.parse import urlsplit

import httpx

LOCAL_PREFIX = "ollama/"
LOOPBACK = {"localhost", "127.0.0.1", "::1"}


class NotLocal(ValueError):
    pass


def _base(api_base: str) -> str:
    parts = urlsplit(api_base)
    if parts.scheme not in ("http", "https") or parts.hostname not in LOOPBACK:
        raise NotLocal(f"Ollama must run on this Mac (localhost), not {api_base!r}")
    return api_base.rstrip("/")


def _client(timeout: float, transport: httpx.BaseTransport | None) -> httpx.Client:
    # review r1: trust_env=False, or HTTP_PROXY/ALL_PROXY (or the macOS system proxy) would carry prompts off the Mac
    return httpx.Client(transport=transport, timeout=timeout, trust_env=False)


def _post(url: str, body: dict, timeout: float, transport: httpx.BaseTransport | None) -> httpx.Response:
    with _client(timeout, transport) as client:
        resp = client.post(url, json=body)
    resp.raise_for_status()  # 404: model not pulled (not retried); 5xx: retried by the socket
    return resp


def chat(*, model: str, messages: list[dict], api_base: str, timeout: float, max_tokens: int | None = None,
         num_ctx: int | None = None, response_format: dict | None = None,
         transport: httpx.BaseTransport | None = None) -> SimpleNamespace:
    """One /api/chat call. Returns the shape the socket reads: choices[0].message.content and usage token counts
    (Ollama's prompt_eval_count / eval_count). A reply without a message has no choices (malformed)."""
    url = _base(api_base) + "/api/chat"
    body: dict = {"model": model.removeprefix(LOCAL_PREFIX), "messages": messages, "stream": False}
    if response_format is not None:
        body["format"] = "json"
    options = {k: v for k, v in (("num_ctx", num_ctx), ("num_predict", max_tokens)) if v is not None}
    if options:
        body["options"] = options
    data = _post(url, body, timeout, transport).json()
    message = data.get("message") if isinstance(data, dict) else None
    choices = [SimpleNamespace(message=SimpleNamespace(content=message.get("content")))] \
        if isinstance(message, dict) else []
    usage = SimpleNamespace(prompt_tokens=int(data.get("prompt_eval_count") or 0) if choices else 0,
                            completion_tokens=int(data.get("eval_count") or 0) if choices else 0)
    return SimpleNamespace(choices=choices, usage=usage)


def get(api_base: str, path: str, timeout: float = 5, transport: httpx.BaseTransport | None = None) -> dict:
    """One GET to a loopback Ollama (doctor's /api/version and /api/tags, and /api/ps below)."""
    with _client(timeout, transport) as client:
        resp = client.get(_base(api_base) + path)
    resp.raise_for_status()
    return resp.json()


def resident(api_base: str, transport: httpx.BaseTransport | None = None) -> list[str]:
    """The models Ollama holds in RAM now (as tier names, with the ollama/ prefix)."""
    return [LOCAL_PREFIX + m["name"] for m in get(api_base, "/api/ps", transport=transport).get("models", [])]


def unload(api_base: str, model: str, transport: httpx.BaseTransport | None = None) -> None:
    """Ask Ollama to free a model's RAM now (keep_alive 0)."""
    _post(_base(api_base) + "/api/generate", {"model": model.removeprefix(LOCAL_PREFIX), "keep_alive": 0}, 10,
          transport)
