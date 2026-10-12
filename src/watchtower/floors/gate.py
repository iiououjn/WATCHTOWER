from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from watchtower.floors.framework import WorkPackage, strs, truthy, untrusted, untrusted_code
from watchtower.roles import Role

GATE_PROMPT = (
    "Spec acceptance criteria:\n{acceptance}\n\nOut of scope:\n{out_of_scope}\n\n"
    "Work package from {floor}:\n{summary}\n\nSources: {sources}\nOpen questions: {questions}\n\n"
    "{rules}"
    'Does the package satisfy the criteria? Reply as JSON: {{"pass": boolean, "reasons": [string]}}'
)


@dataclass(frozen=True)
class Verdict:
    passed: bool
    reasons: list[str]
    route: str | None = None


def _bullets(items: list[str]) -> str:
    return "\n".join(f"- {i}" for i in items) or "- (none)"


class Gate:
    """Floor-5 gate between floors: deterministic checks first, then a reviewer model."""

    def __init__(self, ask: Callable[[Role, str], dict], reviewer: Role, rules: tuple[str, ...] = ()):
        self._ask = ask
        self._reviewer = reviewer
        self._rules = rules

    def check(self, spec: dict, package: WorkPackage, routes: tuple[str, ...] = ()) -> Verdict:
        default_route = routes[-1] if routes else None
        problems = package.validate()
        if problems:
            return Verdict(False, problems, default_route)
        prompt = GATE_PROMPT.format(
            acceptance=_bullets(spec.get("acceptance", [])),
            out_of_scope=_bullets(spec.get("out_of_scope", [])),
            floor=package.floor, summary=untrusted_code(package.floor, package.summary),
            sources=", ".join(package.sources) or "(none)",
            rules=("Guardrails:\n" + "\n".join(f"- {r}" for r in self._rules) + "\n\n") if self._rules else "",
            questions=untrusted("open-questions", "; ".join(package.open_questions)) if package.open_questions
            else "(none)",
        )
        if routes:
            prompt += (f'\nIf it fails, also set "send_back_to" to one of: {", ".join(routes)}. '
                       'Reply as JSON: {"pass": boolean, "reasons": [string], "send_back_to": string}')
        out = self._ask(self._reviewer, prompt)
        route = str(out.get("send_back_to") or "").strip().lower()
        return Verdict(truthy(out.get("pass")), strs(out.get("reasons"), cap=5),
                       (route if route in routes else default_route) if routes else None)
