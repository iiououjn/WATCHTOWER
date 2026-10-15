"""Sign-off evidence and web-lookup queries, built from the checks' own results (moved out of tower.py, 6v)."""
import re
from http import HTTPStatus

from watchtower.floors.f5_oversight.oversight import is_failing as _failing


def _reference(glass: str, text: str) -> list[str]:
    return [f"Reference for this failure (from the web through Glass {glass}; may be wrong):\n{text}"] if text else []


def _status_query(check: dict) -> str:
    """F4 lookup: the HTTP status of the first failing QA check, as words (never the app's output)."""
    for r in check.get("results") or []:
        status = r.get("status")
        if not r.get("pass") and isinstance(status, int) and 100 <= status <= 599:
            try:
                return f"HTTP {status} {HTTPStatus(status).phrase} python http.server"
            except ValueError:
                return f"HTTP {status} python http.server"
    return ""


def _finding_query(check: dict, fail_on) -> str:
    """F5 lookup: the Bandit test id of the first failing finding (secrets need no lookup)."""
    for f in check.get("findings") or []:
        if f.get("tool") == "bandit" and _failing(f, fail_on) and re.fullmatch(r"B\d{3}", str(f.get("id"))):
            return f"bandit {f['id']} python"
    return ""


def _evidence(checks: list[dict], fail_on=("HIGH", "MEDIUM")) -> str:
    """Sign-off evidence built from the checks' own results — never from text the app could print."""
    last = {}
    for c in checks:
        last[c.get("check")] = c
    tests, http, qa, sec = last.get("tests", {}), last.get("http", {}), last.get("qa", {}), last.get("security", {})
    probe = last.get("routes", {}).get("results") or []
    results = qa.get("results") or []
    findings = sec.get("findings") or []
    serious = sum(_failing(f, fail_on) for f in findings)
    unknown = sum(f.get("severity") == "UNKNOWN" for f in findings)
    if unknown:
        scan = f"INCOMPLETE — a scanner did not run (see watchtower doctor); {serious} serious found"
    else:
        scan = f"{'pass' if sec.get('pass') else 'FAIL'} ({serious} serious, {len(findings) - serious} minor)"
    qa_line = (f"{sum(r.get('pass') is True for r in results)}/{len(results)} checks passed" if results
               else "no QA checks ran")
    if qa.get("decide") and len(results) > qa["decide"]:  # 6u: the tower's checks decide, the rest are advisory
        d, a = results[:qa["decide"]], results[qa["decide"]:]
        qa_line = (f"{'pass' if qa.get('pass') else 'FAIL'} (tower checks {sum(r.get('pass') is True for r in d)}/"
                   f"{len(d)}; advisory {sum(r.get('pass') is True for r in a)}/{len(a)} passed)")
    return "\n".join([
        f"- coder unit tests (advisory): {'pass' if tests.get('pass') else 'FAIL'}",
        f"- app answered HTTP {http.get('status')}",
        *([f"- full app: {sum(isinstance(r.get('status'), int) and r['status'] < 500 and r['status'] != 404 for r in probe)}"
           f"/{len(probe)} contract routes answered"] if probe else []),
        f"- QA: {qa_line}",
        f"- security scan: {scan}",
    ])


def model_objection(verdict, package, f3, f4, sec, attempt: int = 1) -> list[str]:
    """6v (run 22): the small model gate's reasons when it is the ONLY thing against the app — the package
    validates, F3 started it, the tower's own F4 checks decided and passed, and the F5 scan passed. The
    coder cannot fix a phantom, so these go to the owner — after one send-back (attempt 0), so a real spec
    gap the tower checks do not cover still reaches the coder first. [] in every other case."""
    if attempt < 1 or verdict.passed or package.validate() or None in (f3, f4, sec):
        return []
    qa = f4.checks_run[-1]
    if not (f3.checks_run[-1]["pass"] and qa["pass"] and qa.get("decide") and sec.checks_run[-1]["pass"]):
        return []
    return [" ".join(str(r).split())[:200] for r in verdict.reasons][:5] or ["no reason given"]  # one line each


def objection_note(reasons: list[str], ceo_note: str) -> str:
    return ("F5 gate (small model) objected though every tower check passed: " + "; ".join(reasons)
            + "; the owner decides" + (f". CEO: {ceo_note}" if ceo_note else ""))[:900]
