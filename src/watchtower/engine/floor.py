from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Callable, Sequence
from urllib.parse import urlsplit

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
    "Task:\n{task}\n\nResult (from the worker):\n{result}\n\n"
    'Does the result complete the task? Reply as JSON: {{"pass": boolean, "reason": string}}'
)


def untrusted(source: str, text: str) -> str:
    """Wrap outside or derived text as data. '<' is escaped so the text cannot close the tag,
    and the source is reduced to URL-safe characters so it cannot break the attribute."""
    safe_source = re.sub(r"[^A-Za-z0-9:/._%#?=&@+~-]", "", source)[:200]
    return f'<untrusted source="{safe_source}">\n{text.replace("<", "&lt;")}\n</untrusted>'


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
                 max_tasks: int = 3, max_redo: int = 2, min_domains: int = 0):
        self.name = name
        self._lead, self._worker, self._hr = lead, worker, hr
        self._ask = ask
        self._context = context
        self._max_tasks = max_tasks
        self._max_redo = max_redo
        self._min_domains = min_domains

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
                verdict = self._ask(self._hr, HR_PROMPT.format(task=task, result=untrusted("f1.worker", result or "(empty)")))
                reason = str(verdict.get("reason") or "").strip()
                passed = truthy(verdict.get("pass")) and bool(result)
                checks.append({"check": "hr", "task": task, "attempt": attempt, "pass": passed,
                               "reason": reason[:200]})
                if passed:
                    break
                note = f"\nHR rejected your last answer: {reason or 'empty or off-task result'}. Fix it."
            cited = [s for s in strs(out.get("sources")) if s in context]  # never trust invented sources
            sources += cited
            hosts = {urlsplit(s).hostname or s for s in cited}
            if passed and self._min_domains and len(hosts) < self._min_domains:
                questions.append(f"only {len(hosts)} independent source(s) for '{task}' (need {self._min_domains})")
            sections.append(f"## {task}\n{result or '(no result)'}")
            if not passed:
                questions.append(f"HR not satisfied with '{task}': {reason or 'empty result'}")
        return WorkPackage(self.name, "\n\n".join(sections), [], list(dict.fromkeys(sources)), checks, questions)
