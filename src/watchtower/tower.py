from __future__ import annotations

import json
import shlex
from pathlib import Path
from typing import Callable

from watchtower.beacon import glass as glass_mod
from watchtower.beacon.beacon import Beacon
from watchtower.beacon.lookout import Lookout, crash_query
from watchtower.floors.board import FLOORS, NAMES, Board
from watchtower.floors.f3_build.buildfloor import build_check
from watchtower.engine.bus import Bus
from watchtower.floors.f2_dev.devfloor import DevFloor
from watchtower.floors.f1_research.office import Floor
from watchtower.floors.framework import WorkPackage, strs, untrusted
from watchtower.floors.gate import Gate
from watchtower.engine.governor.approvals import Approvals
from watchtower.engine.knowledge import Knowledge
from watchtower.engine.model_socket import BadModelOutput
from watchtower.floors.f3_build.office import F3Office
from watchtower.floors.f5_oversight.office import OversightOffice
from watchtower.floors.f4_qa_deploy.office import QAOffice, QARound
from watchtower.evidence import (  # noqa: F401 — re-export
    _evidence, _finding_query, _reference, _status_query, model_objection, objection_note)
from watchtower.floors.f5_oversight.oversight import security_package, security_scan
from watchtower.floors.f5_oversight.probe import xss_probe
from watchtower.floors.f2_dev.handoff import board_line, f2_handoff, for_gate, static_feedback
from watchtower.floors.f4_qa_deploy.contract import QA_ADVISORY, coder_token, contract_checks, fresh_token
from watchtower.floors.f4_qa_deploy.qafloor import QAFloor, qa_headline, run_qa
from watchtower.engine.advisory import ADVISORY_ERRORS
from watchtower.beacon.glass import INJECTION, normalize
from watchtower.floors.f4_qa_deploy.releases import Releases, manifest_of, manifest_problems
from watchtower.csuite.ceo import CEO
from watchtower.csuite.cpo import enough_criteria
from watchtower.csuite.cto import CTO
from watchtower.engine.workflow import Step
from watchtower.guardrails import Guardrails, load_guardrails
from watchtower.engine.workspace import Workspace
from watchtower.roles import Role

MAX_MEMOS = 3
MEMO_SENDERS = {"f1.lead", "f2.architect", "f2.coder", "f3.lead", "f4.lead"}
FLOOR_LEADS = {"f1": "f1.lead", "f2": "f2.architect", "f3": "f3.lead", "f4": "f4.lead"}
MEMO_PROMPT = (
    "{sender} asks your floor:\n{question}\n\nWhat your floor knows:\n{known}\n\n"
    "Answer briefly and factually; say 'unknown' if your floor does not know. "
    'Reply as JSON: {{"answer": string}}'
)
BOARD_HEADER = "\n\nTower board (what the other floors know and what comes next):\n"
DEV_ROUTES = ("research", "design", "code")
CONTEXT_CHARS = 1500
QUESTIONS_PROMPT = (
    "Owner's goal:\n{goal}\n\nReference data:\n{context}\n\nAsk at most 3 short clarifying questions whose answers would most change "
    'the result. Reply as JSON: {{"questions": [string]}}'
)
SPEC_PROMPT = (
    "Owner's goal:\n{goal}\n\nReference data (use it to understand the owner's terms):\n{context}\n\n"
    "Owner's answers to your questions:\n{qa}\n\n"
    "Write a short spec with 3 to 5 acceptance criteria, each one checkable (for an app: what a user does and "
    'what the page then shows). Reply as JSON: {{"title": string, "goal": string, "acceptance": [string], '
    '"out_of_scope": [string]}}'
)
class NeedsOwner(Exception):
    pass


class SpecRejected(Exception):
    pass


class AppRejected(SpecRejected):  # same outcome for the runner: the job fails
    pass


def spec_text(spec: dict) -> str:
    lines = [f"Title: {spec['title']}", f"Goal: {spec['goal']}", "Acceptance criteria:"]
    lines += [f"  - {a}" for a in spec["acceptance"]]
    lines += ["Out of scope:"] + [f"  - {o}" for o in spec["out_of_scope"] or ["(none)"]]
    return "\n".join(lines)


class TowerPipeline:
    """CPO spec → owner approval → Floor 1 with gate. Later phases add floors 2–5 here."""

    def __init__(self, ask: Callable[[Role, dict, str], dict], roles: dict[str, Role],
                 approvals: Approvals, bus: Bus, knowledge: Knowledge,
                 beacon_factory: Callable[[Callable[[str], dict]], Beacon] | None = None, sandbox=None,
                 releases: Releases | None = None, guardrails: Guardrails | None = None,
                 before_sandbox: Callable[[str], object] | None = None):
        self._ask = ask
        self._roles = roles
        self._approvals = approvals
        self._bus = bus
        self._knowledge = knowledge
        self._beacon_factory = beacon_factory
        self._sandbox = sandbox
        self._releases = releases
        self._before_sandbox = before_sandbox  # frees RAM for Docker (unloads the model when RAM is low)
        self._g = guardrails or load_guardrails(None)
        self._board = Board(bus)
        self._known: dict[tuple[str, str], str] = {}  # (job, floor) → what that floor can tell others

    def steps(self) -> list[Step]:
        return [Step("spec", self._spec), Step("approval", self._approval), Step("f1", self._f1)]

    def app_steps(self) -> list[Step]:
        return [Step("spec", self._app_spec), Step("approval", self._approval),
                Step("research", self._research), Step("dev", self._dev),
                Step("signoff_request", self._signoff_request), Step("signoff", self._signoff)]

    def _research(self, data: dict) -> dict:
        return self._f1(data) if data.get("research") else {"f1": None}

    def _dev(self, data: dict) -> dict:
        job_id, spec, r = data["job_id"], data["spec"], self._roles
        ask = lambda role, prompt: self._call(role, data, prompt)  # noqa: E731
        ws = Workspace(self._sandbox.workspace(job_id))
        def run(cmd: list[str]):
            if self._before_sandbox is not None:
                self._before_sandbox(job_id)
            return self._sandbox.run(job_id, cmd, timeout=90)
        dev = DevFloor(r["f2.architect"], r["f2.coder"], ask=ask, workspace=ws, run=run, hr=r["f2.hr"],
                       stdlib_only=self._g.stdlib_only)
        f3_office = F3Office(r["f3.lead"], r["f3.hr"], ask)
        gate = Gate(ask, r["f5.dev_gate"], self._g.rules)
        qa = QAFloor(r["f4.qa"], ask)
        qa_office = QAOffice(r["f4.lead"], r["f4.qa"], r["f4.hr"], ask)
        oversight = OversightOffice(r["f5.lead"], r["f5.auditor"], ask)
        research, lessons = (data.get("f1") or {}).get("summary", ""), self._lessons(data)
        cto = CTO(r["cto"], ask)
        online = data.get("research") and not data.get("offline")  # floors 2–5 search only with --research
        look = Lookout(self._beacon_factory if online else None, self._knowledge)
        peek = lambda floor, query, hits=2, chars=700: look.ask(  # noqa: E731
            floor, query, job_id, lambda prompt: self._ask(r[f"glass.{floor}"], data, prompt), hits, chars)
        docs = peek("f2", "python standard library http.server " + spec["title"])
        plan, feedback = self._approved_plan(data, dev, cto, research, lessons, [], docs), []
        units_due = True  # F2 workers write units on the first build and after each re-plan, never on a fix
        focus = oversight.focus(spec)
        qa_round = QARound(qa_office, qa, spec)
        qa_round.reset(self._plan_qa(data, plan, qa_office))
        expect = f3_office.expect(spec, plan["routes"])
        for attempt in range(self._g.max_send_backs + 1):
            written: list[int] = []  # F2 workers write the missing planned files first (MVP unit first)

            def on_unit(i: int, n: int, paths: list[str]) -> None:
                written.append(i)
                self._post(data, "f2", "doing", f"coder unit {i}/{n} written: {', '.join(paths)}")
            coder_qa = contract_checks(plan["routes"], coder_token(job_id))[0] + qa_round.coder_checks  # tower first
            unit_notes = dev.write_units(spec, plan, coder_qa, on_unit=on_unit) if units_due else []
            units_due = False
            present = {p.lower() for p in ws.files()}
            missing = [f["path"] for f in plan["files"] if f["path"].lower() not in present]
            if written and missing:
                unit_notes.append(f"planned files still missing: {', '.join(missing[:8])}; write them")
            package = dev.build(spec, plan, unit_notes + list(feedback), coder_qa,  # unit notes first: never cut
                                test_first=bool(written) and not feedback and not missing)
            f3, f4, sec, audit, notes = None, None, None, "", ()
            tests_ok = bool(package.checks_run and package.checks_run[-1].get("pass"))
            go, reasons = f2_handoff(package.checks_run, plan["entry"], ws.files())  # the tower's checks decide
            self._post(data, "f2", "doing", board_line(package.checks_run, attempt, go, reasons))
            self._handoff(data, "f2", attempt, go, reasons)
            if package.checks_run and plan["entry"] not in ws.files():
                feedback = [f"the planned entry file {plan['entry']} does not exist; create it"]
                package = WorkPackage("f2", package.summary, ws.files(), [], package.checks_run +
                                      [{"check": "entry", "pass": False}], feedback)
            elif go:
                f3 = build_check(run, plan["entry"], expect, plan["routes"])  # MVP first, then the full app
                self._handoff(data, "f3", attempt, f3.checks_run[-1]["pass"], f3.open_questions)
                self._post(data, "f3", "done" if f3.checks_run[-1]["pass"] else "issue", f3.summary.splitlines()[0])
                if f3.checks_run[-1]["pass"]:
                    tower_qa, decide = contract_checks(plan["routes"], fresh_token())  # a token the coder never saw
                    try:
                        model_qa = qa_round.ensure(plan["routes"], ws.snapshot())
                    except ADVISORY_ERRORS:  # the small model failed: the tower's checks still decide
                        if not tower_qa:
                            raise
                        model_qa = []
                    f4 = run_qa(run, plan["entry"], tower_qa + model_qa, decide=decide)
                    self._handoff(data, "f4", attempt, f4.checks_run[-1]["pass"], f4.open_questions)
                    self._post(data, "f4", "done" if f4.checks_run[-1]["pass"] else "issue",
                               qa_headline(f4.checks_run[-1].get("results") or [], f4.checks_run[-1]["pass"],
                                           decide), known=f4.summary[:1500])
                if f4 is not None and f4.checks_run[-1]["pass"]:  # Floor 5 office: security scan, then spec audit
                    sec = security_package(xss_probe(run, plan["entry"], plan["routes"])  # probe first: never cut
                                           + security_scan(ws.root, ws.files()), self._g.security_fail_on)
                    self._handoff(data, "f5", attempt, sec.checks_run[-1]["pass"], sec.open_questions)
                    self._post(data, "f5", "doing" if sec.checks_run[-1]["pass"] else "issue",
                               sec.summary.splitlines()[0], known=sec.summary[:1500])
                    if sec.checks_run[-1]["pass"]:
                        audit = oversight.audit(spec, focus, ws.snapshot(3000), f4.summary)
                later = [p for p in (f3, f4, sec) if p is not None]
                f2_summary, f2_questions, notes = for_gate(package.summary, package.open_questions, tests_ok)
                notes += (QA_ADVISORY,) if f4 is not None and f4.checks_run[-1]["pass"] and f4.checks_run[-1].get(
                    "advisory_failed") else ()
                package = WorkPackage("dev", "\n\n".join([f2_summary] + [p.summary for p in later]
                                                         + ([f"Oversight audit:\n{audit}"] if audit else []))
                                      + f"\n\nCode:\n{ws.snapshot(3000)}", ws.files(), [],
                                      package.checks_run + [c for p in later for c in p.checks_run],
                                      f2_questions + [q for p in later for q in p.open_questions])
            verdict = gate.check(spec, package, DEV_ROUTES, notes)
            self._bus.publish("gate.verdict", {"floor": "dev", "attempt": attempt, "passed": verdict.passed,
                                               "reasons": verdict.reasons, "route": verdict.route}, job_id)
            objection = model_objection(verdict, package, f3, f4, sec, attempt)  # 6v: only the model objects
            self._post(data, "f5", "done" if verdict.passed else "issue", "gate passed the app" if verdict.passed
                       else f"gate objected; all tower checks passed, owner decides: {'; '.join(objection)[:160]}"
                       if objection else f"gate sent back to {verdict.route}: {'; '.join(verdict.reasons)[:200]}")
            if verdict.passed or objection:
                self._retro(data, oversight, passed=None if objection else True)
                evidence = _evidence(package.checks_run, self._g.security_fail_on)
                ceo_ok, ceo_note = CEO(r["ceo"], ask).recommend(spec, evidence, audit)
                if objection:  # the owner signs off even under --yes, with the objection in front of them
                    ceo_ok, ceo_note = False, objection_note(objection, ceo_note)
                return {"dev": package.to_dict(), "files": ws.files(), "workspace": str(ws.root),
                        "entry": plan["entry"], "manifest": manifest_of(ws.root, ws.files()),
                        "evidence": evidence, "ceo": {"approve": ceo_ok, "note": ceo_note},
                        "answer": (f"App ready in {ws.root}\nFiles: {', '.join(ws.files())}\n"
                                   "Note: written by a local AI and tested only inside the sandbox — untested on "
                                   "your Mac. Read the code before running it.\n"
                                   + ("" if tests_ok else "Note: the coder's own unit tests fail (advisory); "
                                      "the tower's start, QA and security checks passed.\n")
                                   + f"Run it: cd {shlex.quote(str(ws.root))} && python {shlex.quote(plan['entry'])}"
                                   "  (then open http://127.0.0.1:8000)\n"
                                   f"Safer — deploy it isolated, with no internet: watchtower deploy {job_id}")}
            feedback = verdict.reasons or ["the reviewer rejected the app without reasons"]
            feedback = feedback + static_feedback(go, reasons, plan["entry"], ws.files())
            if f3 is not None and not f3.checks_run[-1]["pass"]:  # show the coder the app's real error
                feedback = feedback + ["Floor 3 started the app and it failed:\n" + untrusted("sandbox", f3.summary)]
                crash = crash_query(f3.summary)
                diagnosis = f3_office.diagnose(f3.summary, peek("f3", crash) if crash else "")
                if diagnosis:
                    feedback.append("Floor 3 HR diagnosis:\n" + untrusted("f3.hr", diagnosis))
                    self._post(data, "f3", "issue", "diagnosis: " + diagnosis)
            elif f4 is not None and not f4.checks_run[-1]["pass"]:
                feedback = feedback + ["Floor 4 QA checks failed:\n" + untrusted("sandbox", f4.summary)]
                feedback += _reference("4", peek("f4", _status_query(f4.checks_run[-1]), 1, 480))  # + header ≤ 600
            elif sec is not None and not sec.checks_run[-1]["pass"]:
                feedback = feedback + ["Floor 5 security scan found problems; fix them:\n" + untrusted("security", sec.summary)]
                feedback += _reference("5", peek("f5", _finding_query(sec.checks_run[-1], self._g.security_fail_on), 1, 480))
            if verdict.route in ("design", "research"):
                plan, units_due = self._approved_plan(data, dev, cto, research, lessons, feedback, docs), True
                qa_round.reset(self._plan_qa(data, plan, qa_office))
                expect = f3_office.expect(spec, plan["routes"])
        self._retro(data, oversight, passed=False)
        raise NeedsOwner(f"gate rejected the app {self._g.max_send_backs + 1} times: {'; '.join(feedback)[:300]}")

    def _signoff_request(self, data: dict) -> dict:
        """Lifecycle: final audit → CEO recommendation → owner sign-off → done. Nothing is released until the
        owner signs off; --yes signs off automatically unless the CEO recommends rejecting."""
        ceo = data.get("ceo") or {}
        if data.get("auto_approve") and ceo.get("approve") is not False:
            return {"signoff_id": None}
        answer = data["answer"].replace(  # deploying needs a release, and a release needs this sign-off first
            f"Safer — deploy it isolated, with no internet: watchtower deploy {data['job_id']}",
            f"After you approve: watchtower deploy {data['job_id']}  (isolated, no internet)")
        verdict = {True: "approve", False: "REJECT"}.get(ceo.get("approve"), "no clear view")
        spec = spec_text(data["spec"]) + "\n\n" if data.get("auto_approve") else ""  # the owner never saw it
        note = f" — {ceo['note']}" if ceo.get("note") else ""
        return {"signoff_id": self._approvals.request(data["job_id"], "signoff",
                                                     f"{answer}\n\n{spec}Evidence:\n{data['evidence']}\n\n"
                                                     f"CEO recommends: {verdict}{note}")}

    def _signoff(self, data: dict) -> dict:
        if data.get("signoff_id") is not None:
            status = self._approvals.get(data["signoff_id"]).status
            if status == "rejected":
                raise AppRejected("app rejected by owner")
            if status != "approved":
                raise NeedsOwner(f"app awaiting your sign-off; review it, then: watchtower approve {data['job_id']}")
        if not data.get("manifest"):
            raise NeedsOwner("this job was checkpointed before release pinning; run it again with: watchtower run")
        problems = manifest_problems(Path(data["workspace"]), data["manifest"])
        if problems:  # what ships is exactly what passed QA and the gate, or nothing
            raise NeedsOwner("workspace changed after QA; nothing released: " + "; ".join(problems[:3])
                             + f". Restore those files, then: watchtower resume {data['job_id']}")
        if self._releases is not None:
            self._releases.record_manifest(data["job_id"], data["entry"], data["manifest"])
        self._bus.publish("app.released", {"entry": data["entry"], "files": len(data["files"])}, data["job_id"])
        return {"released": True}

    def _lessons(self, data: dict) -> str:
        """Past retrospectives that match this job (stored untrusted; shown to the architect wrapped)."""
        hits = {}
        for query in (data["prompt"], f"{data['spec']['title']} {data['spec']['goal']}"):
            for h in self._knowledge.search(query, limit=8, distinct=True):
                if h.source.startswith("watchtower://retro/") and h.source != f"watchtower://retro/{data['job_id']}":
                    hits.setdefault(h.source, h.text[:400])
        return "\n".join(list(hits.values())[:2])

    def _retro(self, data: dict, oversight: OversightOffice, passed: bool | None) -> None:
        """Never lets a retrospective problem cost the job: any error is logged and skipped."""
        try:
            self._write_retro(data, oversight, passed)
        except Exception as e:  # noqa: BLE001 — advisory by design
            self._bus.publish("retro.skipped", {"error": type(e).__name__}, data["job_id"])

    def _write_retro(self, data: dict, oversight: OversightOffice, passed: bool | None) -> None:
        notes = [f"{n['floor']} {n['kind']}: {n['text']}" for n in self._board.notes(data["job_id"])][-12:]
        lessons = [x for x in oversight.retro(data["spec"], notes) if not INJECTION.search(normalize(x))]
        if lessons:
            outcome = {True: "passed", False: "did not pass"}.get(
                passed, "passed tower checks; gate objected, owner deciding")
            self._knowledge.add(f"Lessons from job {data['job_id']} ({data['spec']['title']}, {outcome}):\n"
                                + "\n".join(f"- {x}" for x in lessons), f"watchtower://retro/{data['job_id']}",
                                title=f"Retrospective: {data['spec']['title']}", trusted=False)
            self._post(data, "f5", "done", "lessons: " + "; ".join(lessons))

    def _call(self, role: Role, data: dict, prompt: str) -> dict:
        """The one door every floor agent goes through: it hears the tower board and may send a memo."""
        job_id = data["job_id"]
        brief = self._board.brief(job_id, role.floor) if role.floor in FLOORS else ""
        out = self._ask(role, data, prompt + (BOARD_HEADER + untrusted("board", brief) if brief else ""))
        if role.id in MEMO_SENDERS and isinstance(out, dict) and isinstance(out.get("memo"), dict):
            self._route_memo(role, data, out["memo"])
        return out

    def _route_memo(self, sender: Role, data: dict, memo: dict) -> None:
        job_id, to = data["job_id"], str(memo.get("to") or "").strip().lower()
        question = " ".join(str(memo.get("question") or "").split())[:120]
        lead = self._roles.get(FLOOR_LEADS.get(to, ""))
        if lead is None or to == sender.floor or not question:
            return
        notes = self._board.notes(job_id)
        if sum(n["kind"] == "memo" and n["floor"] == sender.floor for n in notes) >= MAX_MEMOS:
            return
        own = [n["text"] for n in notes if n["floor"] == to and n["kind"] != "memo"][-5:]
        known = "\n".join(filter(None, [self._known.get((job_id, to), "")[:1200]] + own))
        if not known:  # never let a floor invent what it has not done
            answer = "nothing yet: that floor has not worked on this job"
        else:
            try:  # answered through the raw door: an answer can never send another memo
                out = self._ask(lead, data, MEMO_PROMPT.format(sender=NAMES[sender.floor],
                                                               question=untrusted(sender.floor, question),
                                                               known=untrusted(to, known[:1500])))
                answer = " ".join(str(out.get("answer") or "").split())[:150] or "no answer"
            except ADVISORY_ERRORS:  # a memo never pauses a job
                answer = "no answer"
        self._board.note(job_id, sender.floor, "memo", f"{NAMES[sender.floor]} asked {NAMES[to]}: {question[:50]} → {answer}")

    def _approved_plan(self, data: dict, dev: DevFloor, cto: CTO, research: str, lessons: str,
                       feedback: list[str], docs: str = "") -> dict:
        """Architect plans; the CTO approves or asks for changes once (one re-plan, never a loop)."""
        plan = dev.plan(data["spec"], research, feedback, lessons, docs)
        approved, changes = cto.review(data["spec"], plan, self._g.rules)
        if not approved and changes:
            self._post(data, "f2", "issue", "CTO asked for: " + "; ".join(changes))
            try:  # CTO changes first: the architect sees only the first few feedback items
                plan = dev.plan(data["spec"], research, [f"CTO: {c}" for c in changes[:3]] + list(feedback), lessons, docs)
            except ADVISORY_ERRORS:  # the C-suite is advisory: a failed re-plan keeps the plan we have
                self._post(data, "f2", "issue", "re-plan for the CTO failed; keeping the first plan")
        return plan

    def _handoff(self, data: dict, floor: str, attempt: int, passed: bool, reasons: list[str]) -> None:
        """F5 gate at a floor handoff: deterministic (the floor's own reality checks), recorded for all to see."""
        self._bus.publish("gate.verdict", {"floor": floor, "attempt": attempt, "passed": passed, "kind": "handoff",
                                           "reasons": [str(r)[:200] for r in reasons[:3]]}, data["job_id"])

    def _plan_qa(self, data: dict, plan: dict, qa_office: QAOffice) -> list[dict]:
        """Post the architect's plan, then let the QA office write its checks from the routes contract."""
        self._post(data, "f2", "doing", f"plan: {', '.join(f['path'] for f in plan['files'])}; entry {plan['entry']}",
                   known=json.dumps(plan))
        checks = qa_office.plan_checks(data["spec"], plan["routes"])
        if checks:
            self._post(data, "f4", "plan", "QA will check: " + ", ".join(c["name"] for c in checks),
                       known=json.dumps(checks))
        return checks

    def _post(self, data: dict, floor: str, kind: str, text: str, known: str | None = None) -> None:
        self._board.note(data["job_id"], floor, kind, text)
        if known is not None:
            self._known[(data["job_id"], floor)] = known

    def questions(self, data: dict) -> list[str]:
        out = self._ask(self._roles["cpo"], data, QUESTIONS_PROMPT.format(goal=data["prompt"], context=self._context(data["prompt"]) or "(none)"))
        return strs(out.get("questions"), cap=3)

    def _app_spec(self, data: dict) -> dict:
        return self._spec(data, app=True)

    def _spec(self, data: dict, app: bool = False) -> dict:
        qa = "\n".join(f"Q: {x['q']}\nA: {x['a'] or '(no answer)'}" for x in data.get("answers") or []) or "(none)"
        raw = self._ask(self._roles["cpo"], data, SPEC_PROMPT.format(goal=data["prompt"], qa=qa,
                                                                        context=self._context(data["prompt"]) or "(none)"))
        spec = {
            "title": str(raw.get("title") or data["prompt"][:60]),
            "goal": str(raw.get("goal") or data["prompt"]),
            "acceptance": strs(raw.get("acceptance")),
            "out_of_scope": strs(raw.get("out_of_scope")),
        }
        if not spec["acceptance"]:
            raise BadModelOutput("CPO spec has no acceptance criteria; resume to retry")
        if app:
            spec["acceptance"] = enough_criteria(lambda prompt: self._ask(self._roles["cpo"], data, prompt), spec)
        approval_id = None
        if not data.get("auto_approve"):
            approval_id = self._approvals.request(data["job_id"], "spec", spec_text(spec))
        self._bus.publish("spec.written", {"title": spec["title"]}, data["job_id"])
        return {"spec": spec, "approval_id": approval_id}

    def _approval(self, data: dict) -> dict:
        status = "approved" if data.get("auto_approve") else self._approvals.get(data["approval_id"]).status
        if status == "approved":
            return {"approved": True}
        if status == "rejected":
            raise SpecRejected("spec rejected by owner")
        raise NeedsOwner(f"spec awaiting your approval; review it, then: watchtower approve {data['job_id']}")

    def _f1(self, data: dict) -> dict:
        ask = lambda role, prompt: self._call(role, data, prompt)  # noqa: E731
        r = self._roles
        beacon = None
        if self._beacon_factory is not None and not data.get("offline"):
            beacon = self._beacon_factory(lambda prompt: self._ask(r["glass.f1"], data, prompt), "f1")

        def context(task: str) -> str:
            if beacon is None:
                return self._context(task)
            beacon.research(task, data["job_id"])
            conflicts = getattr(beacon, "conflicts", [])  # glass step 5: workers learn where sources disagree
            return self._context(task) + ("\n" + untrusted("glass", "\n".join(conflicts[:3])) if conflicts else "")

        floor = Floor("f1", r["f1.lead"], r["f1.worker"], r["f1.hr"], ask=ask, context=context,
                      min_domains=self._g.min_source_domains if beacon is not None else 0)
        gate = Gate(ask, r["f5.gate"], self._g.rules)
        feedback: list[str] = []
        for attempt in range(self._g.max_send_backs + 1):
            package = floor.run(data["spec"]["goal"], feedback)
            verdict = gate.check(data["spec"], package)
            self._bus.publish("gate.verdict", {"floor": "f1", "attempt": attempt, "passed": verdict.passed,
                                               "reasons": verdict.reasons}, data["job_id"])
            if verdict.passed:
                self._post(data, "f1", "done", "research ready: " + package.summary[:200], known=package.summary)
                return {"f1": package.to_dict(), "answer": package.summary}
            feedback = verdict.reasons or ["the reviewer rejected the package without reasons"]
        raise NeedsOwner(f"gate rejected floor 1 {self._g.max_send_backs + 1} times: {'; '.join(feedback)[:300]}")

    def _context(self, task: str) -> str:
        # re-check stored sources against the CURRENT glass rules: a site denied later never reaches agents
        glass = glass_mod.Glass(glass_mod.load_glass_rules("f1"))
        hits = [h for h in self._knowledge.search(task, limit=12, distinct=False)  # over-fetch: lessons are dropped
                if glass.domain_allowed(h.source) and not h.source.startswith("watchtower://")]  # lessons: architect only
        hits = sorted(hits[:3], key=lambda h: -glass.credibility(h.source))  # step 3: credible sources first
        return "\n".join(("[credible] " if glass.credibility(h.source) == 2 else "")  # outside the data: unforgeable
                         + untrusted(h.source, h.text[:CONTEXT_CHARS]) for h in hits)
