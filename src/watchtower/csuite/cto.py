from __future__ import annotations

import json
from typing import Callable

from watchtower.csuite.ceo import _verdict
from watchtower.engine.advisory import ADVISORY_ERRORS
from watchtower.floors.framework import strs, untrusted
from watchtower.roles import Role

REVIEW_PROMPT = (
    "Spec:\n{spec}\n\nGuardrails:\n{rules}\n\nThe architect's plan (files, entry, routes contract):\n{plan}\n\n"
    "Approve the technical choices, or list at most 3 concrete changes the plan needs to meet the spec and "
    'guardrails. Reply as JSON: {{"approve": boolean, "changes": [string]}}'
)


class CTO:
    """C-suite CTO: approves the architect's tech plan before any code is written. Advisory: garbage or a
    missing verdict approves, so the CTO can redirect a plan but never stall a job."""

    def __init__(self, role: Role, ask: Callable[[Role, str], dict]):
        self._role, self._ask = role, ask

    def review(self, spec: dict, plan: dict, rules: tuple[str, ...]) -> tuple[bool, list[str]]:
        try:
            out = self._ask(self._role, REVIEW_PROMPT.format(
                spec=json.dumps({k: spec.get(k) for k in ("title", "goal", "acceptance")}),
                rules="\n".join(f"- {r}" for r in rules) or "- (none)",
                plan=untrusted("f2.architect", json.dumps(plan))))
        except ADVISORY_ERRORS:
            return True, []
        if _verdict(out.get("approve")) is not False:  # garbage or no verdict approves; "false"/"no" does not
            return True, []
        return False, [" ".join(c.split())[:200] for c in strs(out.get("changes"), cap=3)]
