from __future__ import annotations

import json
import shlex
from typing import Callable

from watchtower.engine.beacon import glass as glass_mod
from watchtower.engine.beacon.beacon import Beacon
from watchtower.engine.board import FLOORS, NAMES, Board
from watchtower.engine.buildfloor import smoke_test
from watchtower.engine.bus import Bus
from watchtower.engine.devfloor import DevFloor
from watchtower.engine.floor import Floor, WorkPackage, strs, untrusted
from watchtower.engine.gate import Gate
from watchtower.engine.governor.approvals import Approvals
from watchtower.engine.knowledge import Knowledge
from watchtower.engine.model_socket import BadModelOutput
from watchtower.engine.office import QAOffice
from watchtower.engine.qafloor import QAFloor, run_qa
from watchtower.engine.releases import Releases
from watchtower.engine.workflow import Step
from watchtower.engine.workspace import Workspace
from watchtower.roles import Role

MAX_SEND_BACKS = 3
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
    "Write a short spec. Reply as JSON: "
    '{{"title": string, "goal": string, "acceptance": [string], "out_of_scope": [string]}}'
)


class NeedsOwner(Exception):
    pass


class SpecRejected(Exception):
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
                 releases: Releases | None = None):
        self._ask = ask
        self._roles = roles
        self._approvals = approvals
        self._bus = bus
        self._knowledge = knowledge
        self._beacon_factory = beacon_factory
        self._sandbox = sandbox
        self._releases = releases
        self._board = Board(bus)
        self._known: dict[tuple[str, str], str] = {}  # (job, floor) → what that floor can tell others

    def steps(self) -> list[Step]:
        return [Step("spec", self._spec), Step("approval", self._approval), Step("f1", self._f1)]

    def app_steps(self) -> list[Step]:
        return [Step("spec", self._spec), Step("approval", self._approval),
                Step("research", self._research), Step("dev", self._dev)]

    def _research(self, data: dict) -> dict:
        return self._f1(data) if data.get("research") else {"f1": None}

    def _dev(self, data: dict) -> dict:
        job_id, spec, r = data["job_id"], data["spec"], self._roles
        ask = lambda role, prompt: self._call(role, data, prompt)  # noqa: E731
        ws = Workspace(self._sandbox.workspace(job_id))
        run = lambda cmd: self._sandbox.run(job_id, cmd, timeout=90)  # noqa: E731
        dev = DevFloor(r["f2.architect"], r["f2.coder"], ask=ask, workspace=ws, run=run)
        gate = Gate(ask, r["f5.dev_gate"])
        qa = QAFloor(r["f4.qa"], ask)
        qa_office = QAOffice(r["f4.lead"], r["f4.qa"], r["f4.hr"], ask)
        research = (data.get("f1") or {}).get("summary", "")
        plan, feedback = dev.plan(spec, research, []), []
        checks = self._plan_qa(data, plan, qa_office)
        for attempt in range(MAX_SEND_BACKS + 1):
            package, f3, f4 = dev.build(spec, plan, feedback, checks), None, None
            tests_ok = bool(package.checks_run and package.checks_run[-1].get("pass"))
            self._post(data, "f2", "doing", f"unit tests {'pass' if tests_ok else 'still fail'} "
                       f"after {len(package.checks_run)} round(s) (attempt {attempt + 1})")
            if package.checks_run and package.checks_run[-1].get("pass") and plan["entry"] not in ws.files():
                feedback = [f"the planned entry file {plan['entry']} does not exist; create it"]
                package = WorkPackage("f2", package.summary, ws.files(), [], package.checks_run +
                                      [{"check": "entry", "pass": False}], feedback)
            elif package.checks_run and package.checks_run[-1].get("pass"):
                f3 = smoke_test(run, plan["entry"])
                self._post(data, "f3", "done" if f3.checks_run[-1]["pass"] else "issue", f3.summary.splitlines()[0])
                if f3.checks_run[-1]["pass"]:
                    f4 = run_qa(run, plan["entry"], checks or qa.write_checks(spec, ws.snapshot()))
                    self._post(data, "f4", "done" if f4.checks_run[-1]["pass"] else "issue",
                               f4.summary.splitlines()[0], known=f4.summary[:1500])
                later = [p for p in (f3, f4) if p is not None]
                package = WorkPackage("dev", "\n\n".join([package.summary] + [p.summary for p in later])
                                      + f"\n\nCode:\n{ws.snapshot(3000)}", ws.files(), [],
                                      package.checks_run + [c for p in later for c in p.checks_run],
                                      package.open_questions + [q for p in later for q in p.open_questions])
            verdict = gate.check(spec, package, DEV_ROUTES)
            self._bus.publish("gate.verdict", {"floor": "dev", "attempt": attempt, "passed": verdict.passed,
                                               "reasons": verdict.reasons, "route": verdict.route}, job_id)
            self._post(data, "f5", "done" if verdict.passed else "issue", "gate passed the app" if verdict.passed
                       else f"gate sent back to {verdict.route}: {'; '.join(verdict.reasons)[:200]}")
            if verdict.passed:
                if self._releases is not None:
                    self._releases.record(job_id, plan["entry"], ws.root, ws.files())
                self._bus.publish("app.released", {"entry": plan["entry"], "files": len(ws.files())}, job_id)
                return {"dev": package.to_dict(), "files": ws.files(), "workspace": str(ws.root),
                        "answer": (f"App ready in {ws.root}\nFiles: {', '.join(ws.files())}\n"
                                   "Note: written by a local AI and tested only inside the sandbox — untested on "
                                   "your Mac. Read the code before running it.\n"
                                   f"Run it: cd {shlex.quote(str(ws.root))} && python {shlex.quote(plan['entry'])}"
                                   "  (then open http://127.0.0.1:8000)\n"
                                   f"Safer — deploy it isolated, with no internet: watchtower deploy {job_id}")}
            feedback = verdict.reasons or ["the reviewer rejected the app without reasons"]
            if f3 is not None and not f3.checks_run[-1]["pass"]:  # show the coder the app's real error
                feedback = feedback + ["Floor 3 started the app and it failed:\n" + untrusted("sandbox", f3.summary)]
            elif f4 is not None and not f4.checks_run[-1]["pass"]:
                feedback = feedback + ["Floor 4 QA checks failed:\n" + untrusted("sandbox", f4.summary)]
            if verdict.route in ("design", "research"):
                plan = dev.plan(spec, research, feedback)
                checks = self._plan_qa(data, plan, qa_office)
        raise NeedsOwner(f"gate rejected the app {MAX_SEND_BACKS + 1} times: {'; '.join(feedback)[:300]}")

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
        question = " ".join(str(memo.get("question") or "").split())[:300]
        lead = self._roles.get(FLOOR_LEADS.get(to, ""))
        if lead is None or to == sender.floor or not question:
            return
        sent = [n for n in self._board.notes(job_id) if n["kind"] == "memo" and n["floor"] == sender.floor]
        if len(sent) >= MAX_MEMOS:
            return
        known = self._known.get((job_id, to)) or self._board.brief(job_id, to) or "(nothing yet)"
        try:  # answered through the raw door: an answer can never send another memo
            out = self._ask(lead, data, MEMO_PROMPT.format(sender=NAMES[sender.floor],
                                                           question=untrusted(sender.floor, question),
                                                           known=untrusted(to, known[:1500])))
            answer = " ".join(str(out.get("answer") or "").split())[:200] or "no answer"
        except BadModelOutput:
            answer = "no answer"
        self._board.note(job_id, sender.floor, "memo", f"{NAMES[sender.floor]} asked {NAMES[to]}: {question} → {answer}")

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

    def _spec(self, data: dict) -> dict:
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
            beacon = self._beacon_factory(lambda prompt: self._ask(r["glass.f1"], data, prompt))

        def context(task: str) -> str:
            if beacon is not None:
                beacon.research(task, data["job_id"])
            return self._context(task)

        floor = Floor("f1", r["f1.lead"], r["f1.worker"], r["f1.hr"], ask=ask, context=context,
                      min_domains=2 if beacon is not None else 0)
        gate = Gate(ask, r["f5.gate"])
        feedback: list[str] = []
        for attempt in range(MAX_SEND_BACKS + 1):
            package = floor.run(data["spec"]["goal"], feedback)
            verdict = gate.check(data["spec"], package)
            self._bus.publish("gate.verdict", {"floor": "f1", "attempt": attempt, "passed": verdict.passed,
                                               "reasons": verdict.reasons}, data["job_id"])
            if verdict.passed:
                self._post(data, "f1", "done", "research ready: " + package.summary[:200], known=package.summary)
                return {"f1": package.to_dict(), "answer": package.summary}
            feedback = verdict.reasons or ["the reviewer rejected the package without reasons"]
        raise NeedsOwner(f"gate rejected floor 1 {MAX_SEND_BACKS + 1} times: {'; '.join(feedback)[:300]}")

    def _context(self, task: str) -> str:
        # re-check stored sources against the CURRENT glass rules: a site denied later never reaches agents
        glass = glass_mod.Glass(glass_mod.load_glass_rules("f1"))
        hits = [h for h in self._knowledge.search(task, limit=6, distinct=False) if glass.domain_allowed(h.source)]
        return "\n".join(untrusted(h.source, h.text[:CONTEXT_CHARS]) for h in hits[:3])
