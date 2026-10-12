from __future__ import annotations

import json
import re
from pathlib import PurePosixPath
from typing import Callable, Sequence

from watchtower.engine.floor import WorkPackage, untrusted
from watchtower.engine.qafloor import parse_routes
from watchtower.engine.sandbox import SandboxResult
from watchtower.engine.stdlib_check import import_problems
from watchtower.engine.workspace import Workspace, WorkspaceError
from watchtower.roles import Role

TEST_RUNNER = """\
import json, sys, unittest
suite = unittest.defaultTestLoader.discover(".", pattern="test*.py")
result = unittest.TextTestRunner(stream=sys.stderr, verbosity=1).run(suite)
print("WATCHTOWER_TESTS " + json.dumps({"run": result.testsRun, "skipped": len(result.skipped),
      "failures": len(result.failures), "errors": len(result.errors)}), flush=True)
sys.exit(0 if result.wasSuccessful() else 1)
"""
TEST_COMMAND = ["python", "-c", TEST_RUNNER]
_SUMMARY = re.compile(r"^WATCHTOWER_TESTS (\{.*\})$", re.MULTILINE)
_SAFE_ENTRY = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_/]*\.py")


def test_summary(stdout: str) -> dict | None:
    """The runner's own summary line; printed text like 'Ran 2 tests OK' or an early exit never counts."""
    match = _SUMMARY.search(stdout or "")
    try:
        data = json.loads(match.group(1)) if match else None
    except ValueError:
        return None
    return data if isinstance(data, dict) else None
MAX_FILES_PER_ROUND = 3
PLAN_PROMPT = (
    "Spec:\n{spec}\n\nResearch notes:\n{research}\n{feedback}\n"
    "Plan the files and the app's routes (the contract QA will test). Reply as JSON: "
    '{{"files": [{{"path": string, "purpose": string}}], "entry": string, '
    '"routes": [{{"method": "GET" or "POST", "path": string, "fields": [form field names], "shows": string}}]}}'
)
CODE_PROMPT = (
    "Spec:\n{spec}\n\nFile plan and routes contract:\n{plan}\n\nCurrent files:\n{files}\n{qa}{feedback}\n"
    "Write or fix up to 3 files so the unittest tests pass and the spec is met. To remove a stale file, "
    'send {{"path": string, "delete": true}}. Reply as JSON: {{"files": [{{"path": string, "content": string}}]}}'
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
        safe = _SAFE_ENTRY.fullmatch(entry) and ".." not in entry.split("/")
        return {"files": files[:15], "entry": entry if safe else "app.py", "routes": parse_routes(out.get("routes"))}

    def build(self, spec: dict, plan: dict, feedback: Sequence[str], qa_checks: Sequence[dict] = ()) -> WorkPackage:
        notes = [f"Reviewer feedback to address:\n{untrusted('gate', f)}" for f in feedback]
        qa = ("Floor 4 QA will run these HTTP checks against your running app; make them pass:\n"
              + untrusted("f4", json.dumps(list(qa_checks), indent=1)) + "\n") if qa_checks else ""
        checks, output, passed = [], "", False
        for round_no in range(self._max_rounds):
            reply = self._ask(self._coder, CODE_PROMPT.format(
                spec=_spec_text(spec), plan=json.dumps(plan, indent=1), files=untrusted("workspace", self._ws.snapshot()),
                qa=qa, feedback=("\n" + "\n".join(notes)) if notes else ""))
            notes = self._write(reply.get("files"))
            self._ensure_packages()
            problems = import_problems(self._ws)
            has_tests = any(PurePosixPath(f).name.startswith("test") for f in self._ws.files() if f.endswith(".py"))
            result = self._run(TEST_COMMAND)
            output = ((result.stdout or "") + (result.stderr or ""))[-2000:]
            summary = test_summary(result.stdout)
            real = (summary or {}).get("run", 0) - (summary or {}).get("skipped", 0)
            ran_tests = real >= 1
            passed = (result.exit_code == 0 and has_tests and ran_tests and not problems and not result.timed_out
                      and summary is not None and not summary.get("failures") and not summary.get("errors"))
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
                try:
                    self._ws.write(f"{folder}/__init__.py", "")
                except WorkspaceError:
                    pass

    def _write(self, files) -> list[str]:
        notes = []
        for f in (files if isinstance(files, list) else [])[:MAX_FILES_PER_ROUND]:
            if not isinstance(f, dict):
                continue
            try:
                if f.get("delete") is True:
                    self._ws.delete(str(f.get("path", "")))
                else:
                    self._ws.write(str(f.get("path", "")), str(f.get("content", "")))
            except WorkspaceError as e:
                notes.append(f"File rejected: {e}")
        return notes
