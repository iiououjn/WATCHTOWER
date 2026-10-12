from __future__ import annotations

import re
from typing import Callable

from watchtower.engine.advisory import ADVISORY_ERRORS
from watchtower.floors.framework import strs, untrusted, untrusted_code
from watchtower.roles import Role

_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f]")


def _bullets(items) -> str:
    return "\n".join(f"- {a}" for a in items) or "- (none)"


FOCUS_PROMPT = (
    "Spec:\nTitle: {title}\nGoal: {goal}\nAcceptance criteria:\n{acceptance}\n\nList at most 3 things Floor 5 "
    'must verify in the finished app (spec points and guardrails). Reply as JSON: {{"focus": [string]}}'
)
AUDIT_PROMPT = (
    "Spec acceptance criteria:\n{acceptance}\n\nAudit focus:\n{focus}\n\nThe app's code:\n{code}\n\n"
    "Test and QA evidence:\n{evidence}\n\nFor each focus point, is it met by the code and evidence? Reply as JSON: "
    '{{"findings": [{{"focus": string, "ok": boolean, "note": string}}]}}'
)
RETRO_PROMPT = (
    "Spec:\nTitle: {title}\nGoal: {goal}\n\nWhat happened on the floors:\n{notes}\n\nWrite at most 3 short lessons "
    'that would help the next job like this succeed. Reply as JSON: {{"lessons": [string]}}'
)


class OversightOffice:
    """Floor 5 office: the Oversight Lead sets the audit focus and writes the retrospective; the Spec Auditor
    checks the code against the focus. The security scan is the other worker; the F5 gate is HR (final call).
    All of it is advisory: model garbage is skipped, never a pause."""

    def __init__(self, lead: Role, auditor: Role, ask: Callable[[Role, str], dict]):
        self._lead, self._auditor, self._ask = lead, auditor, ask

    def focus(self, spec: dict) -> list[str]:
        try:
            out = self._ask(self._lead, FOCUS_PROMPT.format(title=spec["title"], goal=spec["goal"],
                                                            acceptance=_bullets(spec["acceptance"])))
            focus = [" ".join(f.split())[:150] for f in strs(out.get("focus"), cap=3)]
        except ADVISORY_ERRORS:
            focus = []
        return focus or [str(a)[:150] for a in spec["acceptance"][:3]]

    def audit(self, spec: dict, focus: list[str], code: str, evidence: str) -> str:
        try:
            out = self._ask(self._auditor, AUDIT_PROMPT.format(
                acceptance=_bullets(spec["acceptance"]), focus=_bullets(focus),
                code=untrusted_code("workspace", code), evidence=untrusted("evidence", evidence[:1500])))
        except ADVISORY_ERRORS:
            return ""
        rows = [f for f in (out.get("findings") if isinstance(out.get("findings"), list) else []) if isinstance(f, dict)]
        return "\n".join(f"- {' '.join(str(f.get('focus', '')).split())[:100]}: "
                         f"{'OK' if f.get('ok') is True else 'CONCERN'} {' '.join(str(f.get('note', '')).split())[:200]}"
                         for f in rows[:5])

    def retro(self, spec: dict, notes: list[str]) -> list[str]:
        try:
            out = self._ask(self._lead, RETRO_PROMPT.format(
                title=spec["title"], goal=spec["goal"], notes=untrusted("board", "\n".join(notes)[-2000:])))
        except ADVISORY_ERRORS:
            return []
        return [" ".join(_CONTROL.sub(" ", lesson).split())[:200] for lesson in strs(out.get("lessons"), cap=3)]
