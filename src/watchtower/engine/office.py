from __future__ import annotations

import json
from typing import Callable

from watchtower.engine.floor import strs, untrusted
from watchtower.engine.advisory import ADVISORY_ERRORS
from watchtower.engine.qafloor import MAX_CHECKS, parse_checks
from watchtower.roles import Role

AREAS_PROMPT = (
    "Spec acceptance criteria:\n{acceptance}\n\nThe app's routes (the architect's contract):\n{routes}\n\n"
    'Split QA into at most 3 test areas that together cover the criteria. Reply as JSON: {{"areas": [string]}}'
)
CHECKS_PROMPT = (
    "Spec acceptance criteria:\n{acceptance}\n\nThe app's routes (the architect's contract):\n{routes}\n\n"
    "Test area: {area}\n\nWrite at most 3 HTTP checks for this area, in order, using ONLY paths and form fields "
    "from the routes contract (POST a form, then GET a page and expect the new text). Reply as JSON: "
    '{{"checks": [{{"name": string, "method": "GET" or "POST", "path": string, "form": {{field: value}}, '
    '"expect_status": number, "expect_text": string}}]}}'
)
REVIEW_PROMPT = (
    "Spec acceptance criteria:\n{acceptance}\n\nThe app's routes:\n{routes}\n\nProposed QA checks:\n{checks}\n\n"
    "Name any check that is wrong, trivial or not about the criteria. Reply as JSON: "
    '{{"pass": boolean, "drop": [check names], "reason": string}}'
)


def _bullets(items) -> str:
    return "\n".join(f"- {a}" for a in items) or "- (none)"


class QAOffice:
    """Floor 4 office, test-first: the QA Lead splits the acceptance criteria into areas, QA workers write
    checks per area from the architect's routes contract (before any code exists), QA HR drops bad ones."""

    def __init__(self, lead: Role, worker: Role, hr: Role, ask: Callable[[Role, str], dict]):
        self._lead, self._worker, self._hr, self._ask = lead, worker, hr, ask

    def plan_checks(self, spec: dict, routes: list[dict]) -> list[dict]:
        if not routes:
            return []
        acceptance, contract = _bullets(spec["acceptance"]), untrusted("f2.architect", json.dumps(routes))
        try:
            areas = strs(self._ask(self._lead, AREAS_PROMPT.format(acceptance=acceptance, routes=contract))
                         .get("areas"), cap=3)
        except ADVISORY_ERRORS:
            areas = []
        checks: list[dict] = []
        for area in areas or list(spec["acceptance"])[:3]:
            try:
                out = self._ask(self._worker, CHECKS_PROMPT.format(acceptance=acceptance, routes=contract,
                                                                   area=untrusted("f4.lead", area)))
            except ADVISORY_ERRORS:
                continue
            checks += parse_checks(out)[:3]
        paths = {r["path"] for r in routes}
        checks = [c for c in checks if c["path"].split("?")[0] in paths
                  and (c["method"] == "POST" or c["expect_text"])][:MAX_CHECKS]
        if not checks:
            return []
        try:
            verdict = self._ask(self._hr, REVIEW_PROMPT.format(
                acceptance=acceptance, routes=contract, checks=untrusted("f4.qa", json.dumps(checks, indent=1))))
            drop = set(strs(verdict.get("drop")))
        except ADVISORY_ERRORS:
            drop = set()
        return [c for c in checks if c["name"] not in drop]


EXPECT_PROMPT = (
    "Spec:\nTitle: {title}\nGoal: {goal}\n\nThe app's routes:\n{routes}\n\nWhat short exact text (a few words) "
    'must the home page (GET /) show? Reply as JSON: {{"expect_text": string}}'
)
DIAGNOSE_PROMPT = (
    "Floor 3 started the app and it failed. Its output:\n{log}\n\nExplain the cause and the fix in one or two "
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

    def diagnose(self, log: str) -> str:
        try:
            out = self._ask(self._hr, DIAGNOSE_PROMPT.format(log=untrusted("sandbox", log[-1500:])))
        except ADVISORY_ERRORS:
            return ""
        return " ".join(str(out.get("diagnosis") or "").split())[:500]
