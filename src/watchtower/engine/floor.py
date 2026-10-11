from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Callable, Sequence

from watchtower.engine.model_socket import BadModelOutput
from watchtower.roles import Role

LEAD_PROMPT = (
    "Goal:\n{goal}\n\nReference data:\n{context}\n{feedback}\n"
    "Split the goal into at most {n} focused tasks. Plan only tasks the reference data can answer; "
    'do not invent background topics. Reply as JSON: {{"tasks": [string]}}'
)
WORKER_PROMPT = (
    "Task:\n{task}\n\nReference data:\n{context}\n{feedback}\n"
    'Reply as JSON: {{"result": string, "sources": [string]}}'
)
HR_PROMPT = (
    "Task:\n{task}\n\nResult:\n{result}\n\n"
    'Does the result complete the task? Reply as JSON: {{"pass": boolean, "reason": string}}'
)


def strs(value, cap: int = 10) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(v).strip() for v in value if str(v).strip()][:cap]


def truthy(value) -> bool:
    if value is True:
        return True
    return isinstance(value, str) and value.strip().lower() in {"true", "yes", "pass"}


@dataclass(frozen=True)
class WorkPackage:
    floor: str
    summary: str
    artifacts: list[str]
    sources: list[str]
    checks_run: list[dict]
    open_questions: list[str]

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "WorkPackage":
        return cls(**d)

    def validate(self) -> list[str]:
        problems = []
        if not self.summary.strip():
            problems.append("summary is empty")
        if not self.checks_run:
            problems.append("no checks were run")
        sections = [s for s in self.summary.split("## ") if s.strip()]
        if sections and all(s.rstrip().endswith("(no result)") for s in sections):
            problems.append("no task produced a result")
        return problems


class Floor:
    """One floor of the tower: the Lead splits the goal, Workers do each task, HR checks each
    result (redo up to max_redo times). The output is a WorkPackage for the gate."""

    def __init__(self, name: str, lead: Role, worker: Role, hr: Role,
                 ask: Callable[[Role, str], dict], context: Callable[[str], str],
                 max_tasks: int = 3, max_redo: int = 2):
        self.name = name
        self._lead, self._worker, self._hr = lead, worker, hr
        self._ask = ask
        self._context = context
        self._max_tasks = max_tasks
        self._max_redo = max_redo

    def run(self, goal: str, feedback: Sequence[str] = ()) -> WorkPackage:
        gate_note = ""
        if feedback:
            gate_note = "\nThe gate rejected the previous attempt; fix these:\n- " + "\n- ".join(feedback)
        plan = self._ask(self._lead, LEAD_PROMPT.format(goal=goal, context=self._context(goal) or "(none)",
                                                         feedback=gate_note, n=self._max_tasks))
        tasks = strs(plan.get("tasks"))[: self._max_tasks]
        if not tasks:
            raise BadModelOutput(f"{self.name} lead returned no tasks")

        sections, sources, checks, questions = [], [], [], []
        for task in tasks:
            context = self._context(task) or "(none)"
            note, result, reason, passed, out = gate_note, "", "", False, {}
            for attempt in range(self._max_redo + 1):
                out = self._ask(self._worker, WORKER_PROMPT.format(task=task, context=context, feedback=note))
                result = str(out.get("result") or "").strip()
                verdict = self._ask(self._hr, HR_PROMPT.format(task=task, result=result or "(empty)"))
                reason = str(verdict.get("reason") or "").strip()
                passed = truthy(verdict.get("pass")) and bool(result)
                checks.append({"check": "hr", "task": task, "attempt": attempt, "pass": passed,
                               "reason": reason[:200]})
                if passed:
                    break
                note = f"\nHR rejected your last answer: {reason or 'empty or off-task result'}. Fix it."
            sources += strs(out.get("sources"))
            sections.append(f"## {task}\n{result or '(no result)'}")
            if not passed:
                questions.append(f"HR not satisfied with '{task}': {reason or 'empty result'}")
        return WorkPackage(self.name, "\n\n".join(sections), [], list(dict.fromkeys(sources)), checks, questions)
