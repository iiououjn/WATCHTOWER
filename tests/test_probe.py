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


def run_real(tmp_path, escape, port):
    (tmp_path / "app.py").write_text(APP.format(escape=escape))
    def run(cmd):
        out = subprocess.run([sys.executable] + cmd[1:], cwd=tmp_path, capture_output=True, text=True, timeout=40,
                             env={"WT_PORT": str(port), "PATH": "/usr/bin:/bin"})
        return SandboxResult(out.returncode, out.stdout, out.stderr, False)
    return run


def test_stored_html_injection_is_a_high_finding(tmp_path):
    findings = xss_probe(run_real(tmp_path, False, 18771), "app.py", ROUTES)
    assert [f["id"] for f in findings] == ["XSS"] and findings[0]["severity"] == "HIGH"
    assert "/add" in findings[0]["text"] and "item" in findings[0]["text"]


def test_an_app_that_escapes_passes(tmp_path):
    assert xss_probe(run_real(tmp_path, True, 18772), "app.py", ROUTES) == []


def test_no_form_routes_means_no_probe():
    calls = []
    assert xss_probe(lambda cmd: calls.append(cmd), "app.py", ROUTES[:1]) == [] and calls == []


@pytest.mark.parametrize("stdout", ["", "WATCHTOWER_XSS []\nWATCHTOWER_XSS []\n", "WATCHTOWER_XSS {bad\n"])
def test_missing_or_forged_result_is_incomplete_not_a_pass(stdout):
    findings = xss_probe(lambda cmd: SandboxResult(0, stdout, "", False), "app.py", ROUTES)
    assert len(findings) == 1 and findings[0]["severity"] == "UNKNOWN"


def test_probe_never_posts_to_hostile_paths():
    hostile = [{"method": "POST", "path": "//evil.com/x", "fields": ["a"], "shows": ""}]
    calls = []
    assert xss_probe(lambda cmd: calls.append(cmd), "app.py", hostile) == [] and calls == []


def test_script_is_sent_with_the_plan():
    calls = []
    xss_probe(lambda cmd: calls.append(cmd) or SandboxResult(0, "WATCHTOWER_XSS []\n", "", False), "app.py", ROUTES)
    plan = json.loads(calls[0][4])
    assert calls[0][:3] == ["python", "-c", XSS_SCRIPT] and plan["posts"][0]["path"] == "/add"
    assert "/list" in plan["gets"] and "/" in plan["gets"]
