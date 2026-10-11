from __future__ import annotations

import json
from pathlib import PurePosixPath
from typing import Callable, Sequence

from watchtower.engine.floor import WorkPackage, untrusted
from watchtower.engine.sandbox import SandboxResult
from watchtower.engine.stdlib_check import import_problems
from watchtower.engine.workspace import Workspace, WorkspaceError
from watchtower.roles import Role

TEST_COMMAND = ["python", "-m", "unittest", "-q"]
MAX_FILES_PER_ROUND = 3
PLAN_PROMPT = (
    "Spec:\n{spec}\n\nResearch notes:\n{research}\n{feedback}\n"
    'Plan the files. Reply as JSON: {{"files": [{{"path": string, "purpose": string}}], "entry": string}}'
)
CODE_PROMPT = (
    "Spec:\n{spec}\n\nFile plan:\n{plan}\n\nCurrent files:\n{files}\n{feedback}\n"
    "Write or fix up to 3 files so the unittest tests pass and the spec is met. "
    'Reply as JSON: {{"files": [{{"path": string, "content": string}}]}}'
)


def _spec_text(spec: dict) -> str:
    return json.dumps({k: spec.get(k) for k in ("title", "goal", "acceptance", "out_of_scope")}, indent=1)


class DevFloor:
    """Floor 2: the architect plans files; the coder writes and fixes them in a loop driven by real
    sandbox test results (tool-using agent), until tests pass or the round budget runs out."""

    def __init__(self, architect: Role, coder: Role, ask: Callable[[Role, str], dict], workspace: Workspace,
                 run: Callable[[list[str]], SandboxResult], max_rounds: int = 4):
        self._architect, self._coder = architect, coder
        self._ask = ask
        self._ws = workspace
        self._run = run
        self._max_rounds = max_rounds

    def plan(self, spec: dict, research: str, feedback: Sequence[str]) -> dict:
        note = ("\nThe reviewer rejected the last design:\n- " + "\n- ".join(feedback)) if feedback else ""
        out = self._ask(self._architect, PLAN_PROMPT.format(
            spec=_spec_text(spec), research=untrusted("f1", research) if research else "(none)", feedback=note))
        files = [{"path": str(f.get("path", "")).strip(), "purpose": str(f.get("purpose", "")).strip()}
                 for f in out.get("files") or [] if isinstance(f, dict) and str(f.get("path", "")).strip()]
        entry = str(out.get("entry") or "app.py").strip()
        return {"files": files[:15], "entry": entry if entry.endswith(".py") else "app.py"}

    def build(self, spec: dict, plan: dict, feedback: Sequence[str]) -> WorkPackage:
        notes = [f"Reviewer feedback to address: {f}" for f in feedback]
        checks, output, passed = [], "", False
        for round_no in range(self._max_rounds):
            reply = self._ask(self._coder, CODE_PROMPT.format(
                spec=_spec_text(spec), plan=json.dumps(plan, indent=1), files=self._ws.snapshot(),
                feedback=("\n" + "\n".join(notes)) if notes else ""))
            notes = self._write(reply.get("files"))
            self._ensure_packages()
            problems = import_problems(self._ws)
            has_tests = any(PurePosixPath(f).name.startswith("test") for f in self._ws.files() if f.endswith(".py"))
            result = self._run(TEST_COMMAND)
            output = ((result.stdout or "") + (result.stderr or ""))[-2000:]
            ran_tests = "Ran 0 tests" not in output and "NO TESTS RAN" not in output
            passed = result.exit_code == 0 and has_tests and ran_tests and not problems and not result.timed_out
            checks.append({"check": "tests", "round": round_no, "pass": passed, "output": output[-300:]})
            if passed:
                break
            notes += problems
            if not has_tests:
                notes.append("There are no unittest files yet: add test_*.py with real tests.")
            elif not ran_tests:
                notes.append("unittest found 0 tests: name test files test_*.py, put test classes in "
                             "unittest.TestCase subclasses, and name methods test_*.")
            notes.append("Test output:\n" + untrusted("sandbox", output or "(no output)"))
        summary = (f"Entry: {plan['entry']}\nFiles: {', '.join(self._ws.files()) or '(none)'}\n"
                   f"Tests: {'PASS' if passed else 'FAIL'}\n{output[-800:]}")
        questions = [] if passed else [f"tests still failing after {len(checks)} round(s)"]
        return WorkPackage("f2", summary, self._ws.files(), [], checks, questions)

    def _ensure_packages(self) -> None:
        """unittest discovery only enters folders that are packages: add empty __init__.py where missing."""
        folders = {PurePosixPath(f).parent for f in self._ws.files() if f.endswith(".py")}
        for folder in sorted(folders):
            if str(folder) != "." and f"{folder}/__init__.py" not in self._ws.files():
                self._ws.write(f"{folder}/__init__.py", "")

    def _write(self, files) -> list[str]:
        notes = []
        for f in (files if isinstance(files, list) else [])[:MAX_FILES_PER_ROUND]:
            if not isinstance(f, dict):
                continue
            try:
                self._ws.write(str(f.get("path", "")), str(f.get("content", "")))
            except WorkspaceError as e:
                notes.append(f"File rejected: {e}")
        return notes
