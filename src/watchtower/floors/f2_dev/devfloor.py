from __future__ import annotations

import json
import re
from pathlib import PurePosixPath
from typing import Callable, Sequence

from watchtower.floors.framework import WorkPackage, untrusted, untrusted_code
from watchtower.engine.advisory import ADVISORY_ERRORS
from watchtower.engine.model_socket import BadModelOutput
from watchtower.floors.f4_qa_deploy.qafloor import parse_routes
from watchtower.engine.sandbox import SandboxResult
from watchtower.floors.f2_dev.stdlib_check import import_problems
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
    "Spec:\n{spec}\n\nResearch notes:\n{research}\n{lessons}{feedback}\n"
    "Plan the files and the app's routes (the contract QA will test). Reply as JSON: "
    '{{"files": [{{"path": string, "purpose": string}}], "entry": string, '
    '"routes": [{{"method": "GET" or "POST", "path": string, "fields": [form field names], "shows": string}}]}}'
)
CODE_PROMPT = (
    "Spec:\n{spec}\n\nFile plan and routes contract:\n{plan}\n\nCurrent files:\n{files}\n{qa}{feedback}\n"
    "Write or fix up to 3 files so the unittest tests pass and the spec is met. To remove a stale file, "
    'send {{"path": string, "delete": true}}. Reply as JSON: {{"files": [{{"path": string, "content": string}}]}}'
)


HR_PROMPT = (
    "Spec:\n{spec}\n\nPlan and routes contract:\n{plan}\n\nCode:\n{code}\n\nThe unit tests pass. Does the code "
    "meet the spec and follow the plan and routes contract? Reply as JSON: "
    '{{"pass": boolean, "reason": string}}'
)
MAX_HR_ASKS = 2
FEEDBACK_ITEM, FEEDBACK_TOTAL, QA_CHARS = 600, 2000, 1500  # keep the coder prompt inside num_ctx
PROMPT_CHARS = 9_000  # + system (~1.2k) + tower brief (~0.8k) ≈ 3.4k tokens; + 2048 output < num_ctx 6144
_UNSAFE = re.compile(r"[<>{}\x00-\x1f\x7f]")


def _compact_checks(checks: Sequence[dict]) -> str:
    """QA checks for the coder: compact JSON, long values trimmed, total capped."""
    trimmed = [{**c, "form": {k: str(v)[:60] for k, v in c.get("form", {}).items()},
                "expect_text": str(c.get("expect_text", ""))[:80]} for c in checks]
    text = json.dumps(trimmed)
    return text if len(text) <= QA_CHARS else text[:QA_CHARS] + " ...(more checks)"


def _spec_text(spec: dict) -> str:
    return json.dumps({k: spec.get(k) for k in ("title", "goal", "acceptance", "out_of_scope")}, indent=1)


class DevFloor:
    """Floor 2: the architect plans files; the coder writes and fixes them in a loop driven by real
    sandbox test results (tool-using agent), until tests pass or the round budget runs out."""

    def __init__(self, architect: Role, coder: Role, ask: Callable[[Role, str], dict], workspace: Workspace,
                 run: Callable[[list[str]], SandboxResult], max_rounds: int = 4, hr: Role | None = None,
                 stdlib_only: bool = True):
        self._architect, self._coder, self._hr = architect, coder, hr
        self._stdlib_only = stdlib_only
        self._ask = ask
        self._ws = workspace
        self._run = run
        self._max_rounds = max_rounds

    def plan(self, spec: dict, research: str, feedback: Sequence[str], lessons: str = "") -> dict:
        note = ("\nThe reviewer rejected the last design:\n" + "\n".join(untrusted("gate", str(f)[:FEEDBACK_ITEM])
                                                                    for f in feedback[:5])) if feedback else ""
        out = self._ask(self._architect, PLAN_PROMPT.format(
            spec=_spec_text(spec), research=untrusted("f1", research) if research else "(none)", feedback=note,
            lessons=("\nLessons from past jobs:\n" + untrusted("retro", lessons[:800]) + "\n") if lessons else ""))
        files = [{"path": str(f.get("path", "")).strip()[:100], "purpose": _UNSAFE.sub("", str(f.get("purpose", ""))).strip()[:80]}
                 for f in out.get("files") or [] if isinstance(f, dict)
                 and 0 < len(str(f.get("path", "")).strip()) <= 100]
        entry = str(out.get("entry") or "app.py").strip()
        safe = _SAFE_ENTRY.fullmatch(entry) and ".." not in entry.split("/")
        entry, files = (entry if safe else "app.py"), files[:15]
        if entry not in {f["path"] for f in files}:  # a 3B architect often names an entry it never plans
            files = files[:14] + [{"path": entry, "purpose": "the app's entry point: starts the HTTP server"}]
        return {"files": files, "entry": entry, "routes": parse_routes(out.get("routes"))}

    def build(self, spec: dict, plan: dict, feedback: Sequence[str], qa_checks: Sequence[dict] = ()) -> WorkPackage:
        kept, used = [], 0
        for f in feedback:
            item = str(f)[:FEEDBACK_ITEM]
            if used + len(item) > FEEDBACK_TOTAL:
                break
            kept.append(item)
            used += len(item)
        notes = [f"Reviewer feedback to address:\n{untrusted('gate', f)}" for f in kept]
        qa = ("Floor 4 QA will run these HTTP checks against your running app; make them pass:\n"
              + untrusted("f4", _compact_checks(qa_checks)) + "\n") if qa_checks else ""
        checks, output, passed, hr_asks, hr_question = [], "", False, 0, None
        for round_no in range(self._max_rounds):
            parts = dict(spec=_spec_text(spec), plan=untrusted("f2.architect", json.dumps(plan)), qa=qa,
                         feedback=("\n" + "\n".join(notes)) if notes else "")
            while notes and len(CODE_PROMPT.format(files="", **parts)) > PROMPT_CHARS - 1500:
                notes = notes[1:]  # oldest notes go first: the snapshot must stay readable
                parts["feedback"] = ("\n" + "\n".join(notes)) if notes else ""
            room = max(1500, min(6000, PROMPT_CHARS - len(CODE_PROMPT.format(files="", **parts))))
            try:
                reply = self._ask(self._coder, CODE_PROMPT.format(
                    files=untrusted_code("workspace", self._ws.snapshot(room)), **parts))
            except BadModelOutput:  # a garbled reply costs this round, not the whole job
                checks.append({"check": "tests", "round": round_no, "pass": False,
                               "output": "coder reply was not valid JSON"})
                notes = ["Your last reply was not valid JSON. Reply with one JSON object; escape every double "
                         "quote and newline inside file contents (\\\" and \\n)."]
                continue
            notes = self._write(reply.get("files"))
            self._ensure_packages()
            problems = import_problems(self._ws) if self._stdlib_only else []
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
                verdict = self._hr_review(spec, plan) if self._hr is not None and hr_asks < MAX_HR_ASKS else None
                if verdict is None or verdict[0]:
                    break
                hr_asks += 1
                if hr_asks >= MAX_HR_ASKS or round_no == self._max_rounds - 1:
                    hr_question = f"F2 HR not satisfied: {verdict[1][:200]}"
                    break
                notes.append("Floor 2 HR reviewed your code and asked for changes:\n" + untrusted("f2.hr", verdict[1]))
                continue
            notes += problems
            if not has_tests:
                notes.append("There are no unittest files yet: add test_*.py with real tests.")
            elif not ran_tests:
                notes.append("unittest found 0 tests: name test files test_*.py, put test classes in "
                             "unittest.TestCase subclasses, and name methods test_*.")
            notes.append("Test output:\n" + untrusted("sandbox", (output or "(no output)")[-1200:]))
        summary = (f"Entry: {plan['entry']}\nFiles: {', '.join(self._ws.files()) or '(none)'}\n"
                   f"Tests: {'PASS' if passed else 'FAIL'}\n{output[-800:]}")
        questions = [] if passed else [f"tests still failing after {len(checks)} round(s)"]
        questions += [hr_question] if hr_question else []
        return WorkPackage("f2", summary, self._ws.files(), [], checks, questions)

    def _hr_review(self, spec: dict, plan: dict) -> tuple[bool, str] | None:
        """Floor 2 HR: a second model family reads the passing code against the spec. Garbage → skipped."""
        try:
            out = self._ask(self._hr, HR_PROMPT.format(spec=_spec_text(spec),
                                                        plan=untrusted("f2.architect", json.dumps(plan)),
                                                        code=untrusted_code("workspace", self._ws.snapshot(4500))))
        except ADVISORY_ERRORS:
            return None
        if not isinstance(out.get("pass"), bool):  # no clear verdict from a sloppy model: skip, never veto
            return None
        return out["pass"], str(out.get("reason") or "no reason given").strip()[:300]

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
