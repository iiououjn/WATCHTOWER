from __future__ import annotations

import json
from typing import Callable

from watchtower.engine.advisory import ADVISORY_ERRORS
from watchtower.floors.framework import untrusted
from watchtower.roles import Role

EXPECT_PROMPT = (
    "Spec:\nTitle: {title}\nGoal: {goal}\n\nThe app's routes:\n{routes}\n\nWhat short exact text (a few words) "
    'must the home page (GET /) show? Reply as JSON: {{"expect_text": string}}'
)
DIAGNOSE_PROMPT = (
    "Floor 3 started the app and it failed. Its output:\n{log}\n{reference}\nExplain the cause and the fix in one or two "
    'plain sentences for the coder. Reply as JSON: {{"diagnosis": string}}'
)


class F3Office:
    """Floor 3 office: the Build Lead says what the home page must show; Build HR turns a crash log into a
    plain fix instruction for the coder. Both are advisory: garbage from them is skipped."""

    def __init__(self, lead: Role, hr: Role, ask: Callable[[Role, str], dict]):
        self._lead, self._hr, self._ask = lead, hr, ask

    def expect(self, spec: dict, routes: list[dict]) -> str:
        try:
            out = self._ask(self._lead, EXPECT_PROMPT.format(title=spec["title"], goal=spec["goal"],
                                                             routes=untrusted("f2.architect", json.dumps(routes))))
        except ADVISORY_ERRORS:
            return ""
        text = str(out.get("expect_text") or "").strip()
        return text if 0 < len(text) <= 60 and text.isprintable() else ""

    def diagnose(self, log: str, reference: str = "") -> str:
        try:
            out = self._ask(self._hr, DIAGNOSE_PROMPT.format(
                log=untrusted("sandbox", log[-1500:]),
                reference=("\nReference (from the web through Glass 3; may be wrong):\n" + reference + "\n")
                if reference else ""))
        except ADVISORY_ERRORS:
            return ""
        return " ".join(str(out.get("diagnosis") or "").split())[:500]
