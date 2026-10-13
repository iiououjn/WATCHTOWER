from __future__ import annotations

import re
from pathlib import PurePosixPath

from watchtower.engine.workspace import Workspace, WorkspaceError
from watchtower.floors.framework import untrusted, untrusted_code

# What the coder hears after a failing round: unittest's own FAIL/ERROR blocks, compact and bounded.
_BLOCK = re.compile(r"^(FAIL|ERROR): (\w+) \(([^)\n]*)\)(?: \([^\n]*\))?\n(?:(?!-{20,}\n)[^\n]*\n)?-{20,}\n"
                    r"(.*?)(?=^={20,}$|^-{20,}$|\Z)", re.M | re.S)  # optional docstring line before the dashes
_EXC = re.compile(r"^[A-Za-z_][\w.]*(: |$)")  # an unindented 'Name: message' line ends a traceback
_FRAME = re.compile(r'^\s+File "([^"]+)", line (\d+), in (\S+)')
MAX_FAILURES, MAX_PARSED, NOTE_CHARS = 5, 20, 1000
NOTE_CAP = 2000  # any one note, after escaping: the newest note is never trimmed, so it must stay small


def _capped(source: str, text: str, cap: int = NOTE_CAP // 2, code: bool = False) -> str:
    """Wrap text as untrusted and keep the result within cap characters (escaping can quadruple a '<')."""
    wrap = untrusted_code if code else untrusted
    body = str(text)
    while body and len(wrap(source, body)) > cap:
        body = body[:int(len(body) * 0.8)]
    return wrap(source, body)


def failures(output: str) -> list[dict]:
    """unittest's own FAIL/ERROR report as a compact list. Only the FINAL traceback of a block counts (chained
    inner errors and loader frames are noise): its first exception line is the cause; assertion failures keep a
    few diff lines, errors keep where they were raised. Import errors first, then FAIL, then ERROR."""
    out = []
    for kind, test, where, body in _BLOCK.findall(output or ""):
        lines = body.rstrip().splitlines()
        start = max((i for i, ln in enumerate(lines) if ln.startswith("Traceback (most recent call last)")),
                    default=-1)
        tail = lines[start + 1:]
        at = next((i for i, ln in enumerate(tail) if _EXC.match(ln)), None)
        if at is None:
            at = max((i for i, ln in enumerate(tail) if ln.strip()), default=None)
        if at is None:
            continue
        frames = [i for i, ln in enumerate(tail[:at]) if _FRAME.match(ln)]
        where_raised = ""
        if frames:
            path, line_no, fn = _FRAME.match(tail[frames[-1]]).groups()
            source = tail[frames[-1] + 1].strip() if frames[-1] + 1 < at else ""
            where_raised = f"at {PurePosixPath(path).name} line {line_no} in {fn}: {source}"[:200]
        rest = tail[at + 1:]
        assertion = tail[at].startswith("AssertionError")
        minus = "".join(ln[2:] for ln in rest if ln.startswith("- "))
        plus = "".join(ln[2:] for ln in rest if ln.startswith("+ "))
        space_only = bool(minus or plus) and minus != plus and re.sub(r"\s", "", minus) == re.sub(r"\s", "", plus)
        out.append({"test": test, "id": where[:150], "kind": kind, "line": tail[at].strip()[:200],
                    "diff": ("\n".join(rest[:6])[:400] if assertion else where_raised), "whitespace": space_only})
    out.sort(key=lambda f: (0 if "_FailedTest" in f["id"] else 1 if f["kind"] == "FAIL" else 2))
    return out[:MAX_PARSED]


def _failure_rows(found: list[dict]) -> str:
    """The failures as text, bounded: at most 5 rows, which shrink (diffs first) instead of disappearing."""
    shown, more = found[:MAX_FAILURES], len(found) - MAX_FAILURES
    for diff_cap in (400, 150, 0):
        rows = "\n".join(f"- {f['test'][:60]} ({f['kind']}): {f['line'][:200]}"
                         + (f"\n{f['diff'][:diff_cap]}" if f["diff"] and diff_cap else "") for f in shown)
        rows += f"\n(+{more} more failing)" if more > 0 else ""
        if len(rows) <= NOTE_CHARS:
            return rows
    return rows[:NOTE_CHARS]


def _failure_note(found: list[dict], stuck: str = "", diagnosis: str = "") -> str:
    """One note (so prompt trimming keeps or drops it whole): the failures, whitespace hints, and — when the
    coder is stuck — the stuck note and Floor 2 HR's diagnosis."""
    hints = [f"{f['test'][:60]}: the two sides differ only in spaces or indentation — make them identical, or "
             "compare without exact whitespace" for f in found[:MAX_FAILURES] if f["whitespace"]][:2]
    # the coder's own test output: HTML kept readable (untrusted_code escapes only <untrusted tags), then bounded
    return ("Failing tests (unittest's own report):\n" + _capped("sandbox", _failure_rows(found), NOTE_CHARS + 100, code=True)
            + ("\n" + "\n".join(hints) if hints else "") + (f"\n{stuck[:250]}" if stuck else "")
            + ("\nFloor 2 HR diagnosis:\n" + _capped("f2.hr", diagnosis, 300) if diagnosis else ""))


_SYNTAX = re.compile(r"^(.+?) has a syntax error on line (\d+):")
LINE_CHARS = 160


def _problem_note(problems: list[str], ws: Workspace, tests_ok: bool) -> str:
    """Problems the test run cannot show (syntax errors in files the tests never import, banned imports),
    with the lines around a syntax error. When the tests already pass, say this is all that is left."""
    parts, shown = [], False
    ordered = sorted(problems, key=lambda p: not _SYNTAX.match(p))  # syntax errors first: they get the excerpt
    for p in ordered[:3]:
        parts.append(p[:200])
        match = None if shown else _SYNTAX.match(p)  # one excerpt: the snapshot shows the rest of the code
        try:
            lines = re.split(r"\r\n|\r|\n", ws.read(match.group(1))) if match else []  # Python's own line count
        except (WorkspaceError, OSError):
            lines = []
        if lines:
            shown, n = True, int(match.group(2))
            excerpt = "\n".join(f"{'>' if i + 1 == n else ' '}{i + 1:4}| {lines[i][:LINE_CHARS]}"  # error line marked
                                 for i in range(max(0, min(n, len(lines)) - 3), min(len(lines), n + 2)))
            parts.append(untrusted_code(match.group(1), excerpt))
    if len(problems) > 3:
        parts.append(f"(+{len(problems) - 3} more)")
    head = "Your unit tests pass; this is the only thing left to fix:" if tests_ok else "Also fix these problems:"
    return head + "\n" + "\n".join(parts)  # bounded by its parts (≤ 3 × 200 + one 5-line excerpt); never cut


UNCHANGED_NOTE = ("Your last reply sent {names} back unchanged, so nothing could get better. Read the failing "
                  "line named below and change that line in your reply.")
STUCK_NOTE = ("The same tests failed again after your last change: {names}. Before changing the app again, check "
              "each failing test itself: tests run in alphabetical order and share module-level state (reset it "
              "in setUp), and a test's own expected value can be wrong — fix the test when it is.")
