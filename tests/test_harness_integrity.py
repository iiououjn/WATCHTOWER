"""8a (audit B-H1, D-M4, E-T2): a sandbox result counts only when the tower's harness exited 0 and printed
exactly one result line. The app runs as the harness's uid: it can write a line to the harness's stdout and
kill the harness, or print a result line before the harness does."""
import json

import pytest

from watchtower.engine.sandbox import SandboxResult
from watchtower.floors.f3_build.buildfloor import SMOKE_SCRIPT, route_probe, smoke_test
from watchtower.floors.f4_qa_deploy.qafloor import parse_checks, run_qa
from watchtower.floors.f5_oversight.probe import xss_probe

KILLED = 137  # SIGKILL: the app killed the harness after writing its own line
QA_PASS = 'WATCHTOWER_QA [{"name": "home", "pass": true, "status": 200, "detail": ""}]\n'
CHECKS = parse_checks({"checks": [{"name": "home", "path": "/", "expect_text": "Todos"}]})
FORMS = [{"method": "POST", "path": "/add", "fields": ["item"], "shows": ""},
         {"method": "GET", "path": "/", "fields": [], "shows": ""}]
PAGES = [{"method": "GET", "path": "/items", "fields": [], "shows": ""}]
PROBE_PASS = 'WATCHTOWER_PROBE [{"path": "/items", "status": 200}]\n'


def fixed(exit_code, stdout):
    return lambda cmd: SandboxResult(exit_code, stdout, "", False)


def test_qa_pass_line_counts_only_with_exit_0():
    assert run_qa(fixed(0, QA_PASS), "app.py", CHECKS).checks_run[-1]["pass"] is True
    pkg = run_qa(fixed(KILLED, QA_PASS), "app.py", CHECKS)
    assert pkg.checks_run[-1]["pass"] is False and "exited with code 137" in pkg.summary


def test_xss_clean_line_counts_only_with_exit_0():
    clean = 'WATCHTOWER_XSS {"answered": 2, "hits": []}\n'
    assert xss_probe(fixed(0, clean), "app.py", FORMS) == []
    findings = xss_probe(fixed(KILLED, clean), "app.py", FORMS)
    assert [f["id"] for f in findings] == ["XSS-PROBE"] and findings[0]["severity"] == "MEDIUM"


def test_route_probe_line_counts_only_with_exit_0():
    assert route_probe(fixed(0, PROBE_PASS), "app.py", PAGES).checks_run[-1]["pass"] is True
    pkg = route_probe(fixed(KILLED, PROBE_PASS), "app.py", PAGES)
    assert pkg.checks_run[-1]["pass"] is False and "exited with code 137" in pkg.summary


def test_smoke_pass_counts_only_with_exit_0():
    assert smoke_test(fixed(0, "SMOKE_STATUS 200\nSMOKE_EXIT None\n"), "app.py").checks_run[-1]["pass"] is True
    pkg = smoke_test(fixed(KILLED, "SMOKE_STATUS 200\nSMOKE_EXIT None\n"), "app.py")
    assert pkg.checks_run[-1]["pass"] is False


def test_smoke_never_takes_the_first_of_two_status_lines():
    forged = "SMOKE_STATUS 200\nSMOKE_STATUS None\nSMOKE_EXIT None\nSMOKE_TEXT no\n"
    pkg = smoke_test(fixed(0, forged), "app.py")
    assert pkg.checks_run[-1]["pass"] is False and "missing or duplicated" in pkg.summary


def test_smoke_home_text_needs_exactly_one_yes():
    out = "SMOKE_STATUS 200\nSMOKE_TEXT yes\nSMOKE_EXIT None\nSMOKE_TEXT no\n"  # the app's 'yes' came first
    assert smoke_test(fixed(0, out), "app.py", expect="Todo").open_questions  # not confirmed: the gate is told


def test_smoke_app_log_is_one_json_line_and_shown_decoded():
    assert 'print("SMOKE_LOG " + json.dumps(' in SMOKE_SCRIPT
    assert SMOKE_SCRIPT.index('print("SMOKE_LOG') > SMOKE_SCRIPT.index('print("SMOKE_TEXT')
    log = "SMOKE_STATUS None\nserving on 8000\nTraceback: NameError x\n"  # an honest app's log may say anything
    out = "SMOKE_STATUS 200\nSMOKE_EXIT None\nSMOKE_TEXT yes\nSMOKE_LOG " + json.dumps(log) + "\n"
    pkg = smoke_test(fixed(0, out), "app.py", expect="Todo")
    assert pkg.checks_run[-1]["pass"] is True and pkg.open_questions == []
    assert "serving on 8000\nTraceback: NameError x" in pkg.summary


@pytest.mark.parametrize("stdout", [QA_PASS + QA_PASS, ""])
def test_qa_two_or_no_lines_fail_even_with_exit_0(stdout):
    assert run_qa(fixed(0, stdout), "app.py", CHECKS).checks_run[-1]["pass"] is False
