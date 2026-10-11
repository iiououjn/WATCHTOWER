from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable

from watchtower.config import Settings
from watchtower.engine.governor.audit import AuditLog
from watchtower.engine.governor.budget import Budget

LOCAL_PREFIX = "ollama/"


class ModelUnavailable(Exception):
    pass


class CloudDisabled(Exception):
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
        clock: Callable[[], float] = time.monotonic,
    ):
        self._s = settings
        self._budget = budget
        self._audit = audit
        self._complete = completion_fn or _litellm_completion
        self._unload = unload_fn or self._unload_ollama
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
        if local:
            self._swap_to(model, job_id)

        self._audit.append("model_socket", "model_call", {"tier": tier, "model": model}, job_id)
        kwargs = {"model": model, "messages": messages}
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

        pt = int(resp.usage.prompt_tokens or 0)
        ct = int(resp.usage.completion_tokens or 0)
        usd = 0.0 if local else _litellm_cost(resp)
        self._budget.charge(job_id, tokens=pt + ct, seconds=seconds, usd=usd)
        self._audit.append(
            "model_socket", "model_reply",
            {"model": model, "tokens": pt + ct, "seconds": round(seconds, 3), "usd": usd}, job_id,
        )
        return Reply(resp.choices[0].message.content or "", model, pt, ct, seconds, usd)

    def _swap_to(self, model: str, job_id: str) -> None:
        if self._loaded and self._loaded != model:
            try:
                self._unload(self._loaded)
            except Exception as e:
                self._audit.append(
                    "model_socket", "unload_failed", {"model": self._loaded, "error": str(e)[:200]}, job_id
                )
        self._loaded = model

    def _unload_ollama(self, model: str) -> None:
        import httpx

        httpx.post(
            f"{self._s.ollama_url}/api/generate",
            json={"model": model.removeprefix(LOCAL_PREFIX), "keep_alive": 0},
            timeout=10,
        ).raise_for_status()
