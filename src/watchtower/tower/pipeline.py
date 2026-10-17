from __future__ import annotations

import json
from typing import Callable

from watchtower.beacon.beacon import Beacon
from watchtower.beacon.glass import INJECTION, normalize
from watchtower.csuite.cto import CTO
from watchtower.engine.advisory import ADVISORY_ERRORS
from watchtower.engine.bus import Bus
from watchtower.engine.governor.approvals import Approvals
from watchtower.engine.knowledge import Knowledge
from watchtower.engine.workflow import Progress, Step
from watchtower.engine.workspace import Workspace
from watchtower.floors.board import Board
from watchtower.floors.f2_dev.devfloor import DevFloor
from watchtower.floors.f2_dev.skeleton import apply as apply_skeleton
from watchtower.floors.f4_qa_deploy.office import QAOffice
from watchtower.floors.f4_qa_deploy.releases import Releases
from watchtower.floors.f5_oversight.office import OversightOffice
from watchtower.guardrails import Guardrails, load_guardrails
from watchtower.roles import Role
from watchtower.tower.dev_run import DevRun
from watchtower.tower.errors import NeedsOwner
from watchtower.tower.memos import MemoDoor
from watchtower.tower.signoff import SignoffSteps
from watchtower.tower.spec_steps import SpecSteps


class TowerPipeline(SpecSteps, MemoDoor, SignoffSteps):
    """The tower's workflows: research (spec → approval → F1) and app (spec → approval → research → dev → sign-off).
    The steps live in their own modules; this class holds the shared parts and the dev loop."""

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
                Step("research", self._research), Step("dev", self._dev, resumable=True),
                Step("signoff_request", self._signoff_request), Step("signoff", self._signoff)]

    def _dev(self, data: dict, progress: Progress | None = None) -> dict:
        """F2→F5 with the gate, up to max_send_backs + 1 attempts, each one checkpointed (8b)."""
        progress = progress or Progress.none()
        run = DevRun(self, data, progress)
        for attempt in range(run.start(), self._g.max_send_backs + 1):
            released = run.attempt(attempt)
            if released is not None:
                return released
        progress.clear()  # out of send-backs: an owner's resume starts a fresh round on purpose
        self._retro(data, run.oversight, passed=False)
        raise NeedsOwner(f"gate rejected the app {self._g.max_send_backs + 1} times: {'; '.join(run.feedback)[:300]}")

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

    def _approved_plan(self, data: dict, dev: DevFloor, cto: CTO, research: str, lessons: str,
                       feedback: list[str], docs: str = "") -> dict:
        """Architect plans; the CTO approves or asks for changes once (one re-plan, never a loop)."""
        plan = dev.plan(data["spec"], research, feedback, lessons, docs)
        approved, changes = cto.review(data["spec"], plan, self._g.rules)
        if not approved and changes:
            self._post(data, "f2", "issue", "CTO asked for: " + "; ".join(changes))
            try:  # CTO changes first: the architect sees only the first few feedback items
                plan = dev.plan(data["spec"], research, [f"CTO: {c}" for c in changes[:3]] + list(feedback), lessons,
                                docs)
            except ADVISORY_ERRORS:  # the C-suite is advisory: a failed re-plan keeps the plan we have
                self._post(data, "f2", "issue", "re-plan for the CTO failed; keeping the first plan")
        ws = Workspace(self._sandbox.workspace(data["job_id"]))
        plan, dev.owned = apply_skeleton(plan, data["spec"]["title"], ws, previous=dev.owned)
        if dev.owned:  # 7a: runs 26-31 failed on HTTP plumbing; for add-and-list apps the tower writes the server
            self._post(data, "f2", "doing", f"tower wrote the web server {plan['entry']}; the coder writes store.py")
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
