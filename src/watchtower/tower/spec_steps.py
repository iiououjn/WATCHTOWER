from __future__ import annotations

from watchtower.beacon import glass as glass_mod
from watchtower.csuite.cpo import enough_criteria
from watchtower.engine.model_socket import BadModelOutput
from watchtower.floors.f1_research.office import Floor
from watchtower.floors.framework import strs, untrusted
from watchtower.floors.gate import Gate
from watchtower.tower.errors import NeedsOwner, SpecRejected

CONTEXT_CHARS = 1500
QUESTIONS_PROMPT = (
    "Owner's goal:\n{goal}\n\nReference data:\n{context}\n\nAsk at most 3 short clarifying questions whose answers "
    'would most change the result. Reply as JSON: {{"questions": [string]}}'
)
SPEC_PROMPT = (
    "Owner's goal:\n{goal}\n\nReference data (use it to understand the owner's terms):\n{context}\n\n"
    "Owner's answers to your questions:\n{qa}\n\n"
    "Write a short spec with 3 to 5 acceptance criteria, each one checkable (for an app: what a user does and "
    'what the page then shows). Reply as JSON: {{"title": string, "goal": string, "acceptance": [string], '
    '"out_of_scope": [string]}}'
)


def spec_text(spec: dict) -> str:
    lines = [f"Title: {spec['title']}", f"Goal: {spec['goal']}", "Acceptance criteria:"]
    lines += [f"  - {a}" for a in spec["acceptance"]]
    lines += ["Out of scope:"] + [f"  - {o}" for o in spec["out_of_scope"] or ["(none)"]]
    return "\n".join(lines)


class SpecSteps:
    """The CPO's questions and spec, the owner's spec approval, and Floor 1 research with its gate (mixed into
    TowerPipeline, which owns `_ask`, `_call`, `_roles`, `_approvals`, `_bus`, `_knowledge` and `_g`)."""

    def questions(self, data: dict) -> list[str]:
        out = self._ask(self._roles["cpo"], data, QUESTIONS_PROMPT.format(
            goal=data["prompt"], context=self._context(data["prompt"]) or "(none)"))
        return strs(out.get("questions"), cap=3)

    def _app_spec(self, data: dict) -> dict:
        return self._spec(data, app=True)

    def _spec(self, data: dict, app: bool = False) -> dict:
        qa = "\n".join(f"Q: {x['q']}\nA: {x['a'] or '(no answer)'}" for x in data.get("answers") or []) or "(none)"
        raw = self._ask(self._roles["cpo"], data, SPEC_PROMPT.format(
            goal=data["prompt"], qa=qa, context=self._context(data["prompt"]) or "(none)"))
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

    def _research(self, data: dict) -> dict:
        return self._f1(data) if data.get("research") else {"f1": None}

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
                if glass.domain_allowed(h.source)
                and not h.source.startswith("watchtower://")]  # lessons: architect only
        hits = sorted(hits[:3], key=lambda h: -glass.credibility(h.source))  # step 3: credible sources first
        return "\n".join(("[credible] " if glass.credibility(h.source) == 2 else "")  # outside the data: unforgeable
                         + untrusted(h.source, h.text[:CONTEXT_CHARS]) for h in hits)
