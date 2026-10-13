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
