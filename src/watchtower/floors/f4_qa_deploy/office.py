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


RECHECK_PROMPT = (
    "Spec acceptance criteria:\n{acceptance}\n\nThis QA check failed twice in a row against the running app:\n"
    "{check}\n\nWhat it got:\n{detail}\n\nIs the check itself wrong (it expects something the criteria do not "
    'require, or text that is not real page text)? Reply as JSON: {{"check_wrong": boolean, "reason": string}}'
)


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
        return kept or checks  # HR may prune, never empty the suite: zero checks would test nothing

    def recheck(self, spec: dict, check: dict, detail: str) -> bool:
        """A check that failed twice in a row: QA HR says whether the CHECK is wrong (then it is dropped).
        Advisory: garbage or no clear verdict keeps the check."""
        try:
            out = self._ask(self._hr, RECHECK_PROMPT.format(
                acceptance=_bullets(spec["acceptance"]), check=untrusted("f4.qa", json.dumps(check)),
                detail=untrusted("sandbox", detail[:600])))
        except ADVISORY_ERRORS:
            return False
        return out.get("check_wrong") is True


class QARound:
    """Floor 4's checks for one plan, and what happened to them. Checks come from the test-first office or,
    failing that, are written once from the code and reviewed. A check whose expected text fails two F4 runs
    in a row (status right) gets one QA HR second look; a wrong one is relaxed to status-only — never a check
    that a POST must persist, and never the last text check, so a broken app cannot slip through."""

    def __init__(self, office: QAOffice, writer, spec: dict):
        self._office, self._writer, self._spec = office, writer, spec
        self.checks: list[dict] = []
        self._failed: set[str] = set()
        self._looked: set[str] = set()

    def reset(self, checks: list[dict]) -> None:
        self.checks, self._failed, self._looked = [dict(c) for c in checks], set(), set()

    def ensure(self, routes: list[dict], code: str) -> list[dict]:
        if not self.checks:
            self.reset(self._office.review(self._spec, routes, self._writer.write_checks(self._spec, code)))
        return self.checks

    def no_f4(self) -> None:
        self._failed = set()  # F4 did not run: the next F4 failure is not "consecutive"

    def after_fail(self, results: list[dict], replanning: bool) -> list[str]:
        failed = {str(r.get("name")) for r in results if r.get("pass") is not True}
        twice, self._failed = failed & self._failed, failed
        if replanning:  # the checks are about to be replaced: no second look worth paying for
            return []
        posted = {str(v) for c in self.checks if c["method"] == "POST" for v in c["form"].values()}
        notes = []
        for c in self.checks:
            result = next((r for r in results if r.get("name") == c["name"]), {})
            texts = [x for x in self.checks if x["expect_text"]]
            if (c["name"] not in twice or c["name"] in self._looked or not c["expect_text"]
                    or c["expect_text"] in posted or len(texts) <= 1
                    or result.get("status") != c["expect_status"]):  # wrong status is a real failure
                continue
            self._looked.add(c["name"])
            if self._office.recheck(self._spec, c, str(result.get("detail") or "")):
                c["expect_text"] = ""
                notes.append(f"QA HR found check {c['name']!r} was wrong; it now only checks the status — ignore "
                             "its expected text")
        return notes
