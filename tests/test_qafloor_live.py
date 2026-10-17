"""Floor 4 QA run against small live apps (tower-written fixtures): how user text is shown, escaped and encoded.
Split out of test_qafloor.py (8d review r1: test files stay under 500 lines)."""
import json
import os
import socket
import subprocess
import sys

from watchtower.engine.sandbox import SandboxResult
from watchtower.floors.f4_qa_deploy.qafloor import QA_SCRIPT, parse_checks, run_qa


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


ECHO_APP = '''import html, os
from http.server import BaseHTTPRequestHandler, HTTPServer
ITEMS = []
class H(BaseHTTPRequestHandler):
    def do_POST(self):
        raw = self.rfile.read(int(self.headers["Content-Length"])).decode()
        ITEMS.append(raw.split("=", 1)[1])  # MODE
        self.do_GET()
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(("<ul>" + "".join(f"<li>{i}</li>" for i in ITEMS) + "</ul>").encode())
    def log_message(self, *a):
        pass
HTTPServer(("127.0.0.1", int(os.environ["PORT"])), H).serve_forever()
'''


def _live(tmp_path, app, checks):
    (tmp_path / "app.py").write_text(app)
    proc = subprocess.run([sys.executable, "-c", QA_SCRIPT, "app.py", json.dumps(checks)], cwd=tmp_path,
                          capture_output=True, text=True, timeout=60, env={**os.environ, "WT_PORT": str(free_port())})
    return run_qa(lambda cmd: SandboxResult(proc.returncode, proc.stdout, proc.stderr, False), "app.py", checks)


def test_a_form_value_shown_still_url_encoded_is_named(tmp_path):
    checks = parse_checks({"checks": [
        {"name": "add", "method": "POST", "path": "/add", "form": {"item": "New todo & more"}, "expect_text": ""},
        {"name": "list", "path": "/", "expect_text": "New todo & more"}]})
    pkg = _live(tmp_path, ECHO_APP, checks)
    line = next(ln for ln in pkg.summary.splitlines() if ln.startswith("- list:"))
    assert "URL-encoded" in line and "parse_qs" in line and "quote_plus" in line and line.index("URL-encoded") < 120


HREF_APP = """import os
from http.server import BaseHTTPRequestHandler, HTTPServer
class H(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"<a href='/x?t=New+todo'>open</a>")
HTTPServer(("127.0.0.1", int(os.environ["PORT"])), H).serve_forever()
"""


def test_url_encoded_text_only_inside_a_link_gets_no_hint(tmp_path):
    """6y review r1: quote() is right inside an href; the hint must look at visible text only."""
    checks = parse_checks({"checks": [{"name": "list", "path": "/", "expect_text": "New todo"}]})
    line = next(ln for ln in _live(tmp_path, HREF_APP, checks).summary.splitlines() if ln.startswith("- list:"))
    assert "FAIL" in line and "URL-encoded" not in line and "<a href" in line  # the app really answered


def _shown(tmp_path, mode):
    app = ECHO_APP.replace('ITEMS.append(raw.split("=", 1)[1])  # MODE',
                           "from urllib.parse import parse_qs\n        ITEMS.append(" + mode + ")")
    value = "2409400 <&> 240940"
    checks = parse_checks({"checks": [
        {"name": "add", "method": "POST", "path": "/add", "form": {"item": value}, "expect_text": ""},
        {"name": "list", "path": "/", "expect_text": value}]})
    checks[1]["expect_escaped"] = True  # tower-only flag, set after validation like contract_checks
    return next(ln for ln in _live(tmp_path, app, checks).summary.splitlines() if ln.startswith("- list:"))


def test_escaped_once_passes(tmp_path):  # 6z (run 30): XSS, over-escaping and encoding in one deciding check
    assert "PASS" in _shown(tmp_path, 'html.escape(parse_qs(raw)["item"][0])')


def test_unescaped_user_text_fails_with_an_xss_hint(tmp_path):
    line = _shown(tmp_path, 'parse_qs(raw)["item"][0]')
    assert "FAIL" in line and "html.escape" in line and "unescaped" in line


def test_text_escaped_twice_fails_with_a_hint(tmp_path):  # run 29: escape on save and again on show
    line = _shown(tmp_path, 'html.escape(html.escape(parse_qs(raw)["item"][0]))')
    assert "FAIL" in line and "more than once" in line


def test_model_checks_cannot_set_expect_escaped():  # 6z review r1: tower-only flag
    c = parse_checks({"checks": [{"name": "l", "path": "/", "expect_text": "a", "expect_escaped": True}]})
    assert "expect_escaped" not in c[0]


def test_escaped_list_plus_a_raw_copy_fails(tmp_path):  # 6z review r1: a raw banner is still XSS
    app = ECHO_APP.replace('"<ul>" +', '"<p>last: " + (parse_qs(LAST[0])["item"][0] if LAST else "") + "</p><ul>" +')
    app = app.replace("ITEMS = []", "ITEMS = []\nLAST = []").replace(
        'ITEMS.append(raw.split("=", 1)[1])  # MODE',
        'LAST[:] = [raw]\n        ITEMS.append(html.escape(parse_qs(raw)["item"][0]))')
    app = app.replace("import html, os", "import html, os\nfrom urllib.parse import parse_qs")
    value = "2409400 <&> 240940"
    checks = parse_checks({"checks": [
        {"name": "add", "method": "POST", "path": "/add", "form": {"item": value}, "expect_text": ""},
        {"name": "list", "path": "/", "expect_text": value}]})
    checks[1]["expect_escaped"] = True
    line = next(ln for ln in _live(tmp_path, app, checks).summary.splitlines() if ln.startswith("- list:"))
    assert "FAIL" in line and "unescaped" in line


def test_numeric_entities_count_as_escaped_once(tmp_path):
    assert "PASS" in _shown(tmp_path, 'parse_qs(raw)["item"][0].replace("&", "&#38;").replace("<", "&#60;")'
                                      '.replace(">", "&#x3e;")')


def test_text_escaped_three_times_gets_the_hint(tmp_path):  # run 29
    assert "more than once" in _shown(tmp_path, 'html.escape(html.escape(html.escape(parse_qs(raw)["item"][0])))')


def test_html_escaped_text_counts_as_shown(tmp_path):
    app = ECHO_APP.replace('ITEMS.append(raw.split("=", 1)[1])  # MODE',
                           'from urllib.parse import parse_qs\n        ITEMS.append(html.escape(parse_qs(raw)["item"][0]))')
    checks = parse_checks({"checks": [
        {"name": "add", "method": "POST", "path": "/add", "form": {"item": "Tom & Jerry <3"}, "expect_text": ""},
        {"name": "list", "path": "/", "expect_text": "Tom & Jerry <3"}]})
    assert _live(tmp_path, app, checks).checks_run[-1]["pass"] is True


def test_escaped_markup_does_not_pass_a_markup_check(tmp_path):
    app = ECHO_APP.replace('self.wfile.write(("<ul>"', 'self.wfile.write(html.escape("<ul>"')  # escapes its own markup
    checks = parse_checks({"checks": [
        {"name": "add", "method": "POST", "path": "/add", "form": {"item": "milk"}, "expect_text": ""},
        {"name": "list", "path": "/", "expect_text": "<li>milk</li>"}]})
    assert _live(tmp_path, app, checks).checks_run[-1]["pass"] is False


def test_json_list_page_is_not_held_to_html_escaping(tmp_path):  # 6z review r2: raw '<' is harmless in JSON
    app = ECHO_APP.replace("self.end_headers()", 'self.send_header("Content-Type", "application/json")\n        '
                           'self.end_headers()').replace(
        '("<ul>" + "".join(f"<li>{i}</li>" for i in ITEMS) + "</ul>")', "json.dumps(ITEMS)").replace(
        'ITEMS.append(raw.split("=", 1)[1])  # MODE', 'ITEMS.append(parse_qs(raw)["item"][0])').replace(
        "import html, os", "import html, json, os\nfrom urllib.parse import parse_qs")
    value = "2409400 <&> 240940"
    checks = parse_checks({"checks": [
        {"name": "add", "method": "POST", "path": "/add", "form": {"item": value}, "expect_text": ""},
        {"name": "list", "path": "/", "expect_text": value}]})
    checks[1]["expect_escaped"] = True
    line = next(ln for ln in _live(tmp_path, app, checks).summary.splitlines() if ln.startswith("- list:"))
    assert "PASS" in line


def test_raw_text_in_a_comment_still_fails(tmp_path):  # 6z review r3: '-->' breaks out of a comment
    assert "unescaped" in _shown(tmp_path, '(ITEMS.append("<!-- " + parse_qs(raw)["item"][0] + " -->") or '
                                           'html.escape(parse_qs(raw)["item"][0]))')
