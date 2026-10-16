from __future__ import annotations

import json
from dataclasses import replace
from pathlib import PurePosixPath
from typing import Callable, Sequence

from watchtower.engine.advisory import ADVISORY_ERRORS
from watchtower.engine.model_socket import BadModelOutput
from watchtower.engine.sandbox import SandboxResult
from watchtower.engine.workspace import Workspace, WorkspaceError
from watchtower.floors.f2_dev.app_tests import app_is_tested, is_test_file
from watchtower.floors.f2_dev.feedback import _capped, _failure_note, _failure_rows, _problem_note, failures, stuck_note
from watchtower.floors.f2_dev.lint import handler_state_problems, idiom_notes
from watchtower.floors.f2_dev.planner import PLAN_PROMPT, parse_plan, units
from watchtower.floors.f2_dev.prompt_fit import FILES_MIN, PROMPT_CHARS, RESEARCH_CHARS, SPEC_CHARS, fit, plan_text
from watchtower.floors.f2_dev.prompt_fit import room_left, spec_text as _spec_text
from watchtower.floors.f2_dev.repair import repair_names
from watchtower.floors.f2_dev.skeleton import (CODER_PROMPT, ONLY_NOTE, SAFE, SAFE_TESTS, STORE, STORE_NOTE,
                                               STORE_TESTS, store_problems)
from watchtower.floors.f2_dev.stdlib_check import import_problems
from watchtower.floors.f2_dev.unittest_runner import TEST_COMMAND, test_summary
from watchtower.floors.f2_dev.writer import write_files
from watchtower.floors.framework import WorkPackage, untrusted, untrusted_code
from watchtower.roles import Role

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
HR_PROMPT = (
    "Spec:\n{spec}\n\nPlan and routes contract:\n{plan}\n\nCode:\n{code}\n\nThe unit tests pass. Does the code "
    "meet the spec and follow the plan and routes contract? Reply as JSON: "
    '{{"pass": boolean, "reason": string}}'
)
MAX_HR_ASKS = 2
MAX_DIAGNOSES = 2
FEEDBACK_ITEM = 600  # each part capped, so the coder prompt stays inside num_ctx
FEEDBACK_TOTAL = 2000
QA_CHARS = 1500


def _compact_checks(checks: Sequence[dict]) -> str:
    """QA checks for the coder: compact JSON, long values trimmed, total capped."""
    trimmed = [{**c, "form": {k: str(v)[:60] for k, v in c.get("form", {}).items()},
                "expect_text": str(c.get("expect_text", ""))[:80]} for c in checks]
    text = json.dumps(trimmed)
    return text if len(text) <= QA_CHARS else text[:QA_CHARS] + " ...(more checks)"


ESCAPE_NOTE = ('Checks with "expect_escaped": true post text containing <&> (written &lt;&> above). The page '
               "must show it escaped exactly once: html.escape(text) when you build the HTML, not on save.\n")


def _qa_block(head: str, checks: Sequence[dict], store_only: bool = False, shown: bool = True) -> str:
    """The QA checks for a coder prompt; notes sit outside the untrusted block (6z). `store_only`: 7a-7c.
    `shown=False` (8c): the prompt is full; the notes stay, the checks go."""
    note = (ONLY_NOTE if store_only else "") + (
        (STORE_NOTE if store_only else ESCAPE_NOTE) if any(c.get("expect_escaped") for c in checks) else "")
    if not checks:
        return note
    return (head + untrusted("f4", _compact_checks(checks)) if shown else "(QA's HTTP checks not shown)") + "\n" + note


TEST_DIAGNOSE_PROMPT = (
    "The coder's unit tests keep failing the same way. unittest's report:\n{report}\n\nIn one or two plain "
    "sentences: is the test wrong or the code, and what exactly should change? Reply as JSON: "
    '{{"diagnosis": string}}'
)


def _format_notes(reply: dict) -> list[str]:
    """What the file-block reader could not use (a block left open, cut off …): the coder must hear it."""
    return [str(n)[:200] for n in (reply.get("notes") if isinstance(reply.get("notes"), list) else [])][:3]


def _feedback_notes(feedback: Sequence[str]) -> list[str]:
    """The reviewer's feedback for the coder: each item capped, the first ones kept up to the total."""
    kept, used = [], 0
    for f in feedback:
        item = str(f)[:FEEDBACK_ITEM]
        if used + len(item) > FEEDBACK_TOTAL:
            break
        kept.append(item)
        used += len(item)
    return [f"Reviewer feedback to address:\n{_capped('gate', f, 800)}" for f in kept]


def _code_parts(spec: dict, plan: dict, qa: str, qa_short: str, notes: list[str]) -> tuple[dict, int, list[str]]:
    """The fix prompt's parts within budget: the oldest notes go first (the newest, most important one is kept),
    then every part is capped (8c, C-M5). Returns the parts, the room left for files, and the notes kept."""
    parts = dict(spec=_spec_text(spec), plan=plan_text(plan), qa=qa, files="",
                 feedback=("\n" + "\n".join(notes)) if notes else "")
    while len(notes) > 1 and len(CODE_PROMPT.format(**parts)) > PROMPT_CHARS - FILES_MIN:
        notes = notes[1:]
        parts["feedback"] = ("\n" + "\n".join(notes)) if notes else ""
    parts = fit(CODE_PROMPT, parts, [("qa", qa_short), ("plan", plan_text(plan, False)),
                                     ("spec", _spec_text(spec, SPEC_CHARS))], FILES_MIN)
    room = room_left(CODE_PROMPT, parts)
    del parts["files"]
    return parts, room, notes


def _test_bar_notes(owned: bool, has_tests: bool, real: int, imports_app: bool) -> list[str]:
    """What the coder's tests still lack: files, discovered tests, two real tests, an import of the app."""
    tests = STORE_TESTS if owned else "test_*.py"  # 8c (C-H2): only test_store.py is accepted
    notes = []
    if not has_tests:
        notes.append(f"There are no unittest files yet: add {tests} with real tests.")
    elif real < 1:
        notes.append(f"unittest found 0 tests: name test files {tests}, put test classes in "
                     "unittest.TestCase subclasses, and name methods test_*.")
    elif real < 2:
        notes.append(f"unittest ran only {real} test: write at least 2 real tests of the app's behaviour.")
    if has_tests and not imports_app:  # app.py is the tower's server: importing it is rejected
        notes.append(f"Your tests import nothing from the app: in {STORE_TESTS}, `import store` and test "
                     "store.add(entry) and store.items()." if owned else "Your tests import nothing "
                     "from the app: import the app's own functions or handler (e.g. from app import ...) "
                     "and test what they do.")
    return notes


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
        self.owned: set[str] = set()  # 7a: paths the tower wrote (the web server); the coder never changes them

    @property
    def _writer(self) -> Role:
        """The coder; under the skeleton with a store-only system prompt (8c review r3: the web-app one asked for
        app.py, test_*.py and add_todo, which _write and _contract reject). Same id: memos and the scheduler."""
        return replace(self._coder, prompt=CODER_PROMPT) if self.owned else self._coder

    def plan(self, spec: dict, research: str, feedback: Sequence[str], lessons: str = "", reference: str = "") -> dict:
        note = ("\nThe reviewer rejected the last design:\n" + "\n".join(_capped("gate", str(f), FEEDBACK_ITEM)
                                                                    for f in feedback[:5])) if feedback else ""
        parts = dict(spec=_spec_text(spec), feedback=note,  # 8c (C-M5): every part capped after escaping
                     research=_capped("f1", research, RESEARCH_CHARS) if research else "(none)",
                     lessons=("\nLessons from past jobs:\n" + _capped("retro", lessons, 800) + "\n") if lessons else "",
                     reference=("\nReference docs (from the web through Glass 2; may be wrong):\n" + reference + "\n")
                     if reference else "")
        return parse_plan(self._ask(self._architect, PLAN_PROMPT.format(**fit(PLAN_PROMPT, parts, [
            ("reference", ""), ("lessons", ""), ("research", _capped("f1", research, 500) if research else "(none)"),
            ("spec", _spec_text(spec, SPEC_CHARS))]))))

    def write_units(self, spec: dict, plan: dict, qa_checks: Sequence[dict] = (),
                    on_unit: Callable[[int, int, list[str]], None] | None = None) -> list[str]:
        """F2 workers: one coder call per unit that still has missing files, back to back on the coder model.
        A worker writes only its own unit's files; a garbled reply costs that unit (the fix loop catches up)."""
        present = {p.lower() for p in self._ws.files()}  # macOS disks are case-blind: App.py is app.py
        todo = [[f for f in u if f["path"].lower() not in present] for u in units(plan, self.owned)]
        todo = [u for u in todo if u]  # a worker writes only files that do not exist yet: never a fixed one
        qa = _qa_block("Floor 4 QA will run these HTTP checks against the app:\n", qa_checks, bool(self.owned))
        qa_short = _qa_block("", qa_checks, bool(self.owned), shown=False)
        notes: list[str] = []
        stray: list[str] = []
        for i, unit in enumerate(todo, start=1):
            paths = [f["path"] for f in unit]
            listed = untrusted("f2.architect", "\n".join(f"- {f['path']}: {f['purpose']}" for f in unit))
            parts = fit(UNIT_PROMPT, dict(spec=_spec_text(spec), plan=plan_text(plan), qa=qa, i=i, n=len(todo),
                                          files="", unit=listed),
                        [("qa", qa_short), ("plan", plan_text(plan, False)), ("spec", _spec_text(spec, SPEC_CHARS))],
                        FILES_MIN)
            room = room_left(UNIT_PROMPT, parts)
            del parts["files"]
            try:
                reply = self._ask(self._writer, UNIT_PROMPT.format(
                    files=untrusted_code("workspace", self._ws.snapshot(room) or "(none yet)"), **parts))
            except BadModelOutput:  # low memory or a dead model pauses the job, as for any coder call
                notes.append(f"coder {i} gave no usable reply for {', '.join(paths)}; write those files")
                continue
            files = reply.get("files") if isinstance(reply.get("files"), list) else []
            mine = [f for f in files if isinstance(f, dict) and f.get("path") in paths and f.get("delete") is not True]
            stray += [str(f.get("path"))[:100] for f in files if isinstance(f, dict) and f not in mine]
            before = set(self._ws.files())
            notes += _format_notes(reply) + self._write(mine, plan["entry"])
            if on_unit is not None and set(self._ws.files()) - before:
                on_unit(i, len(todo), paths)
        written = {p.lower() for p in self._ws.files()}  # a stray file another unit then wrote is no news
        return notes + [f"File rejected: {p!r} was outside your unit" for p in dict.fromkeys(stray)
                        if p.lower() not in written]

    def build(self, spec: dict, plan: dict, feedback: Sequence[str], qa_checks: Sequence[dict] = (),
              test_first: bool = False) -> WorkPackage:
        notes = _feedback_notes(feedback)
        qa = _qa_block("Floor 4 QA will run these HTTP checks against your running app; make them pass:\n", qa_checks,
                       bool(self.owned))
        qa_short = _qa_block("", qa_checks, bool(self.owned), shown=False)
        checks, output, passed, hr_asks, hr_question, hr_pending = [], "", False, 0, None, ""
        last_failing, diagnoses, diagnosis, diagnosed_for, carry = None, 0, "", None, []  # stuck = same set twice
        for round_no in range(self._max_rounds):
            parts, room, notes = _code_parts(spec, plan, qa, qa_short, notes)
            if test_first and round_no == 0:  # the unit workers just wrote every file: test before rewriting
                notes = []
            else:
                try:
                    reply = self._ask(self._writer, CODE_PROMPT.format(
                        files=untrusted_code("workspace", self._ws.snapshot(room)), **parts))
                except BadModelOutput:  # a garbled reply costs this round, not the whole job
                    problems = self._problems()  # files on disk still judged; unchanged, so the last test result
                    clean = bool(checks and checks[-1].get("clean"))  # holds (8c, C-M6: PASS beside pass False)
                    passed = clean and not problems
                    checks.append({"check": "tests", "round": round_no, "pass": passed, "clean": clean,
                                   "output": "coder reply had no usable files",
                                   "problems": [str(p)[:200] for p in problems]})
                    notes = ["Your last reply had no usable files. Reply with one block per file: ### FILE: path, "
                             "then the complete file in a ``` fence."] + carry  # keep what HR said
                    continue
                notes = _format_notes(reply) + self._write(reply.get("files"), plan["entry"])
            self._ensure_packages()
            notes += self._link_entry(plan["entry"])
            problems = self._problems()
            has_tests = any(is_test_file(f) for f in self._ws.files())
            result = self._run(TEST_COMMAND)
            output = ((result.stdout or "") + (result.stderr or ""))[-2000:]
            summary = test_summary(result.stdout)
            real = (summary or {}).get("run", 0) - (summary or {}).get("skipped", 0)
            imports_app = app_is_tested(self._ws)
            clean = (result.exit_code == 0 and has_tests and real >= 2 and imports_app and not result.timed_out
                     and summary is not None and not summary.get("failures") and not summary.get("errors"))
            passed = clean and not problems
            checks.append({"check": "tests", "round": round_no, "pass": passed, "output": output[-300:],
                           "problems": [str(p)[:200] for p in problems], "clean": clean})
            if passed:
                last_failing, carry, diagnosis, diagnosed_for = None, [], "", None  # a pass ends any stuck set
                verdict = self._hr_review(spec, plan) if self._hr is not None and hr_asks < MAX_HR_ASKS else None
                if verdict is None or verdict[0]:
                    hr_pending = ""
                    break
                hr_asks += 1
                if hr_asks >= MAX_HR_ASKS or round_no == self._max_rounds - 1:
                    hr_question = f"F2 HR not satisfied: {verdict[1][:200]}"
                    break
                hr_pending = verdict[1]  # still open if the rounds run out first (8c, C-M6)
                carry = ["Floor 2 HR reviewed your code and asked for changes:\n" + _capped("f2.hr", verdict[1], 800)]
                notes += carry  # kept through a garbled reply
                continue
            notes += _test_bar_notes(bool(self.owned), has_tests, real, imports_app)
            found = failures(result.stderr or "")
            failing = sorted({f"{f['id']}:{f['test']}" for f in found})
            stuck = bool(failing) and failing == last_failing
            if stuck and failing != diagnosed_for and self._hr is not None and diagnoses < MAX_DIAGNOSES:
                diagnoses += 1  # one F2 HR diagnosis per stuck set, at most 2 per build
                diagnosis, diagnosed_for = self._diagnose_tests(_failure_rows(found)), failing
            shown = diagnosis if stuck and failing == diagnosed_for else ""  # never another set's diagnosis
            carry = self._carry(found, stuck, shown, clean, problems, output)
            notes += ([] if clean else idiom_notes(self._ws)) + carry  # failures last: kept on trim
            last_failing = failing
        summary = (f"Entry: {plan['entry']}\nFiles: {', '.join(self._ws.files()) or '(none)'}\n"
                   f"Tests: {'PASS' if passed else 'FAIL'}\n{output[-800:]}")
        questions = [] if passed else [f"tests still failing after {len(checks)} round(s)"]
        hr_question = hr_question or (f"F2 HR not satisfied: {hr_pending[:200]}" if hr_pending else None)
        questions += [hr_question] if hr_question else []
        return WorkPackage("f2", summary, self._ws.files(), [], checks, questions)

    def _carry(self, found: list[dict], stuck: bool, shown: str, clean: bool, problems: list[str],
               output: str) -> list[str]:
        """The round's failures, kept last in the notes so trimming drops the oldest notes first. With the whole
        test bar met ("only thing left") the static problems alone; one note, kept or dropped together."""
        carry = [] if clean and problems else [
            _failure_note(found, stuck_note(f["test"] for f in found) if stuck else "", shown) if found
            else "Test output:\n" + _capped("sandbox", (output or "(no output)")[-1200:], 1300, code=True)]
        if problems:
            note = _problem_note(problems, self._ws, clean)
            carry = [carry[0] + "\n" + note] if carry else [note]
        return carry

    def _problems(self) -> list[str]:
        """The tower's own static checks on the files on disk: they block the F2 handoff (phase 6s)."""
        found = ((store_problems(self._ws) if self.owned else []) + handler_state_problems(self._ws)  # 7c: first
                 + (import_problems(self._ws) if self._stdlib_only else []))
        return [f"write {STORE} with add(entry) and items(): the tower's web server imports it"
                if self.owned and p.endswith(f"imports {STORE[:-3]} (not in the Python standard library)") else p
                for p in found]

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
            parts = fit(HR_PROMPT, dict(spec=_spec_text(spec), plan=plan_text(plan), code=""),
                        [("plan", plan_text(plan, False)), ("spec", _spec_text(spec, SPEC_CHARS))], FILES_MIN)
            room = room_left(HR_PROMPT, parts, 4500)
            out = self._ask(self._hr, HR_PROMPT.format(**{**parts, "code": untrusted_code("workspace",
                                                                                          self._ws.snapshot(room))}))
        except ADVISORY_ERRORS:
            return None
        if not isinstance(out.get("pass"), bool):  # no clear verdict from a sloppy model: skip, never veto
            return None
        return out["pass"], str(out.get("reason") or "no reason given").strip()[:300]

    def _link_entry(self, entry: str) -> list[str]:
        """Run 11: the entry called its own module's functions without importing them; the unit tests import
        that module directly, so only QA met the NameError. Static: link names exactly one sibling defines."""
        if "/" in entry or not entry.endswith(".py"):
            return []
        siblings = {}
        for f in self._ws.files():
            if "/" not in f and f.endswith(".py") and f != entry:
                try:
                    siblings[f[:-3]] = self._ws.read(f)
                except (WorkspaceError, OSError):
                    continue
        try:
            source = self._ws.read(entry)
            text, added = repair_names(source, entry[:-3], siblings)
            if added:
                self._ws.write(entry, text)
        except (WorkspaceError, OSError):
            return []
        return [f"Auto-repaired: added `{line}` to {entry}; it used those names without importing them."
                for line in added]

    def _may_import(self, path: str) -> frozenset[str] | None:
        """What auto-repair may add (8c, C-H2): under the skeleton only what store_problems accepts; store.py never
        gets html (STORE_NOTE: the server escapes)."""
        if not self.owned:
            return None
        return frozenset(SAFE - {"html"} if path == STORE else SAFE_TESTS)

    def _ensure_packages(self) -> None:
        """unittest discovery only enters folders that are packages: add empty __init__.py where missing."""
        folders = {PurePosixPath(f).parent for f in self._ws.files() if f.endswith(".py")}
        for folder in sorted(folders):
            if str(folder) != "." and f"{folder}/__init__.py" not in self._ws.files():
                try:
                    self._ws.write(f"{folder}/__init__.py", "")
                except WorkspaceError:
                    pass

    def _write(self, files, entry: str = "") -> list[str]:
        return write_files(self._ws, files, entry, self.owned, self._may_import)
