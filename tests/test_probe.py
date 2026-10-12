import json
import subprocess
import sys

import pytest

from watchtower.engine.sandbox import SandboxResult
from watchtower.floors.f5_oversight.probe import XSS_SCRIPT, xss_probe

ROUTES = [{"method": "GET", "path": "/", "fields": [], "shows": ""},
          {"method": "POST", "path": "/add", "fields": ["item"], "shows": ""},
          {"method": "GET", "path": "/list", "fields": [], "shows": ""}]

APP = """\
import html, os, urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer
items = []
ESCAPE = {escape}
class H(BaseHTTPRequestHandler):
    def do_GET(self):
        body = "<ul>" + "".join("<li>" + (html.escape(i) if ESCAPE else i) + "</li>" for i in items) + "</ul>"
        self.send_response(200); self.send_header("Content-Type", "text/html"); self.end_headers()
        self.wfile.write(body.encode())
    def do_POST(self):
        data = urllib.parse.parse_qs(self.rfile.read(int(self.headers["Content-Length"])).decode())
        items.append(data.get("item", [""])[0])
        print("WATCHTOWER_XSS []")
        self.send_response(303); self.send_header("Location", "/list"); self.end_headers()
    def log_message(self, *a):
        pass
HTTPServer(("127.0.0.1", int(os.environ["PORT"])), H).serve_forever()
"""


def free_port():
    import socket
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def run_real(tmp_path, escape, port=None, app=None):
    port = port or free_port()
    (tmp_path / "app.py").write_text(app or APP.format(escape=escape))
    def run(cmd):
        out = subprocess.run([sys.executable] + cmd[1:], cwd=tmp_path, capture_output=True, text=True, timeout=40,
                             env={"WT_PORT": str(port), "PATH": "/usr/bin:/bin"})
        return SandboxResult(out.returncode, out.stdout, out.stderr, False)
    return run


def test_stored_html_injection_is_a_high_finding(tmp_path):
    findings = xss_probe(run_real(tmp_path, False), "app.py", ROUTES)
    assert [f["id"] for f in findings] == ["XSS"] and findings[0]["severity"] == "HIGH"
    assert "/add" in findings[0]["text"] and "item" in findings[0]["text"]


def test_an_app_that_escapes_passes(tmp_path):
    assert xss_probe(run_real(tmp_path, True), "app.py", ROUTES) == []


def test_no_form_routes_means_no_probe():
    calls = []
    assert xss_probe(lambda cmd: calls.append(cmd), "app.py", ROUTES[:1]) == [] and calls == []


@pytest.mark.parametrize("stdout", ["", "WATCHTOWER_XSS []\nWATCHTOWER_XSS []\n", "WATCHTOWER_XSS {bad\n"])
def test_missing_or_forged_result_is_incomplete_not_a_pass(stdout):
    findings = xss_probe(lambda cmd: SandboxResult(0, stdout, "", False), "app.py", ROUTES)
    assert len(findings) == 1 and findings[0]["severity"] == "MEDIUM" and findings[0]["id"] == "XSS-PROBE"


def test_probe_never_posts_to_hostile_paths():
    hostile = [{"method": "POST", "path": "//evil.com/x", "fields": ["a"], "shows": ""}]
    calls = []
    assert xss_probe(lambda cmd: calls.append(cmd), "app.py", hostile) == [] and calls == []


def test_script_is_sent_with_the_plan():
    calls = []
    xss_probe(lambda cmd: calls.append(cmd) or SandboxResult(0, "WATCHTOWER_XSS []\n", "", False), "app.py", ROUTES)
    plan = json.loads(calls[0][5])
    assert calls[0][:4] == ["python", "-I", "-c", XSS_SCRIPT] and plan["posts"][0]["path"] == "/add"
    assert "/list" in plan["gets"] and "/" in plan["gets"]


def test_a_planted_json_module_cannot_forge_a_clean_result(tmp_path):
    (tmp_path / "json.py").write_text("def dumps(*a, **k):\n    return '[]'\ndef loads(s):\n    import sys\n"
                                      "    sys.path.remove(sys.path[0]); del sys.modules['json']; import json\n"
                                      "    return json.loads(s)\n")
    findings = xss_probe(run_real(tmp_path, False), "app.py", ROUTES)
    assert [f["id"] for f in findings] == ["XSS"]


def test_a_validated_number_field_does_not_hide_the_text_field(tmp_path):
    app = APP.format(escape=False).replace(
        'items.append(data.get("item", [""])[0])',
        'float(data.get("amount", ["x"])[0]); items.append(data.get("item", [""])[0])')
    routes = [ROUTES[0], {"method": "POST", "path": "/add", "fields": ["item", "amount"], "shows": ""}, ROUTES[2]]
    findings = xss_probe(run_real(tmp_path, False, app=app), "app.py", routes)
    assert [f["id"] for f in findings] == ["XSS"] and "item" in findings[0]["text"]


def test_json_api_responses_are_not_html_injection(tmp_path):
    app = APP.format(escape=False).replace('"text/html"', '"application/json"')
    assert xss_probe(run_real(tmp_path, False, app=app), "app.py", ROUTES) == []


def test_an_upper_cased_marker_is_still_raw_html(tmp_path):
    app = APP.format(escape=False).replace("items.append(data", "items.append(lambda v: v)").replace(
        'items.append(lambda v: v).get("item", [""])[0])', 'items.append(data.get("item", [""])[0].upper())')
    findings = xss_probe(run_real(tmp_path, False, app=app), "app.py", ROUTES)
    assert [f["id"] for f in findings] == ["XSS"]


def test_an_app_that_answers_nothing_is_incomplete_not_clean(tmp_path):
    app = "import time\ntime.sleep(0.2)\n"
    findings = xss_probe(run_real(tmp_path, False, app=app), "app.py", ROUTES)
    assert len(findings) == 1 and findings[0]["severity"] == "MEDIUM"


def test_fix_advice_survives_the_finding_line_cut(tmp_path):
    from watchtower.floors.f5_oversight.oversight import _line
    findings = xss_probe(run_real(tmp_path, False), "app.py", ROUTES)
    assert "html.escape" in _line(findings[0])
