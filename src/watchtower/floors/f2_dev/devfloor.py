from __future__ import annotations

import ast
import json
import re
from fnmatch import fnmatch
from pathlib import PurePosixPath
from typing import Callable, Sequence

from watchtower.floors.framework import WorkPackage, untrusted, untrusted_code
from watchtower.engine.advisory import ADVISORY_ERRORS
from watchtower.engine.model_socket import BadModelOutput
from watchtower.floors.f4_qa_deploy.qafloor import parse_routes
from watchtower.engine.sandbox import SandboxResult
from watchtower.floors.f2_dev.feedback import (NOTE_CAP, STUCK_NOTE, UNCHANGED_NOTE,  # noqa: F401 (re-export)
                                               _capped, _failure_note, _failure_rows, _problem_note, failures)
from watchtower.floors.f2_dev.repair import repair_imports, repair_strings
from watchtower.floors.f2_dev.stdlib_check import import_problems
from watchtower.engine.workspace import ALLOWED_SUFFIXES, Workspace, WorkspaceError
from watchtower.roles import Role

TEST_RUNNER = """\
import fnmatch, inspect, json, os, sys, unittest
class Fn(unittest.FunctionTestCase):  # pytest-style 'def test_x(): assert ...' runs too, named like a method
    def __str__(self):
        f = self._testFunc
        name = getattr(f, "__name__", str(f))
        return f"{name} ({getattr(f, '__module__', '?')}.{name})"
def plain(fn):
    if inspect.iscoroutinefunction(fn) or inspect.isgeneratorfunction(fn):
        def refuse():
            raise AssertionError("async/generator test functions are not run: use a plain def, or "
                                 "unittest.IsolatedAsyncioTestCase")
        refuse.__name__, refuse.__module__ = fn.__name__, fn.__module__
        return refuse
    return fn
def no_args(fn):
    try:  # mock.patch injects its own arguments: judge the wrapper, not the wrapped function
        sig = inspect.signature(fn, follow_wrapped=not hasattr(fn, "patchings"))
    except (ValueError, TypeError):
        return False
    return all(p.default is not p.empty or p.kind in (p.VAR_POSITIONAL, p.VAR_KEYWORD) for p in sig.parameters.values())
class Loader(unittest.TestLoader):
    def loadTestsFromModule(self, module, *args, **kwargs):
        suite = super().loadTestsFromModule(module, *args, **kwargs)
        if not fnmatch.fnmatch(os.path.basename(getattr(module, "__file__", None) or ""), "test*.py"):
            return suite  # app packages are not test files, even when discovery walks them
        case = type("Fn", (Fn,), {"__module__": module.__name__})  # module fixtures wrap these tests too
        for name, fn in sorted(vars(module).items()):
            if (name.startswith("test") and name != "test_main" and inspect.isfunction(fn)  # test_main: legacy
                    and fn.__name__ != "<lambda>" and fn.__module__ == module.__name__
                    and no_args(fn)):  # a helper that takes arguments is not a test
                suite.addTest(case(plain(fn)))
        return suite
suite = Loader().discover(".", pattern="test*.py")
result = unittest.TextTestRunner(stream=sys.stderr, verbosity=1).run(suite)
print("WATCHTOWER_TESTS " + json.dumps({"run": result.testsRun, "skipped": len(result.skipped),
      "failures": len(result.failures), "errors": len(result.errors)}), flush=True)
sys.exit(0 if result.wasSuccessful() else 1)
"""
TEST_COMMAND = ["python", "-I", "-c", TEST_RUNNER]  # -I: app files cannot shadow json/unittest
_SUMMARY = re.compile(r"^WATCHTOWER_TESTS (\{.*\})$", re.MULTILINE)
_SAFE_ENTRY = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(/[A-Za-z_][A-Za-z0-9_]*)*\.py")  # importable by tests


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
    "Spec:\n{spec}\n\nResearch notes:\n{research}\n{reference}{lessons}{feedback}\n"
    "Plan the files and the app's routes (the contract QA will test). Reply as JSON: "
    '{{"files": [{{"path": string, "purpose": string}}], "entry": string, '
    '"routes": [{{"method": "GET" or "POST", "path": string, "fields": [form field names], "shows": string}}]}}'
)
CODE_PROMPT = (
    "Spec:\n{spec}\n\nFile plan and routes contract:\n{plan}\n\nCurrent files:\n{files}\n{qa}{feedback}\n"
    "Write or fix up to 3 files so the unittest tests pass and the spec is met. Reply with one block per file "
    "(### FILE: path, then the complete file in a ``` fence); to remove a stale file write ### DELETE: path."
)


UNIT_PROMPT = (
    "Spec:\n{spec}\n\nFile plan and routes contract:\n{plan}\n\nFiles already written:\n{files}\n{qa}\n"
    "You are coder {i} of {n} on this floor. Write ONLY these files, complete and working:\n{unit}\n"
    "Reply with one block per file: ### FILE: path, then the complete file in a ``` fence."
)
MAX_UNITS, UNIT_FILES = 4, 3
HR_PROMPT = (
    "Spec:\n{spec}\n\nPlan and routes contract:\n{plan}\n\nCode:\n{code}\n\nThe unit tests pass. Does the code "
    "meet the spec and follow the plan and routes contract? Reply as JSON: "
    '{{"pass": boolean, "reason": string}}'
)
MAX_HR_ASKS = 2
MAX_DIAGNOSES = 2
FEEDBACK_ITEM, FEEDBACK_TOTAL, QA_CHARS = 600, 2000, 1500  # keep the coder prompt inside num_ctx
PROMPT_CHARS = 9_000  # + system (~1.2k) + tower brief (~0.8k) ≈ 3.4k tokens; + 2048 output < num_ctx 6144
_UNSAFE = re.compile(r"[<>{}\x00-\x1f\x7f]")


def _compact_checks(checks: Sequence[dict]) -> str:
    """QA checks for the coder: compact JSON, long values trimmed, total capped."""
    trimmed = [{**c, "form": {k: str(v)[:60] for k, v in c.get("form", {}).items()},
                "expect_text": str(c.get("expect_text", ""))[:80]} for c in checks]
    text = json.dumps(trimmed)
    return text if len(text) <= QA_CHARS else text[:QA_CHARS] + " ...(more checks)"


TEST_DIAGNOSE_PROMPT = (
    "The coder's unit tests keep failing the same way. unittest's report:\n{report}\n\nIn one or two plain "
    "sentences: is the test wrong or the code, and what exactly should change? Reply as JSON: "
    '{{"diagnosis": string}}'
)




def _format_notes(reply: dict) -> list[str]:
    """What the file-block reader could not use (a block left open, cut off …): the coder must hear it."""
    return [str(n)[:200] for n in (reply.get("notes") if isinstance(reply.get("notes"), list) else [])][:3]


def _is_test_file(path: str) -> bool:
    """Exactly what the runner discovers: test*.py anywhere (_ensure_packages makes every folder a package)."""
    return fnmatch(PurePosixPath(path).name, "test*.py")


def app_is_tested(ws: Workspace) -> bool:
    """At least one test file imports a module of the app itself (not only unittest or another test file):
    a test that never touches the app proves nothing."""
    py = [f for f in ws.files() if f.endswith(".py")]
    tests = [f for f in py if _is_test_file(f)]
    app = {PurePosixPath(f).with_suffix("").as_posix().replace("/", ".") for f in py
           if f not in tests and PurePosixPath(f).stem not in ("__init__", "conftest")
           and not {"tests", "test"} & set(PurePosixPath(f).parts[:-1])}  # helpers in tests/ are not the app
    app |= {m.split(".")[0] for m in app}  # 'import store' counts for store/db.py
    for name in tests:
        try:
            tree = ast.parse(ws.read(name))
        except (SyntaxError, ValueError, RecursionError, MemoryError):
            continue
        for node in ast.walk(tree):
            mods = ([a.name for a in node.names] if isinstance(node, ast.Import)
                    else [node.module or ""] if isinstance(node, ast.ImportFrom)
                    else [node.args[0].value] if (isinstance(node, ast.Call) and node.args  # import_module("app")
                                                  and isinstance(node.args[0], ast.Constant)
                                                  and isinstance(node.args[0].value, str)
                                                  and getattr(node.func, "attr", getattr(node.func, "id", ""))
                                                  in ("import_module", "__import__")) else [])
            if any(m in app for m in mods):
                return True
    return False


def _plan_path(raw) -> str | None:
    """A planned path as the workspace will name it ('./a.py' → 'a.py'), or None if it could never be written."""
    text = str(raw or "").strip()
    if not 0 < len(text) <= 100 or "\\" in text or any(ord(c) < 32 or c == "\x7f" for c in text):
        return None
    rel = PurePosixPath(text)
    if rel.is_absolute() or ".." in rel.parts or any(p.startswith(".") for p in rel.parts):
        return None
    return rel.as_posix() if rel.suffix in ALLOWED_SUFFIXES else None


def units(plan: dict) -> list[list[dict]]:
    """F2 Lead's split, by code: unit 1 is the MVP (entry + test files), then the other planned files in
    groups of up to 3, in plan order; at most 4 units (the fix loop writes anything left over)."""
    files = list({f["path"]: f for f in plan["files"]}.values())
    first = [f for f in files if f["path"] == plan["entry"]]
    first += [f for f in files if PurePosixPath(f["path"]).name.startswith("test")][:UNIT_FILES - len(first)]
    rest = [f for f in files if f not in first]
    split = [first] if first else []
    split += [rest[i:i + UNIT_FILES] for i in range(0, len(rest), UNIT_FILES)]
    return split[:MAX_UNITS]


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

    def plan(self, spec: dict, research: str, feedback: Sequence[str], lessons: str = "", reference: str = "") -> dict:
        note = ("\nThe reviewer rejected the last design:\n" + "\n".join(untrusted("gate", str(f)[:FEEDBACK_ITEM])
                                                                    for f in feedback[:5])) if feedback else ""
        out = self._ask(self._architect, PLAN_PROMPT.format(
            spec=_spec_text(spec), research=untrusted("f1", research) if research else "(none)", feedback=note,
            lessons=("\nLessons from past jobs:\n" + untrusted("retro", lessons[:800]) + "\n") if lessons else "",
            reference=("\nReference docs (from the web through Glass 2; may be wrong):\n" + reference + "\n")
            if reference else ""))
        files, seen = [], set()
        for f in out.get("files") or []:
            path = _plan_path(f.get("path")) if isinstance(f, dict) else None
            if path is not None and path.lower() not in seen:  # one name per file, even on case-blind disks
                seen.add(path.lower())
                files.append({"path": path, "purpose": _UNSAFE.sub("", str(f.get("purpose", ""))).strip()[:80]})
        entry = _plan_path(out.get("entry")) or "app.py"
        if not _SAFE_ENTRY.fullmatch(entry):
            fixed = re.sub(r"(^|/)(?=\d)", r"\1app_", entry)  # '2048.py' → 'app_2048.py': tests can import it
            if _SAFE_ENTRY.fullmatch(fixed):
                files = [{**f, "path": fixed} if f["path"] == entry else f for f in files]
            entry = fixed if _SAFE_ENTRY.fullmatch(fixed) else "app.py"
        files = files[:15]
        files = [f for f in files if f["path"] == entry or f["path"].lower() != entry.lower()]
        if entry not in {f["path"] for f in files}:  # a 3B architect often names an entry it never plans
            files = files[:14] + [{"path": entry, "purpose": "the app's entry point: starts the HTTP server"}]
        return {"files": files, "entry": entry, "routes": parse_routes(out.get("routes"))}

    def write_units(self, spec: dict, plan: dict, qa_checks: Sequence[dict] = (),
                    on_unit: Callable[[int, int, list[str]], None] | None = None) -> list[str]:
        """F2 workers: one coder call per unit that still has missing files, back to back on the coder model.
        A worker writes only its own unit's files; a garbled reply costs that unit (the fix loop catches up)."""
        present = {p.lower() for p in self._ws.files()}  # macOS disks are case-blind: App.py is app.py
        todo = [[f for f in u if f["path"].lower() not in present] for u in units(plan)]
        todo = [u for u in todo if u]  # a worker writes only files that do not exist yet: never a fixed one
        qa = ("Floor 4 QA will run these HTTP checks against the app:\n"
              + untrusted("f4", _compact_checks(qa_checks)) + "\n") if qa_checks else ""
        notes: list[str] = []
        stray: list[str] = []
        for i, unit in enumerate(todo, start=1):
            paths = [f["path"] for f in unit]
            parts = dict(spec=_spec_text(spec), plan=untrusted("f2.architect", json.dumps(plan)), qa=qa, i=i,
                         n=len(todo), unit=untrusted("f2.architect", "\n".join(f"- {f['path']}: {f['purpose']}"
                                                                               for f in unit)))
            room = max(1500, min(6000, PROMPT_CHARS - len(UNIT_PROMPT.format(files="", **parts))))
            try:
                reply = self._ask(self._coder, UNIT_PROMPT.format(
                    files=untrusted_code("workspace", self._ws.snapshot(room) or "(none yet)"), **parts))
            except BadModelOutput:  # low memory or a dead model pauses the job, as for any coder call
                notes.append(f"coder {i} gave no usable reply for {', '.join(paths)}; write those files")
                continue
            files = reply.get("files") if isinstance(reply.get("files"), list) else []
            mine = [f for f in files if isinstance(f, dict) and f.get("path") in paths and f.get("delete") is not True]
            stray += [str(f.get("path"))[:100] for f in files if isinstance(f, dict) and f not in mine]
            before = set(self._ws.files())
            notes += _format_notes(reply) + self._write(mine)
            if on_unit is not None and set(self._ws.files()) - before:
                on_unit(i, len(todo), paths)
        written = {p.lower() for p in self._ws.files()}  # a stray file another unit then wrote is no news
        return notes + [f"File rejected: {p!r} was outside your unit" for p in dict.fromkeys(stray)
                        if p.lower() not in written]

    def build(self, spec: dict, plan: dict, feedback: Sequence[str], qa_checks: Sequence[dict] = (),
              test_first: bool = False) -> WorkPackage:
        kept, used = [], 0
        for f in feedback:
            item = str(f)[:FEEDBACK_ITEM]
            if used + len(item) > FEEDBACK_TOTAL:
                break
            kept.append(item)
            used += len(item)
        notes = [f"Reviewer feedback to address:\n{_capped('gate', f, 800)}" for f in kept]
        qa = ("Floor 4 QA will run these HTTP checks against your running app; make them pass:\n"
              + untrusted("f4", _compact_checks(qa_checks)) + "\n") if qa_checks else ""
        checks, output, passed, hr_asks, hr_question = [], "", False, 0, None
        last_failing, diagnoses, diagnosis, diagnosed_for, carry = None, 0, "", None, []  # stuck = same set twice
        for round_no in range(self._max_rounds):
            parts = dict(spec=_spec_text(spec), plan=untrusted("f2.architect", json.dumps(plan)), qa=qa,
                         feedback=("\n" + "\n".join(notes)) if notes else "")
            while len(notes) > 1 and len(CODE_PROMPT.format(files="", **parts)) > PROMPT_CHARS - 1500:
                notes = notes[1:]  # oldest notes go first (the newest, most important one is kept)
                parts["feedback"] = ("\n" + "\n".join(notes)) if notes else ""
            room = max(1500, min(6000, PROMPT_CHARS - len(CODE_PROMPT.format(files="", **parts))))
            if test_first and round_no == 0:  # the unit workers just wrote every file: test before rewriting
                notes = []
            else:
                try:
                    reply = self._ask(self._coder, CODE_PROMPT.format(
                        files=untrusted_code("workspace", self._ws.snapshot(room)), **parts))
                except BadModelOutput:  # a garbled reply costs this round, not the whole job
                    checks.append({"check": "tests", "round": round_no, "pass": False,
                                   "output": "coder reply had no usable files"})
                    notes = ["Your last reply had no usable files. Reply with one block per file: ### FILE: path, "
                             "then the complete file in a ``` fence."] + carry  # keep what HR said
                    continue
                notes = _format_notes(reply) + self._write(reply.get("files"))
            self._ensure_packages()
            problems = import_problems(self._ws) if self._stdlib_only else []
            has_tests = any(_is_test_file(f) for f in self._ws.files())
            result = self._run(TEST_COMMAND)
            output = ((result.stdout or "") + (result.stderr or ""))[-2000:]
            summary = test_summary(result.stdout)
            real = (summary or {}).get("run", 0) - (summary or {}).get("skipped", 0)
            ran_tests = real >= 1
            imports_app = app_is_tested(self._ws)
            clean = (result.exit_code == 0 and has_tests and real >= 2 and imports_app and not result.timed_out
                     and summary is not None and not summary.get("failures") and not summary.get("errors"))
            passed = clean and not problems
            checks.append({"check": "tests", "round": round_no, "pass": passed, "output": output[-300:]})
            if passed:
                last_failing, carry, diagnosis, diagnosed_for = None, [], "", None  # a pass ends any stuck set
                verdict = self._hr_review(spec, plan) if self._hr is not None and hr_asks < MAX_HR_ASKS else None
                if verdict is None or verdict[0]:
                    break
                hr_asks += 1
                if hr_asks >= MAX_HR_ASKS or round_no == self._max_rounds - 1:
                    hr_question = f"F2 HR not satisfied: {verdict[1][:200]}"
                    break
                carry = ["Floor 2 HR reviewed your code and asked for changes:\n" + _capped("f2.hr", verdict[1], 800)]
                notes += carry  # kept through a garbled reply
                continue
            if not has_tests:
                notes.append("There are no unittest files yet: add test_*.py with real tests.")
            elif not ran_tests:
                notes.append("unittest found 0 tests: name test files test_*.py, put test classes in "
                             "unittest.TestCase subclasses, and name methods test_*.")
            elif real < 2:
                notes.append(f"unittest ran only {real} test: write at least 2 real tests of the app's behaviour.")
            if has_tests and not imports_app:
                notes.append("Your tests import nothing from the app: import the app's own functions or handler "
                             "(e.g. from app import ...) and test what they do.")
            found = failures(result.stderr or "")
            failing = sorted({f"{f['id']}:{f['test']}" for f in found})
            stuck = bool(failing) and failing == last_failing
            if stuck and failing != diagnosed_for and self._hr is not None and diagnoses < MAX_DIAGNOSES:
                diagnoses += 1  # one F2 HR diagnosis per stuck set, at most 2 per build
                diagnosis, diagnosed_for = self._diagnose_tests(_failure_rows(found)), failing
            shown = diagnosis if stuck and failing == diagnosed_for else ""  # never another set's diagnosis
            tests_ok = clean  # "only thing left" only when the whole test bar is met
            carry = [] if tests_ok and problems else [
                _failure_note(found, STUCK_NOTE.format(names=", ".join(sorted({f["test"] for f in found})))
                              if stuck else "", shown) if found  # last: trimming drops the oldest first
                else "Test output:\n" + _capped("sandbox", (output or "(no output)")[-1200:], 1300, code=True)]
            if problems:  # one note with the failures (trimming keeps or drops them together), kept last
                note = _problem_note(problems, self._ws, tests_ok)
                carry = [carry[0] + "\n" + note] if carry else [note]
            notes += carry
            last_failing = failing
        summary = (f"Entry: {plan['entry']}\nFiles: {', '.join(self._ws.files()) or '(none)'}\n"
                   f"Tests: {'PASS' if passed else 'FAIL'}\n{output[-800:]}")
        questions = [] if passed else [f"tests still failing after {len(checks)} round(s)"]
        questions += [hr_question] if hr_question else []
        return WorkPackage("f2", summary, self._ws.files(), [], checks, questions)

    def _diagnose_tests(self, report: str) -> str:
        """Floor 2 HR, only when the coder is stuck: plain words on why the same tests keep failing. Advisory."""
        try:
            out = self._ask(self._hr, TEST_DIAGNOSE_PROMPT.format(report=untrusted_code("sandbox", report)))
        except ADVISORY_ERRORS:
            return ""
        return " ".join(str(out.get("diagnosis") or "").split())[:400]

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
        notes, same, changed = [], [], False
        written = 0
        for f in (files if isinstance(files, list) else [])[:MAX_FILES_PER_ROUND + 5]:
            if not isinstance(f, dict):
                continue
            if f.get("delete") is not True:
                if written >= MAX_FILES_PER_ROUND:  # deletes don't use up the cap; writes beyond it are dropped
                    changed = True  # it sent more than was written: never tell it "unchanged"
                    notes.append(f"File {str(f.get('path'))[:100]!r} not written: at most {MAX_FILES_PER_ROUND} "
                                 "files per reply")
                    continue
                written += 1
            try:
                if f.get("delete") is True:
                    before_files = set(self._ws.files())
                    self._ws.delete(str(f.get("path", "")))
                    changed = changed or set(self._ws.files()) != before_files  # a missing file: no change
                elif not isinstance(f.get("content"), str):
                    notes.append(f"File rejected: {str(f.get('path'))[:100]!r} has no content")
                else:
                    path, content = str(f.get("path", "")), str(f.get("content", ""))
                    lines: list[int] = []
                    added: list[str] = []
                    if path.endswith(".py"):
                        content, lines = repair_strings(content)
                        content, added = repair_imports(content)
                    try:
                        before = self._ws.read(path)
                    except (WorkspaceError, OSError):
                        before = None
                    self._ws.write(path, content)
                    if before == content.replace("\r\n", "\n").replace("\r", "\n"):  # read() gives \n only
                        same.append(path)
                    else:
                        changed = True
                    if lines:
                        notes.append(f"Auto-repaired {path} line(s) {', '.join(map(str, lines))} of what you sent: a line "
                                     "break inside a one-line string was joined as \\n. Keep one-line strings on one line.")
                    if added:
                        notes.append(f"Auto-repaired: added the missing import {', '.join(added)} to {path}.")
            except WorkspaceError as e:
                notes.append(f"File rejected: {e}")
        if same and not changed:  # run 8: the 7B copied the files it was shown, 16 rounds in a row
            notes.append(UNCHANGED_NOTE.format(names=", ".join(same)[:200]))
        return notes
