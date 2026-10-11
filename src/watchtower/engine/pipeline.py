from __future__ import annotations

from typing import Callable

from watchtower.engine.bus import Bus
from watchtower.engine.floor import Floor, strs
from watchtower.engine.gate import Gate
from watchtower.engine.governor.approvals import Approvals
from watchtower.engine.knowledge import Knowledge
from watchtower.engine.model_socket import BadModelOutput
from watchtower.engine.workflow import Step
from watchtower.roles import Role

MAX_SEND_BACKS = 3
QUESTIONS_PROMPT = (
    "Owner's goal:\n{goal}\n\nAsk at most 3 short clarifying questions whose answers would most change "
    'the result. Reply as JSON: {{"questions": [string]}}'
)
SPEC_PROMPT = (
    "Owner's goal:\n{goal}\n\nOwner's answers to your questions:\n{qa}\n\n"
    "Write a short spec. Reply as JSON: "
    '{{"title": string, "goal": string, "acceptance": [string], "out_of_scope": [string]}}'
)


class NeedsOwner(Exception):
    pass


def spec_text(spec: dict) -> str:
    lines = [f"Title: {spec['title']}", f"Goal: {spec['goal']}", "Acceptance criteria:"]
    lines += [f"  - {a}" for a in spec["acceptance"]]
    lines += ["Out of scope:"] + [f"  - {o}" for o in spec["out_of_scope"] or ["(none)"]]
    return "\n".join(lines)


class TowerPipeline:
    """CPO spec → owner approval → Floor 1 with gate. Later phases add floors 2–5 here."""

    def __init__(self, ask: Callable[[Role, dict, str], dict], roles: dict[str, Role],
                 approvals: Approvals, bus: Bus, knowledge: Knowledge):
        self._ask = ask
        self._roles = roles
        self._approvals = approvals
        self._bus = bus
        self._knowledge = knowledge

    def steps(self) -> list[Step]:
        return [Step("spec", self._spec), Step("approval", self._approval), Step("f1", self._f1)]

    def questions(self, data: dict) -> list[str]:
        out = self._ask(self._roles["cpo"], data, QUESTIONS_PROMPT.format(goal=data["prompt"]))
        return strs(out.get("questions"), cap=3)

    def _spec(self, data: dict) -> dict:
        qa = "\n".join(f"Q: {x['q']}\nA: {x['a'] or '(no answer)'}" for x in data.get("answers") or []) or "(none)"
        raw = self._ask(self._roles["cpo"], data, SPEC_PROMPT.format(goal=data["prompt"], qa=qa))
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
        if data.get("auto_approve") or self._approvals.get(data["approval_id"]).status == "approved":
            return {"approved": True}
        raise NeedsOwner(f"spec awaiting your approval; review it, then: watchtower approve {data['job_id']}")

    def _f1(self, data: dict) -> dict:
        ask = lambda role, prompt: self._ask(role, data, prompt)  # noqa: E731
        r = self._roles
        floor = Floor("f1", r["f1.lead"], r["f1.worker"], r["f1.hr"], ask=ask, context=self._context)
        gate = Gate(ask, r["f5.gate"])
        feedback: list[str] = []
        for attempt in range(MAX_SEND_BACKS + 1):
            package = floor.run(data["spec"]["goal"], feedback)
            verdict = gate.check(data["spec"], package)
            self._bus.publish("gate.verdict", {"floor": "f1", "attempt": attempt, "passed": verdict.passed,
                                               "reasons": verdict.reasons}, data["job_id"])
            if verdict.passed:
                return {"f1": package.to_dict(), "answer": package.summary}
            feedback = verdict.reasons or ["the reviewer rejected the package without reasons"]
        raise NeedsOwner(f"gate rejected floor 1 {MAX_SEND_BACKS + 1} times: {'; '.join(feedback)[:300]}")

    def _context(self, task: str) -> str:
        return "\n".join(
            f'<untrusted source="{h.source}">\n{h.snippet}\n</untrusted>'
            for h in self._knowledge.search(task, limit=3)
        )
