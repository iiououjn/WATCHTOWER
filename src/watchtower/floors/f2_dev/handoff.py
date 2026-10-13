"""F2 → F3 handoff: the tower's own checks decide, not the coder's tests (phase 6s, run 17)."""

ADVISORY = "coder's own unit tests fail (advisory: F3/F4 decide)"


def f2_handoff(checks_run: list[dict], entry: str, files: list[str]) -> tuple[bool, list[str]]:
    """Go to F3 when the planned entry file exists and the last F2 round has no tower problems
    (stdlib-only imports, handler-state lint). The coder's own failing tests are reported, never blocking."""
    if not checks_run:
        return False, ["no F2 test round ran"]
    if entry not in files:
        return False, [f"planned entry file {entry} missing"]
    last = checks_run[-1]
    problems = [str(p) for p in last.get("problems") or []]
    if problems:
        return False, problems
    return True, [] if last.get("pass") else [ADVISORY]


GATE_NOTE = ("the coder's own unit tests are advisory, not blocking: judge the app on the F3 start, "
             "F4 QA and F5 scan results")
STATIC = "Floor 2 static checks failed: "
ITEM = 600  # devfloor FEEDBACK_ITEM: one coder feedback item


def for_gate(summary: str, questions: list[str], tests_ok: bool) -> tuple[str, list[str], tuple[str, ...]]:
    """F2's part of the package the model gate reads, plus trusted tower notes for the gate's own prompt.
    The package summary is untrusted text, so the advisory note goes outside it (6s reviews r1, r2)."""
    if tests_ok:
        return summary, questions, ()
    return (summary.replace("Tests: FAIL", "Coder unit tests (advisory): FAIL", 1),
            [q for q in questions if not q.startswith("tests still failing")], (GATE_NOTE,))


def static_feedback(go: bool, reasons: list[str], entry: str, files: list[str]) -> list[str]:
    """What the coder hears when F2 blocks: the gate's verdict replaces earlier feedback (6s reviews r1, r2)."""
    if go:
        return []
    if entry not in files:
        return [f"the planned entry file {entry} does not exist; create it"]
    return [STATIC + "; ".join(reasons)[:ITEM - len(STATIC)]]


def board_line(checks_run: list[dict], attempt: int, go: bool, reasons: list[str]) -> str:
    """The board's F2 line: the coder's tests and the tower's blocking problems, told apart."""
    last = checks_run[-1] if checks_run else {}
    clean = last.get("clean", last.get("pass"))
    line = f"unit tests {'pass' if clean else 'still fail'} after {len(checks_run)} round(s) (attempt {attempt + 1})"
    return line if go else f"{line}; blocked: {'; '.join(reasons)[:200]}"
