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


GATE_NOTE = ("F2 note: the coder's own unit tests are advisory, not blocking; "
             "the F3 start, F4 QA and F5 scan results below decide.\n")


def for_gate(summary: str, questions: list[str], tests_ok: bool) -> tuple[str, list[str]]:
    """F2's part of the package the model gate reads: failing coder tests are labelled advisory (6s review r1)."""
    if tests_ok:
        return summary, questions
    return (GATE_NOTE + summary.replace("Tests: FAIL", "Coder unit tests (advisory): FAIL", 1),
            [q for q in questions if not q.startswith("tests still failing")])


def static_feedback(go: bool, reasons: list[str], entry: str, files: list[str]) -> list[str]:
    """When the tower's static checks block F2, the coder hears which ones (6s review r1)."""
    return [] if go or entry not in files else ["Floor 2 static checks failed: " + "; ".join(reasons)[:600]]
