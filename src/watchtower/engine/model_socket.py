from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from typing import Callable

from watchtower.config import Settings
from watchtower.engine.governor.audit import AuditLog
from watchtower.engine.governor.budget import Budget
from watchtower.engine.system import free_ram_pct

LOCAL_PREFIX = "ollama/"
RAM_SETTLE_POLLS = 10  # Ollama frees an unloaded model's RAM asynchronously
RAM_SETTLE_SECONDS = 0.5
RETRY_DELAYS = (2.0, 4.0)  # backoff before the 2nd and 3rd try of a transient failure (spec §10)
_TRANSIENT_NAMES = {  # litellm's and httpx's names for a dropped connection, a timeout or a server error
    "APIConnectionError", "Timeout", "InternalServerError", "ServiceUnavailableError", "BadGatewayError",
    "TransportError", "NetworkError", "ConnectError", "ReadError", "WriteError", "RemoteProtocolError",
    "TimeoutException", "ConnectTimeout", "ReadTimeout", "WriteTimeout", "PoolTimeout"}


class ModelUnavailable(Exception):
    pass


class CloudDisabled(Exception):
    pass


class LowMemory(Exception):
    pass


class BadModelOutput(Exception):
    pass


def transient(error: BaseException) -> bool:
    """Worth another try: the connection dropped, the call timed out, or the server failed (5xx). Read from
    builtins, a status code and class names (MRO), never library types, so it outlives a swap of the client."""
    if isinstance(error, (ConnectionError, TimeoutError)):
        return True
    status = getattr(error, "status_code", None)
    if status is None:
        status = getattr(getattr(error, "response", None), "status_code", None)
    if isinstance(status, int) and not isinstance(status, bool):
        return 500 <= status <= 599
    return any(cls.__name__ in _TRANSIENT_NAMES for cls in type(error).__mro__)


def parse_json(text: str) -> dict:
    """Parse a JSON object from model output, tolerating prose and ```json fences around it."""
    text = (text or "").strip()
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            raise ValueError("no JSON object found") from None
        try:
            value = json.loads(text[start:end + 1])
        except json.JSONDecodeError as e:
            raise ValueError(f"invalid JSON: {e.msg}") from None
    if not isinstance(value, dict):
        raise ValueError("expected a JSON object")
    return value


@dataclass(frozen=True)
class Reply:
    text: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    seconds: float
    usd: float


_MARK = r"^[ \t]*(?:[-*][ \t]+|\d+[.)][ \t]*)?(?:#{2,4}|\*\*)[ \t]*(?:\*\*)?[ \t]*"  # '### ', '**', '1. ###' …
_HEADER = re.compile(_MARK + r"(FILE|DELETE)[ \t]*(?:\*\*)?[ \t]*:[ \t]*(?:\*\*)?[ \t]*(.+?)[ \t]*(?:\*\*)?[ \t]*$",
                     re.I)
_MEMO = re.compile(r"^[ \t]*(?:(?:#{2,4}|\*\*)[ \t]*(?:\*\*)?[ \t]*)?MEMO[ \t]+(f\d)[ \t]*(?:\*\*)?[ \t]*:"
                   r"[ \t]*(?:\*\*)?[ \t]*(\S.*?)[ \t]*$", re.I)
_FENCE = re.compile(r"^([ \t]*)(`{3,}|~{3,})")
_PATH_OK = re.compile(r"[\w.-]+(?:/[\w.-]+)*\.\w+")
FILES_NOTE = ("\n\nYour previous reply had no usable files. Reply with one block per file, exactly like this:\n"
              "### FILE: app.py\n```python\n<the complete file>\n```")


def _clean_path(raw: str) -> str:
    path = raw.strip().strip("`*'\"").strip().replace("\\", "/")
    while path.startswith("./"):
        path = path[2:]
    return path


def _header(line: str) -> tuple[str, str] | None:
    """A file header only when clearly marked ('##'/'###'/'**', optional list number) and naming a real file —
    so a code comment ('# File: app.py') or a template ('### FILE: {name}') is never one."""
    m = _HEADER.match(line)
    path = _clean_path(m.group(2)) if m else ""
    return (m.group(1).upper(), path) if m and _PATH_OK.fullmatch(path) else None


def parse_files(text: str) -> dict:
    """Code as plain fenced blocks ('### FILE: path' + a fence), so no character ever needs escaping — the
    coder's JSON escaping of newlines and quotes was the commonest cause of broken files. A file starts at a
    marked header followed by a fence and ends at the LAST closing fence before the next file (so ``` lines
    inside code never cut it short); a block with no closing fence is rejected with a note, never written half.
    DELETE / MEMO lines count only outside code; the model's own order is kept."""
    lines = (text or "").replace("\r\n", "\n").split("\n")
    starts = []  # (header line, fence line, path)
    for i, line in enumerate(lines):
        head = _header(line)
        if head and head[0] == "FILE":
            j = next((k for k in range(i + 1, len(lines)) if lines[k].strip()), None)
            if j is not None and _FENCE.match(lines[j]):
                starts.append((i, j, head[1]))
    entries, notes, outside = [], [], []  # entries: (line number, file dict)
    first = starts[0][0] if starts else len(lines)
    outside += list(range(first))
    for n, (head_at, open_at, path) in enumerate(starts):
        end = starts[n + 1][0] if n + 1 < len(starts) else len(lines)
        indent, fence = _FENCE.match(lines[open_at]).groups()
        closes = [k for k in range(open_at + 1, end)
                  if lines[k].strip() and set(lines[k].strip()) == {fence[0]} and len(lines[k].strip()) >= len(fence)]
        if not closes:
            last = n + 1 == len(starts)
            notes.append(f"File {path} was cut off (no closing fence); send it again, shorter" if last else
                         f"File {path} was not closed with a fence before the next file; it was not written")
            continue
        body = [ln[len(indent):] if indent and ln.startswith(indent) else ln for ln in lines[open_at + 1:closes[-1]]]
        entries.append((head_at, {"path": path, "content": "\n".join(body) + ("\n" if body else "")}))
        outside += list(range(closes[-1] + 1, end))
    memo = None
    for k in outside:  # text outside every code block: deletes, a memo, headers that never got a fence
        head = _header(lines[k])
        if head and head[0] == "DELETE":
            entries.append((k, {"path": head[1], "delete": True}))
        elif head:
            notes.append(f"File {head[1]} had no ``` fence after its header; send it again as a block")
        elif memo is None and (m := _MEMO.match(lines[k])):
            question = m.group(2).strip()
            if re.sub(r"[^a-z ]", "", question.lower()).strip() != "your question":
                memo = {"to": m.group(1).lower(), "question": question}
    out: dict = {"files": [entry for _, entry in sorted(entries, key=lambda e: e[0])]}
    if notes:
        out["notes"] = notes
    if memo:  # '### MEMO f3: question' — the same memo the JSON roles send
        out["memo"] = memo
    return out


def _litellm_completion(**kw):
    import litellm

    litellm.suppress_debug_info = True  # errors are reported by the CLI, not LiteLLM's banner
    return litellm.completion(**kw)


def _litellm_cost(response) -> float:
    import litellm

    return float(litellm.completion_cost(completion_response=response))


class ModelSocket:
    """One way to call any model. Routes by tier; keeps only one local model in RAM."""

    def __init__(
        self,
        settings: Settings,
        budget: Budget,
        audit: AuditLog,
        completion_fn: Callable | None = None,
        unload_fn: Callable[[str], None] | None = None,
        resident_fn: Callable[[], list[str]] | None = None,
        free_ram_fn: Callable[[], int | None] | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self._s = settings
        self._budget = budget
        self._audit = audit
        self._complete = completion_fn or _litellm_completion
        self._unload = unload_fn or self._unload_ollama
        self._resident = resident_fn or self._resident_ollama
        self._free_ram = free_ram_fn or free_ram_pct
        self._clock = clock
        self._sleep = sleep
        self._loaded: str | None = None

    @property
    def loaded(self) -> str | None:
        return self._loaded

    def ask(self, tier: str, messages: list[dict], job_id: str, json_mode: bool = False) -> Reply:
        if tier not in self._s.tiers:
            raise ValueError(f"unknown model tier {tier!r}; known: {sorted(self._s.tiers)}")
        model = self._s.tiers[tier]
        local = model.startswith(LOCAL_PREFIX)
        if not local and not self._s.cloud_enabled:
            raise CloudDisabled(f"cloud model {model} is disabled; enable cloud models explicitly")
        self._budget.check(job_id)
        usage = self._budget.usage(job_id)
        if local:
            self._swap_to(model, job_id)

        self._audit.append("model_socket", "model_call", {"tier": tier, "model": model}, job_id)
        kwargs = {
            "model": model,
            "messages": messages,
            "max_tokens": max(1, min(self._s.max_output_tokens, usage["max_tokens"] - usage["used_tokens"])),
            "timeout": max(1.0, usage["max_seconds"] - usage["used_seconds"]),
        }
        if local:
            kwargs["api_base"] = self._s.ollama_url
            kwargs["num_ctx"] = self._s.num_ctx
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        for attempt in range(len(RETRY_DELAYS) + 1):
            if attempt:  # a transient failure: back off, then only if the budget still has room
                self._sleep(RETRY_DELAYS[attempt - 1])
                self._budget.check(job_id)
            start = self._clock()
            try:
                resp = self._complete(**kwargs)
                break
            except Exception as e:
                retry = transient(e) and attempt < len(RETRY_DELAYS)
                self._audit.append(
                    "model_socket", "model_error",
                    {"model": model, "error": f"{type(e).__name__}: {str(e)[:200]}", "try": attempt + 1,
                     "retry": retry}, job_id,
                )
                if not retry:
                    hint = f" Is Ollama running? Try: ollama pull {model.removeprefix(LOCAL_PREFIX)}" if local else ""
                    raise ModelUnavailable(f"{model} unavailable ({type(e).__name__}).{hint}") from e
        seconds = self._clock() - start

        try:
            text = resp.choices[0].message.content or ""
            pt = int(resp.usage.prompt_tokens or 0)
            ct = int(resp.usage.completion_tokens or 0)
        except (AttributeError, IndexError, TypeError) as e:
            self._audit.append("model_socket", "model_error", {"model": model, "error": "malformed response"}, job_id)
            raise ModelUnavailable(f"{model} returned a malformed response") from e
        usd = 0.0 if local else _litellm_cost(resp)
        self._budget.charge(job_id, tokens=pt + ct, seconds=seconds, usd=usd)
        self._audit.append(
            "model_socket", "model_reply",
            {"model": model, "tokens": pt + ct, "seconds": round(seconds, 3), "usd": usd}, job_id,
        )
        return Reply(text, model, pt, ct, seconds, usd)

    def ask_files(self, tier: str, messages: list[dict], job_id: str, retries: int = 1) -> dict:
        """Ask for files as fenced blocks (plain text, no JSON escaping). A JSON {"files": [...]} reply is still
        accepted; nothing usable → ask once more with the format shown, then BadModelOutput."""
        convo = list(messages)
        out: dict = {"files": []}
        for attempt in range(retries + 1):
            reply = self.ask(tier, convo, job_id)
            out = parse_files(reply.text)
            if not out["files"] and not out.get("memo"):
                try:
                    data = parse_json(reply.text)
                    if (isinstance(data.get("files"), list) and data["files"]) or isinstance(data.get("memo"), dict):
                        out = {**data, "files": data.get("files") if isinstance(data.get("files"), list) else []}
                except ValueError:
                    pass
            if out["files"] or out.get("memo"):
                return out
            if out.get("notes") and attempt == retries:  # last try: the coder still hears what went wrong
                return out
            self._audit.append("model_socket", "bad_files", {"model": reply.model}, job_id)
            convo = list(messages[:-1]) + [{**messages[-1], "content": messages[-1]["content"] + FILES_NOTE}]
        raise BadModelOutput(f"{self._s.tiers[tier]} returned no usable files after {retries + 1} tries")

    def ask_json(self, tier: str, messages: list[dict], job_id: str, retries: int = 1) -> dict:
        """Ask for a JSON object; on unparseable output, ask again with the error noted. The broken reply is NOT
        sent back: it can be ~2k tokens and would push the retry past the model's context window."""
        convo = list(messages)
        for _ in range(retries + 1):
            reply = self.ask(tier, convo, job_id, json_mode=True)
            try:
                return parse_json(reply.text)
            except ValueError as e:
                self._audit.append("model_socket", "bad_json", {"model": reply.model, "error": str(e)}, job_id)
                note = (f"\n\nYour previous reply was not valid JSON ({str(e)[:120]}). Reply with only one JSON "
                        "object; escape every double quote and newline inside strings (\\\" and \\n).")
                convo = list(messages[:-1]) + [{**messages[-1], "content": messages[-1]["content"] + note}]
        raise BadModelOutput(f"{self._s.tiers[tier]} did not return valid JSON after {retries + 1} tries")

    def _swap_to(self, model: str, job_id: str) -> None:
        """Unload every other resident local model, then refuse to load a new one into low RAM."""
        resident = self._resident_safe(job_id)
        unloaded = False
        for other in resident:
            if other != model:
                self._unload_safe(other, job_id)
                unloaded = True
        if model not in resident:
            pct = self._free_ram()
            for _ in range(RAM_SETTLE_POLLS if unloaded else 0):
                if pct is None or pct >= self._s.min_free_ram_pct:
                    break
                self._sleep(RAM_SETTLE_SECONDS)
                pct = self._free_ram()
            if pct is not None and pct < self._s.min_free_ram_pct:
                self._audit.append("model_socket", "low_memory", {"model": model, "free_pct": pct}, job_id)
                raise LowMemory(
                    f"only {pct}% RAM free (need {self._s.min_free_ram_pct}%) to load {model}; "
                    "close some apps, then resume"
                )
        self._loaded = model

    def make_room(self, job_id: str | None = None) -> bool:
        """Before a sandbox run: if RAM is low, unload our model so Docker and the model never fight over it
        (on 8 GB a resident 7B + a running container means minutes of swap). Reloading costs seconds."""
        if not self._loaded:
            return False
        pct = self._free_ram()
        if pct is None or pct >= self._s.sandbox_free_ram_pct:
            return False
        self._audit.append("model_socket", "make_room", {"model": self._loaded, "free_pct": pct}, job_id)
        self.unload_all(job_id)
        return True

    def unload_all(self, job_id: str | None = None) -> None:
        """Free RAM after a job: unload the model this process loaded, never another process's."""
        if self._loaded:
            self._unload_safe(self._loaded, job_id)
        self._loaded = None

    def _resident_safe(self, job_id: str | None) -> list[str]:
        try:
            return self._resident()
        except Exception as e:
            self._audit.append("model_socket", "resident_check_failed", {"error": str(e)[:200]}, job_id)
            return []

    def _unload_safe(self, model: str, job_id: str | None) -> None:
        try:
            self._unload(model)
        except Exception as e:
            self._audit.append("model_socket", "unload_failed", {"model": model, "error": str(e)[:200]}, job_id)

    def _resident_ollama(self) -> list[str]:
        import httpx

        resp = httpx.get(f"{self._s.ollama_url}/api/ps", timeout=5)
        resp.raise_for_status()
        return [LOCAL_PREFIX + m["name"] for m in resp.json().get("models", [])]

    def _unload_ollama(self, model: str) -> None:
        import httpx

        httpx.post(
            f"{self._s.ollama_url}/api/generate",
            json={"model": model.removeprefix(LOCAL_PREFIX), "keep_alive": 0},
            timeout=10,
        ).raise_for_status()
