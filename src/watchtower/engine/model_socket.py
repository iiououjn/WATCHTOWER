from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable

from watchtower.config import Settings
from watchtower.engine.governor.audit import AuditLog
from watchtower.engine.governor.budget import Budget
from watchtower.engine.system import free_ram_pct

LOCAL_PREFIX = "ollama/"


class ModelUnavailable(Exception):
    pass


class CloudDisabled(Exception):
    pass


class LowMemory(Exception):
    pass


@dataclass(frozen=True)
class Reply:
    text: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    seconds: float
    usd: float


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
    ):
        self._s = settings
        self._budget = budget
        self._audit = audit
        self._complete = completion_fn or _litellm_completion
        self._unload = unload_fn or self._unload_ollama
        self._resident = resident_fn or self._resident_ollama
        self._free_ram = free_ram_fn or free_ram_pct
        self._clock = clock
        self._loaded: str | None = None

    @property
    def loaded(self) -> str | None:
        return self._loaded

    def ask(self, tier: str, messages: list[dict], job_id: str) -> Reply:
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
            "max_tokens": max(1, usage["max_tokens"] - usage["used_tokens"]),
            "timeout": max(1.0, usage["max_seconds"] - usage["used_seconds"]),
        }
        if local:
            kwargs["api_base"] = self._s.ollama_url
        start = self._clock()
        try:
            resp = self._complete(**kwargs)
        except Exception as e:
            self._audit.append(
                "model_socket", "model_error",
                {"model": model, "error": f"{type(e).__name__}: {str(e)[:200]}"}, job_id,
            )
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

    def _swap_to(self, model: str, job_id: str) -> None:
        """Unload every other resident local model, then refuse to load a new one into low RAM."""
        resident = self._resident_safe(job_id)
        for other in resident:
            if other != model:
                self._unload_safe(other, job_id)
        if model not in resident:
            pct = self._free_ram()
            if pct is not None and pct < self._s.min_free_ram_pct:
                self._audit.append("model_socket", "low_memory", {"model": model, "free_pct": pct}, job_id)
                raise LowMemory(
                    f"only {pct}% RAM free (need {self._s.min_free_ram_pct}%) to load {model}; "
                    "close some apps, then resume"
                )
        self._loaded = model

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
