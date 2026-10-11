from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from watchtower.engine.floor import WorkPackage, strs, truthy, untrusted
from watchtower.roles import Role

GATE_PROMPT = (
    "Spec acceptance criteria:\n{acceptance}\n\nOut of scope:\n{out_of_scope}\n\n"
    "Work package from {floor}:\n{summary}\n\nSources: {sources}\nOpen questions: {questions}\n\n"
    'Does the package satisfy the criteria? Reply as JSON: {{"pass": boolean, "reasons": [string]}}'
)


@dataclass(frozen=True)
class Verdict:
    passed: bool
    reasons: list[str]


def _bullets(items: list[str]) -> str:
    return "\n".join(f"- {i}" for i in items) or "- (none)"


class Gate:
    """Floor-5 gate between floors: deterministic checks first, then a reviewer model."""

    def __init__(self, ask: Callable[[Role, str], dict], reviewer: Role):
        self._ask = ask
        self._reviewer = reviewer

    def check(self, spec: dict, package: WorkPackage) -> Verdict:
        problems = package.validate()
        if problems:
            return Verdict(False, problems)
        out = self._ask(self._reviewer, GATE_PROMPT.format(
            acceptance=_bullets(spec.get("acceptance", [])),
            out_of_scope=_bullets(spec.get("out_of_scope", [])),
            floor=package.floor, summary=untrusted(package.floor, package.summary),
            sources=", ".join(package.sources) or "(none)",
            questions="; ".join(package.open_questions) or "(none)",
        ))
        return Verdict(truthy(out.get("pass")), strs(out.get("reasons"), cap=5))
