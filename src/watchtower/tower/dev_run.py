from __future__ import annotations

from dataclasses import dataclass, field

from watchtower.beacon.lookout import Lookout, crash_query
from watchtower.csuite.ceo import CEO
from watchtower.csuite.cto import CTO
from watchtower.engine.advisory import ADVISORY_ERRORS
from watchtower.engine.workflow import Progress
from watchtower.engine.workspace import Workspace
from watchtower.evidence import _evidence, _finding_query, _reference, _status_query, model_objection, objection_note
from watchtower.floors.f2_dev.devfloor import DevFloor
from watchtower.floors.f2_dev.handoff import board_line, f2_handoff, for_gate, static_feedback
from watchtower.floors.f2_dev.skeleton import page_text
from watchtower.floors.f3_build.buildfloor import build_check
from watchtower.floors.f3_build.office import F3Office
from watchtower.floors.f4_qa_deploy.contract import coder_token, contract_checks, fresh_token, gate_qa_note
from watchtower.floors.f4_qa_deploy.office import QAOffice, QARound
from watchtower.floors.f4_qa_deploy.qafloor import QAFloor, qa_headline, run_qa
from watchtower.floors.f4_qa_deploy.releases import manifest_of
from watchtower.floors.f5_oversight.office import OversightOffice
from watchtower.floors.f5_oversight.oversight import security_package, security_scan
from watchtower.floors.f5_oversight.probe import xss_probe
from watchtower.floors.framework import WorkPackage, untrusted
from watchtower.floors.gate import Gate
from watchtower.tower.signoff import release_answer

DEV_ROUTES = ("research", "design", "code")


def _passed(package: WorkPackage | None) -> bool:
    return package is not None and bool(package.checks_run[-1]["pass"])


def _failed(package: WorkPackage | None) -> bool:
    return package is not None and not package.checks_run[-1]["pass"]


@dataclass
class Attempt:
    """What one attempt's floors produced: the package the gate reads, and each later floor's own result."""
    package: WorkPackage
    go: bool
    reasons: list[str]
    tests_ok: bool
    f3: WorkPackage | None = None
    f4: WorkPackage | None = None
    sec: WorkPackage | None = None
    audit: str = ""
    notes: tuple = field(default_factory=tuple)


class DevRun:
    """One app job's F2→F5 loop (8d, audit E-A1: what was the 133-line `tower._dev`). It owns the floors and the
    state an attempt hands the next (plan, feedback, QA round …); each `attempt` runs F2 → F3 → F4 → F5 → gate and
    returns the release payload, or None after saving the send-back. `tower` is the TowerPipeline that called it
    (its board, memo door, plan and retro helpers)."""

    def __init__(self, tower, data: dict, progress: Progress):
        self.t, self.data, self.progress = tower, data, progress
        self.job_id, self.spec, r = data["job_id"], data["spec"], tower._roles
        self.ask = lambda role, prompt: tower._call(role, data, prompt)
        self.ws = Workspace(tower._sandbox.workspace(self.job_id))
        self.dev = DevFloor(r["f2.architect"], r["f2.coder"], ask=self.ask, workspace=self.ws, run=self.run,
                            hr=r["f2.hr"], stdlib_only=tower._g.stdlib_only)
        self.f3_office = F3Office(r["f3.lead"], r["f3.hr"], self.ask)
        self.gate = Gate(self.ask, r["f5.dev_gate"], tower._g.rules)
        qa = QAFloor(r["f4.qa"], self.ask)
        self.qa_office = QAOffice(r["f4.lead"], r["f4.qa"], r["f4.hr"], self.ask)
        self.oversight = OversightOffice(r["f5.lead"], r["f5.auditor"], self.ask)
        self.research, self.lessons = (data.get("f1") or {}).get("summary", ""), tower._lessons(data)
        self.cto = CTO(r["cto"], self.ask)
        online = data.get("research") and not data.get("offline")  # floors 2–5 search only with --research
        self.look = Lookout(tower._beacon_factory if online else None, tower._knowledge)
        self.qa_round = QARound(self.qa_office, qa, self.spec)
        self.feedback: list[str] = []

    def run(self, cmd: list[str]):
        if self.t._before_sandbox is not None:
            self.t._before_sandbox(self.job_id)
        return self.t._sandbox.run(self.job_id, cmd, timeout=90)

    def peek(self, floor: str, query: str, hits: int = 2, chars: int = 700) -> str:
        return self.look.ask(floor, query, self.job_id,
                             lambda prompt: self.t._ask(self.t._roles[f"glass.{floor}"], self.data, prompt), hits,
                             chars)

    def qa_for(self, plan: dict) -> str:
        """The QA office's checks for this plan, then the text F3 expects."""
        self.qa_round.reset(self.t._plan_qa(self.data, plan, self.qa_office))
        return page_text(self.spec["title"]) if self.dev.owned else self.f3_office.expect(self.spec, plan["routes"])

    def _plan(self, feedback: list[str]) -> dict:
        return self.t._approved_plan(self.data, self.dev, self.cto, self.research, self.lessons, feedback, self.docs)

    def start(self) -> int:
        """Plan (or, 8b, restore the last finished attempt: no re-plan, the send-back counter is kept); the first
        attempt to run."""
        saved = self.progress.state
        if saved:
            for k in ("plan", "feedback", "docs", "focus", "expect", "units_due", "model_heard"):
                setattr(self, k, saved[k])
            self.dev.owned = set(saved["owned"])
            self.qa_round.restore(saved["qa"])
            self.look.restore(saved.get("looks", {}))
            self.t._known.update({(self.job_id, floor): text for floor, text in saved["known"].items()})
        else:
            self.docs = self.peek("f2", "python standard library http.server " + self.spec["title"])
            self.plan, self.feedback = self._plan([]), []
            self.units_due = True  # F2 workers write units on the first build and after each re-plan, never on a fix
            self.focus = self.oversight.focus(self.spec)
            self.expect = self.qa_for(self.plan)
            self.model_heard = False  # 6v: has the coder already heard a model-only gate objection?
        self.qa_due = saved.get("qa_due", False)  # review r3: a re-plan was saved before its QA plan was written
        if not saved:
            self.save(0)
        elif self.qa_due:  # the crash came between a re-plan and its QA plan: finish that plan first
            self.expect, self.qa_due = self.qa_for(self.plan), False
            self.save(saved["attempt"])
        return saved.get("attempt", 0)

    def save(self, next_attempt: int) -> None:
        """Durable, then the owner's pause acts: no finished attempt is lost."""
        self.progress.save({
            "attempt": next_attempt, "plan": self.plan, "feedback": self.feedback, "docs": self.docs,
            "focus": self.focus, "expect": self.expect, "owned": sorted(self.dev.owned), "units_due": self.units_due,
            "model_heard": self.model_heard, "qa": self.qa_round.state(), "qa_due": self.qa_due,
            "looks": self.look.state(), "known": {f: t for (j, f), t in self.t._known.items() if j == self.job_id}})

    def attempt(self, attempt: int) -> dict | None:
        a = self._floors(attempt)
        verdict = self.gate.check(self.spec, a.package, DEV_ROUTES, a.notes)
        self.t._bus.publish("gate.verdict", {"floor": "dev", "attempt": attempt, "passed": verdict.passed,
                                             "reasons": verdict.reasons, "route": verdict.route}, self.job_id)
        lone = model_objection(verdict, a.package, a.f3, a.f4, a.sec)  # 6v: only the model objects
        objection = lone if lone and (self.model_heard or attempt == self.t._g.max_send_backs) else []
        self.model_heard = self.model_heard or bool(lone)  # the coder hears the first one (send-back below)
        self.t._post(self.data, "f5", "done" if verdict.passed else "issue", "gate passed the app" if verdict.passed
                     else f"gate objected; all tower checks passed, owner decides: {'; '.join(objection)[:160]}"
                     if objection else f"gate sent back to {verdict.route}: {'; '.join(verdict.reasons)[:200]}")
        if verdict.passed or objection:
            return self._release(a, objection)
        self.feedback = self._send_back(a, verdict.reasons)
        if verdict.route in ("design", "research"):
            self.plan, self.units_due = self._plan(self.feedback), True
            self.qa_due = True  # review r3: the re-plan already changed the workspace: its plan is durable with it
            self.save(attempt + 1)
            self.expect, self.qa_due = self.qa_for(self.plan), False
        self.save(attempt + 1)
        return None

    def _floors(self, attempt: int) -> Attempt:
        """F2 units and build, then (only while each floor passes) F3 build check, F4 QA and the F5 office."""
        written: list[int] = []  # F2 workers write the missing planned files first (MVP unit first)

        def on_unit(i: int, n: int, paths: list[str]) -> None:
            written.append(i)
            self.t._post(self.data, "f2", "doing", f"coder unit {i}/{n} written: {', '.join(paths)}")
        plan, ws = self.plan, self.ws
        coder_qa = contract_checks(plan["routes"], coder_token(self.job_id))[0] + self.qa_round.coder_checks
        unit_notes = self.dev.write_units(self.spec, plan, coder_qa, on_unit=on_unit) if self.units_due else []
        self.units_due = False
        present = {p.lower() for p in ws.files()}
        missing = [f["path"] for f in plan["files"] if f["path"].lower() not in present]
        if written and missing:
            unit_notes.append(f"planned files still missing: {', '.join(missing[:8])}; write them")
        package = self.dev.build(self.spec, plan, unit_notes + list(self.feedback), coder_qa,  # unit notes first
                                 test_first=bool(written) and not self.feedback and not missing)
        tests_ok = bool(package.checks_run and package.checks_run[-1].get("pass"))
        go, reasons = f2_handoff(package.checks_run, plan["entry"], ws.files())  # the tower's checks decide
        self.t._post(self.data, "f2", "doing", board_line(package.checks_run, attempt, go, reasons))
        self.t._handoff(self.data, "f2", attempt, go, reasons)
        a = Attempt(package, go, reasons, tests_ok)
        if package.checks_run and plan["entry"] not in ws.files():
            missing_entry = [f"the planned entry file {plan['entry']} does not exist; create it"]
            a.package = WorkPackage("f2", package.summary, ws.files(), [], package.checks_run +
                                    [{"check": "entry", "pass": False}], missing_entry)
        elif go:
            self._later_floors(a, attempt)
        return a

    def _later_floors(self, a: Attempt, attempt: int) -> None:
        plan, ws = self.plan, self.ws
        a.f3 = build_check(self.run, plan["entry"], self.expect, plan["routes"])  # MVP first, then the full app
        self.t._handoff(self.data, "f3", attempt, a.f3.checks_run[-1]["pass"], a.f3.open_questions)
        self.t._post(self.data, "f3", "done" if _passed(a.f3) else "issue", a.f3.summary.splitlines()[0])
        if _passed(a.f3):
            a.f4 = self._f4(attempt)
        if _passed(a.f4):  # Floor 5 office: security scan, then spec audit
            a.sec = security_package(xss_probe(self.run, plan["entry"], plan["routes"])  # probe first: never cut
                                     + security_scan(ws.root, ws.files()), self.t._g.security_fail_on)
            self.t._handoff(self.data, "f5", attempt, a.sec.checks_run[-1]["pass"], a.sec.open_questions)
            self.t._post(self.data, "f5", "doing" if _passed(a.sec) else "issue", a.sec.summary.splitlines()[0],
                         known=a.sec.summary[:1500])
            if _passed(a.sec):
                a.audit = self.oversight.audit(self.spec, self.focus, ws.snapshot(3000), a.f4.summary)
        later = [p for p in (a.f3, a.f4, a.sec) if p is not None]
        f2_summary, f2_questions, a.notes = for_gate(a.package.summary, a.package.open_questions, a.tests_ok)
        a.notes += gate_qa_note(a.f4.checks_run[-1]) if a.f4 is not None else ()
        a.package = WorkPackage("dev", "\n\n".join([f2_summary] + [p.summary for p in later]
                                                   + ([f"Oversight audit:\n{a.audit}"] if a.audit else []))
                                + f"\n\nCode:\n{ws.snapshot(3000)}", ws.files(), [],
                                a.package.checks_run + [c for p in later for c in p.checks_run],
                                f2_questions + [q for p in later for q in p.open_questions])

    def _f4(self, attempt: int) -> WorkPackage:
        plan = self.plan
        tower_qa, decide = contract_checks(plan["routes"], fresh_token())  # a token the coder never saw
        try:
            model_qa = self.qa_round.ensure(plan["routes"], self.ws.snapshot())
        except ADVISORY_ERRORS:  # the small model failed: the tower's checks still decide
            if not tower_qa:
                raise
            model_qa = []
        f4 = run_qa(self.run, plan["entry"], tower_qa + model_qa, decide=decide)
        last = f4.checks_run[-1]
        self.t._handoff(self.data, "f4", attempt, last["pass"], f4.open_questions)
        self.t._post(self.data, "f4", "done" if last["pass"] else "issue",
                     qa_headline(last.get("results") or [], last["pass"], decide, last.get("timed_out", False)),
                     known=f4.summary[:1500])
        return f4

    def _release(self, a: Attempt, objection: list[str]) -> dict:
        """The gate passed, or only its model objects after the coder heard it: the owner signs off from here."""
        self.t._retro(self.data, self.oversight, passed=None if objection else True)
        evidence = _evidence(a.package.checks_run, self.t._g.security_fail_on)
        ceo_ok, ceo_note = CEO(self.t._roles["ceo"], self.ask).recommend(self.spec, evidence, a.audit)
        ws = self.ws
        return {"dev": a.package.to_dict(), "files": ws.files(), "workspace": str(ws.root),
                "entry": self.plan["entry"], "manifest": manifest_of(ws.root, ws.files()),
                "evidence": evidence, "ceo": {"approve": ceo_ok, "note": ceo_note},
                "objection": objection_note(objection) if objection else "",  # owner signs off
                "answer": release_answer(self.job_id, ws.root, ws.files(), bool(self.dev.owned), a.tests_ok)}

    def _send_back(self, a: Attempt, reasons: list[str]) -> list[str]:
        """The gate's reasons, the tower's own static notes, and the first failing floor's real output."""
        entry, fail_on = self.plan["entry"], self.t._g.security_fail_on
        feedback = reasons or ["the reviewer rejected the app without reasons"]
        feedback = feedback + static_feedback(a.go, a.reasons, entry, self.ws.files())
        if _failed(a.f3):  # show the coder the app's real error
            feedback = feedback + ["Floor 3 started the app and it failed:\n" + untrusted("sandbox", a.f3.summary)]
            crash = crash_query(a.f3.summary)
            diagnosis = self.f3_office.diagnose(a.f3.summary, self.peek("f3", crash) if crash else "")
            if diagnosis:
                feedback.append("Floor 3 HR diagnosis:\n" + untrusted("f3.hr", diagnosis))
                self.t._post(self.data, "f3", "issue", "diagnosis: " + diagnosis)
        elif _failed(a.f4):
            feedback = feedback + ["Floor 4 QA checks failed:\n" + untrusted("sandbox", a.f4.summary)]
            feedback += _reference("4", self.peek("f4", _status_query(a.f4.checks_run[-1]), 1, 480))  # ≤ 600
        elif _failed(a.sec):
            feedback = feedback + ["Floor 5 security scan found problems; fix them:\n"
                                   + untrusted("security", a.sec.summary)]
            feedback += _reference("5", self.peek("f5", _finding_query(a.sec.checks_run[-1], fail_on), 1, 480))
        return feedback
