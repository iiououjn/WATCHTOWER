from __future__ import annotations

from typing import Callable

from watchtower.engine.advisory import ADVISORY_ERRORS
from watchtower.floors.framework import untrusted
from watchtower.roles import Role

RECOMMEND_PROMPT = (
    "Spec:\nTitle: {title}\nGoal: {goal}\nAcceptance criteria:\n{acceptance}\n\nEvidence from the floors:\n"
    "{evidence}\n\nOversight audit:\n{audit}\n\nShould the owner accept this app? Reply as JSON: "
    '{{"approve": boolean, "note": string}}'
)


class CEO:
    """C-suite CEO: the tower's final recommendation to the owner before sign-off. Returns (None, "") when
    it has no clear view; a clear reject makes the owner look even when --yes was given."""

    def __init__(self, role: Role, ask: Callable[[Role, str], dict]):
        self._role, self._ask = role, ask

    def recommend(self, spec: dict, evidence: str, audit: str) -> tuple[bool | None, str]:
        try:
            out = self._ask(self._role, RECOMMEND_PROMPT.format(
                title=spec["title"], goal=spec["goal"], acceptance="\n".join(f"- {a}" for a in spec["acceptance"]),
                evidence=untrusted("evidence", evidence[:1500]), audit=untrusted("f5.auditor", audit[:1500] or "(none)")))
        except ADVISORY_ERRORS:
            return None, ""
        verdict = out.get("approve")
        return (verdict if isinstance(verdict, bool) else None), " ".join(str(out.get("note") or "").split())[:200]
