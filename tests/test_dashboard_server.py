"""9a: the dashboard server is read-only, loopback-only, and safe to open in a browser."""
import http.client
import json
import re
import socket
import threading

import pytest

from watchtower.dashboard.page import render_page
from watchtower.dashboard.server import make_server
from watchtower.engine.governor.audit import AuditLog
from watchtower.engine.jobs import JobStore


@pytest.fixture
def served(conn, settings):
    JobStore(conn).create("<script>alert(1)</script> todo app")
    AuditLog(conn).append("bus", "board.note", {"floor": "f2", "text": "<img src=x onerror=alert(2)>"}, None)
    server = make_server(settings.db_path, 0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield server
    server.shutdown()
    server.server_close()


def _get(server, path="/", method="GET", host=None, body=None, headers=None):
    port = server.server_address[1]
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    c.putrequest(method, path, skip_host=True)
    c.putheader("Host", host if host is not None else f"127.0.0.1:{port}")
    for k, v in ({"X-Watchtower": "1", **(headers or {})}).items():
        if v is not None:
            c.putheader(k, v)
    c.putheader("Content-Length", str(len(body or b"")))
    c.endheaders(body)
    r = c.getresponse()
    data = r.read()
    c.close()
    return r, data


def test_it_binds_to_loopback_only(served):
    assert served.server_address[0] == "127.0.0.1"


def test_state_endpoint_returns_json(served):
    r, data = _get(served, "/api/state")
    assert r.status == 200 and r.getheader("Content-Type").startswith("application/json")
    assert json.loads(data)["jobs"][0]["status"] == "queued"


def test_the_page_is_html_with_a_nonce_matching_its_csp(served):
    r, data = _get(served, "/")
    assert r.status == 200 and r.getheader("Content-Type").startswith("text/html")
    csp = r.getheader("Content-Security-Policy")
    nonce = re.search(r"script-src 'nonce-([^']+)'", csp).group(1)
    assert f'<script nonce="{nonce}">'.encode() in data
    for needed in ("default-src 'none'", "connect-src 'self'", "frame-ancestors 'none'", "base-uri 'none'", "form-action 'none'"):
        assert needed in csp
    assert "unsafe-inline" not in csp and "unsafe-eval" not in csp


def test_each_page_gets_a_fresh_nonce(served):
    a = re.search(r"nonce-([^']+)'", _get(served, "/")[0].getheader("Content-Security-Policy")).group(1)
    b = re.search(r"nonce-([^']+)'", _get(served, "/")[0].getheader("Content-Security-Policy")).group(1)
    assert a != b


def test_security_headers_on_every_response(served):
    for path in ("/", "/api/state", "/nope"):
        r, _ = _get(served, path)
        assert r.getheader("X-Content-Type-Options") == "nosniff"
        assert r.getheader("Cache-Control") == "no-store"
        assert r.getheader("X-Frame-Options") == "DENY"
        assert r.getheader("Referrer-Policy") == "no-referrer"


def test_unknown_path_is_404_and_the_query_string_is_ignored(served):
    assert _get(served, "/nope")[0].status == 404
    assert _get(served, "/api/state?x=1")[0].status == 200


@pytest.mark.parametrize("method", ["POST", "PUT", "DELETE", "PATCH"])
def test_nothing_but_get_and_head_is_allowed(served, method):
    r, _ = _get(served, "/api/state", method=method, body=b"x=1")
    assert r.status == 405 and r.getheader("Allow") == "GET, HEAD"


def test_head_works_without_a_body(served):
    r, data = _get(served, "/api/state", method="HEAD")
    assert r.status == 200 and data == b""


@pytest.mark.parametrize("host", ["evil.example", "evil.example:80", "127.0.0.1", "localhost", "x", "127.0.0.1.evil.com:1", "[::1]:1"])
def test_a_foreign_or_portless_host_is_refused(served, host):
    assert _get(served, "/api/state", host=host)[0].status == 403
    assert _get(served, "/", method="POST", host=host)[0].status == 403


def test_localhost_with_the_right_port_is_accepted(served):
    port = served.server_address[1]
    assert _get(served, "/api/state", host=f"localhost:{port}")[0].status == 200
    assert _get(served, "/api/state", host=f"LOCALHOST:{port}")[0].status == 200


def test_a_missing_database_is_a_plain_503_without_details(tmp_path):
    server = make_server(tmp_path / "missing.db", 0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        r, data = _get(server, "/api/state")
        assert r.status == 503 and str(tmp_path).encode() not in data
    finally:
        server.shutdown()
        server.server_close()


def test_a_busy_port_is_a_clear_error(served):
    with pytest.raises(OSError, match="in use"):
        make_server(served.db_path, served.server_address[1])


def test_page_template_never_writes_html_from_data():
    page = render_page("n0nce")
    for banned in ("innerHTML", "outerHTML", "document.write", "eval(", "insertAdjacentHTML", "new Function", "setTimeout(\""):
        assert banned not in page
    assert "textContent" in page and 'nonce="n0nce"' in page


def test_hostile_text_never_appears_raw_in_any_html(served):
    _, page = _get(served, "/")
    assert b"<script>alert(1)" not in page and b"onerror=alert" not in page


def test_a_slow_client_does_not_hold_a_thread_forever(served):
    assert served.RequestHandlerClass.timeout and served.RequestHandlerClass.timeout <= 15
    s = socket.create_connection(("127.0.0.1", served.server_address[1]))
    s.close()
    assert _get(served, "/api/state")[0].status == 200


def test_the_state_endpoint_needs_the_apps_own_header_so_other_sites_cannot_poll_it(served):
    assert _get(served, "/api/state", headers={"X-Watchtower": None})[0].status == 403
    assert _get(served, "/api/state")[0].status == 200


@pytest.mark.parametrize("path", ["/", "/api/state"])
def test_cross_site_requests_are_refused(served, path):
    assert _get(served, path, headers={"Sec-Fetch-Site": "cross-site"})[0].status == 403
    assert _get(served, path, headers={"Sec-Fetch-Site": "same-origin"})[0].status == 200
    assert _get(served, path, headers={"Sec-Fetch-Site": "none"})[0].status == 200


def test_the_page_sends_the_header_when_it_polls():
    assert "X-Watchtower" in render_page("n")


def test_state_is_cached_briefly_so_polling_cannot_burn_cpu(served, monkeypatch):
    from watchtower.dashboard import server as srv
    calls = []
    real = srv.state
    monkeypatch.setattr(srv, "state", lambda *a, **k: calls.append(1) or real(*a, **k))
    for _ in range(5):
        assert _get(served, "/api/state")[0].status == 200
    assert len(calls) == 1


def test_a_server_error_in_state_is_a_plain_503(served, monkeypatch):
    from watchtower.dashboard import server as srv
    monkeypatch.setattr(srv, "state", lambda *a, **k: (_ for _ in ()).throw(ValueError("boom with /secret/path")))
    r, data = _get(served, "/api/state")
    assert r.status == 503 and b"secret" not in data


def test_connections_are_capped_and_a_full_server_answers_503(served):
    served.max_connections = 3
    served._slots = __import__("threading").BoundedSemaphore(3)
    held = [socket.create_connection(("127.0.0.1", served.server_address[1])) for _ in range(3)]
    try:
        import time
        time.sleep(0.3)
        r, _ = _get(served, "/api/state")
        assert r.status == 503
    finally:
        for h in held:
            h.close()


def test_a_trickling_client_is_cut_off_by_a_total_deadline(served):
    import time
    served.RequestHandlerClass.deadline = 0.6
    s = socket.create_connection(("127.0.0.1", served.server_address[1]))
    t0, cut = time.time(), False
    try:
        for _ in range(20):  # one byte every 0.3 s would keep a per-read timeout alive for ever
            try:
                s.sendall(b"G")
                time.sleep(0.3)
            except OSError:
                cut = True
                break
        assert cut and time.time() - t0 < 4
    finally:
        s.close()
        served.RequestHandlerClass.deadline = 15
