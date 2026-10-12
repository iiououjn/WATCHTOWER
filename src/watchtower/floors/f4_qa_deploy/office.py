from __future__ import annotations

import json
from typing import Callable

from watchtower.engine.advisory import ADVISORY_ERRORS
from watchtower.floors.f4_qa_deploy.qafloor import MAX_CHECKS, parse_checks
from watchtower.floors.framework import strs, untrusted
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
            checks += parse_checks(out, known=spec["title"] + "\n" + "\n".join(r["shows"] for r in routes))[:3]
        paths = {r["path"] for r in routes}
        checks = [c for c in checks if c["path"].split("?")[0] in paths
                  and (c["method"] == "POST" or c["expect_text"])][:MAX_CHECKS]
        return self.review(spec, routes, checks)

    def review(self, spec: dict, routes: list[dict], checks: list[dict]) -> list[dict]:
        """QA HR drops checks that are wrong, trivial or not about the criteria (advisory: garbage keeps all)."""
        if not checks:
            return []
        try:
            verdict = self._ask(self._hr, REVIEW_PROMPT.format(
                acceptance=_bullets(spec["acceptance"]), routes=untrusted("f2.architect", json.dumps(routes)),
                checks=untrusted("f4.qa", json.dumps(checks, indent=1))))
            drop = set(strs(verdict.get("drop")))
        except ADVISORY_ERRORS:
            drop = set()
        kept = [c for c in checks if c["name"] not in drop]
        # HR may prune, never empty the suite or strip every page-text check: status-only checks test nothing
        return kept if any(c["expect_text"] for c in kept) or not any(c["expect_text"] for c in checks) else checks



class QARound:
    """Floor 4's checks for one plan. Test-first checks (from the routes contract) are kept as written; if
    there are none — or none tests real page text — QA writes checks from the current code every attempt
    (so they never go stale) and QA HR reviews them. Nothing here ever weakens a check: a bad check that
    keeps failing runs out the send-backs and the owner decides, which is the safe way to fail."""

    def __init__(self, office: QAOffice, writer, spec: dict):
        self._office, self._writer, self._spec = office, writer, spec
        self.checks: list[dict] = []
        self._fallback = True

    def reset(self, checks: list[dict]) -> None:
        good = any(c["expect_text"] for c in checks)  # a status-only suite passes almost any app: not a suite
        self.checks, self._fallback = ([dict(c) for c in checks], False) if good else ([], True)

    def ensure(self, routes: list[dict], code: str) -> list[dict]:
        if self._fallback:
            self.checks = self._office.review(self._spec, routes, self._writer.write_checks(self._spec, code))
        return self.checks
