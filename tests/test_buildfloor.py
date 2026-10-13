from watchtower.floors.f3_build.buildfloor import SMOKE_SCRIPT, smoke_test
from watchtower.engine.sandbox import SandboxResult


def runner(result):
    calls = []

    def run(cmd):
        calls.append(cmd)
        return result

    return run, calls


def test_http_200_passes():
    run, calls = runner(SandboxResult(0, "SMOKE_STATUS 200\nserving\n", "", False))
    pkg = smoke_test(run, "app.py")
    assert calls == [["python", "-I", "-c", SMOKE_SCRIPT, "app.py"]]
    assert pkg.floor == "f3" and pkg.checks_run == [{"check": "http", "pass": True, "status": "200"}]
    assert pkg.validate() == []


def test_no_answer_fails_with_app_output():
    run, _ = runner(SandboxResult(0, "SMOKE_STATUS None\nTraceback: NameError\n", "", False))
    pkg = smoke_test(run, "app.py")
    assert not pkg.checks_run[0]["pass"] and "NameError" in pkg.summary
    assert pkg.validate()


def test_non_200_fails():
    run, _ = runner(SandboxResult(0, "SMOKE_STATUS 500\n", "", False))
    assert not smoke_test(run, "app.py").checks_run[0]["pass"]


def test_script_waits_then_kills_the_app():
    assert "PORT" in SMOKE_SCRIPT and "kill()" in SMOKE_SCRIPT and "127.0.0.1:8000" in SMOKE_SCRIPT


def test_expected_home_text_is_a_soft_check():
    run, calls = runner(SandboxResult(0, "SMOKE_STATUS 200\nSMOKE_TEXT no\n", "", False))
    pkg = smoke_test(run, "app.py", expect="Todo list")
    assert calls == [["python", "-I", "-c", SMOKE_SCRIPT, "app.py", "Todo list"]]
    assert pkg.checks_run[-1]["pass"] is True and any("Todo list" in q for q in pkg.open_questions)
    run, _ = runner(SandboxResult(0, "SMOKE_STATUS 200\nSMOKE_TEXT yes\n", "", False))
    assert smoke_test(run, "app.py", expect="Todo list").open_questions == []


import json  # noqa: E402
import subprocess  # noqa: E402
import sys  # noqa: E402

from watchtower.floors.f3_build.buildfloor import PROBE_SCRIPT, build_check, route_probe  # noqa: E402

ROUTES = [{"method": "GET", "path": "/", "fields": [], "shows": ""},
          {"method": "GET", "path": "/items", "fields": [], "shows": ""},
          {"method": "POST", "path": "/add", "fields": ["name"], "shows": ""},
          {"method": "GET", "path": "/about", "fields": [], "shows": ""}]


def probe_out(results, log="served"):
    return SandboxResult(0, "WATCHTOWER_PROBE " + json.dumps(results) + "\nWATCHTOWER_LOG " + json.dumps(log) + "\n",
                         "", False)


def test_probe_checks_every_get_route_except_home():
    run, calls = runner(probe_out([{"path": "/items", "status": 200}, {"path": "/about", "status": 302}]))
    pkg = route_probe(run, "app.py", ROUTES)
    assert json.loads(calls[0][5]) == ["/items", "/about"] and pkg.checks_run[-1]["pass"]


def test_probe_fails_on_500_404_or_no_answer_and_names_the_route():
    for bad in (500, 404, None):
        run, _ = runner(probe_out([{"path": "/items", "status": 200}, {"path": "/about", "status": bad}],
                                  log="Traceback: KeyError"))
        pkg = route_probe(run, "app.py", ROUTES)
        assert not pkg.checks_run[-1]["pass"] and "/about" in pkg.summary and "KeyError" in pkg.summary


def test_forged_or_missing_probe_result_fails():
    two = SandboxResult(0, 'WATCHTOWER_PROBE [{"path": "/items", "status": 200}, {"path": "/about", "status": 200}]\n'
                           'WATCHTOWER_PROBE []\n', "", False)
    for result in (two, SandboxResult(0, "", "", False)):
        run, _ = runner(result)
        assert not route_probe(run, "app.py", ROUTES).checks_run[-1]["pass"]


def test_hostile_paths_are_never_probed():
    hostile = [{"method": "GET", "path": p, "fields": [], "shows": ""}
               for p in ("//evil.com", "/../etc", "/a b", "/" + "x" * 200, "http://x")]
    run, calls = runner(probe_out([]))
    pkg = route_probe(run, "app.py", hostile)
    assert calls == [] and pkg.checks_run[-1]["pass"]


def test_failed_mvp_skips_the_full_app_probe():
    run, calls = runner(SandboxResult(0, "SMOKE_STATUS None\nTraceback\n", "", False))
    pkg = build_check(run, "app.py", "", ROUTES)
    assert len(calls) == 1 and not pkg.checks_run[-1]["pass"]


def test_probe_script_against_a_real_tiny_app(tmp_path):
    (tmp_path / "app.py").write_text(
        "import os\nfrom http.server import BaseHTTPRequestHandler, HTTPServer\n"
        "class H(BaseHTTPRequestHandler):\n"
        "    def do_GET(self):\n"
        "        code = {'/': 200, '/items': 200, '/boom': 500}.get(self.path, 404)\n"
        "        self.send_response(code); self.end_headers(); self.wfile.write(b'ok')\n"
        "    def log_message(self, *a):\n        print('WATCHTOWER_PROBE [forged]')\n"
        "HTTPServer(('127.0.0.1', int(os.environ['PORT'])), H).serve_forever()\n")
    out = subprocess.run([sys.executable, "-c", PROBE_SCRIPT, "app.py", json.dumps(["/items", "/boom", "/nope"])],
                         cwd=tmp_path, capture_output=True, text=True, timeout=30,
                         env={"WT_PORT": "18765", "PATH": "/usr/bin:/bin"})
    pkg = route_probe(lambda cmd: SandboxResult(out.returncode, out.stdout, out.stderr, False), "app.py",
                      [{"method": "GET", "path": p, "fields": [], "shows": ""} for p in ("/items", "/boom", "/nope")])
    statuses = {r["path"]: r["status"] for r in pkg.checks_run[-1]["results"]}
    assert statuses == {"/items": 200, "/boom": 500, "/nope": 404} and not pkg.checks_run[-1]["pass"]


def test_probe_failure_puts_the_exception_first_for_the_coder():
    log = "Serving on 8000\n" + "noise line\n" * 60 + "Traceback (most recent call last):\nKeyError: 'items'\n"
    run, _ = runner(probe_out([{"path": f"/r{i}", "status": 500} for i in range(8)], log=log))
    routes = [{"method": "GET", "path": f"/r{i}", "fields": [], "shows": ""} for i in range(8)]
    pkg = route_probe(run, "app.py", routes)
    assert "KeyError: 'items'" in pkg.summary[:600] and len(pkg.summary) < 900


def test_full_app_line_leads_the_f3_summary():
    outputs = iter([SandboxResult(0, "SMOKE_STATUS 200\n", "", False),
                    probe_out([{"path": "/items", "status": 500}, {"path": "/about", "status": 200}])])
    pkg = build_check(lambda cmd: next(outputs), "app.py", "", ROUTES)
    assert pkg.summary.splitlines()[0].startswith("Full app: 1/2")


def test_timed_out_probe_says_so():
    run, _ = runner(SandboxResult(124, "", "", True))
    assert "timed out" in route_probe(run, "app.py", ROUTES).summary


def test_real_traceback_survives_access_log_noise(tmp_path):
    (tmp_path / "app.py").write_text(
        "import os\nfrom http.server import BaseHTTPRequestHandler, HTTPServer\n"
        "class H(BaseHTTPRequestHandler):\n"
        "    def do_GET(self):\n"
        "        if self.path == '/items':\n            raise KeyError('items')\n"
        "        self.send_response(200); self.end_headers(); self.wfile.write(b'ok')\n"
        "HTTPServer(('127.0.0.1', int(os.environ['PORT'])), H).serve_forever()\n")
    paths = ["/items", "/about", "/contact"]
    out = subprocess.run([sys.executable, "-c", PROBE_SCRIPT, "app.py", json.dumps(paths)],
                         cwd=tmp_path, capture_output=True, text=True, timeout=30,
                         env={"WT_PORT": "18766", "PATH": "/usr/bin:/bin"})
    pkg = route_probe(lambda cmd: SandboxResult(out.returncode, out.stdout, out.stderr, False), "app.py",
                      [{"method": "GET", "path": p, "fields": [], "shows": ""} for p in paths])
    first = pkg.summary.splitlines()[1]
    assert "KeyError" in first and "HTTP/1.1" not in first


def test_no_other_routes_still_shows_the_mvp_result():
    run, _ = runner(SandboxResult(0, "SMOKE_STATUS 200\n", "", False))
    assert "MVP" in build_check(run, "app.py", "", ROUTES[:1]).summary.splitlines()[0]


def test_every_sandbox_script_runs_isolated_from_the_app_folder():
    from watchtower.floors.f2_dev.devfloor import TEST_COMMAND
    from watchtower.floors.f4_qa_deploy.qafloor import run_qa
    seen = []
    record = lambda cmd: seen.append(cmd) or SandboxResult(0, "", "", False)  # noqa: E731
    smoke_test(record, "app.py")
    route_probe(record, "app.py", ROUTES)
    run_qa(record, "app.py", [{"name": "h", "method": "GET", "path": "/", "form": {}, "expect_status": 200,
                               "expect_text": ""}])
    assert all(cmd[:3] == ["python", "-I", "-c"] for cmd in seen + [TEST_COMMAND]) and len(seen) == 3


def test_app_that_exits_is_named_with_its_exit_code():
    run, _ = runner(SandboxResult(0, "SMOKE_STATUS None\nSMOKE_EXIT 0\nSMOKE_TEXT no\n", "", False))
    pkg = smoke_test(run, "app.py")
    assert not pkg.checks_run[0]["pass"]
    assert "exited with code 0 before answering" in pkg.summary and 'if __name__ == "__main__"' in pkg.summary
    assert "SMOKE_EXIT" in SMOKE_SCRIPT


def test_forged_exit_line_in_the_app_log_is_ignored():
    run, _ = runner(SandboxResult(0, "SMOKE_STATUS None\nSMOKE_EXIT None\nSMOKE_TEXT no\nSMOKE_EXIT 0\n", "", False))
    assert "exited with code" not in smoke_test(run, "app.py").summary
