"""9a: the read-only dashboard server. Loopback only, GET/HEAD only, Host-checked against DNS rebinding, strict CSP.
It reads the tower's database through a read-only connection and has no way to change anything."""
from __future__ import annotations

import json
import secrets
import sqlite3
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from watchtower.dashboard.data import state
from watchtower.dashboard.page import render_page

HOST = "127.0.0.1"


class _Server(ThreadingHTTPServer):
    allow_reuse_address = False  # a busy port must be an error, not a silent second listener
    daemon_threads = True
    request_queue_size = 16

    def __init__(self, address, handler, db_path: Path):
        self.db_path = Path(db_path)
        super().__init__(address, handler)


class _Handler(BaseHTTPRequestHandler):
    timeout = 10  # a slow or stalled client frees its thread
    server: _Server

    def log_message(self, *args) -> None:
        pass

    def _allowed_host(self) -> bool:
        port = self.server.server_address[1]
        return (self.headers.get("Host") or "").lower() in (f"127.0.0.1:{port}", f"localhost:{port}")

    def _send(self, status: int, body: bytes, ctype: str, extra: dict | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _text(self, status: int, message: str) -> None:
        self._send(status, message.encode(), "text/plain; charset=utf-8")

    def _serve(self) -> None:
        if not self._allowed_host():
            return self._text(403, "forbidden host")
        path = urlsplit(self.path).path
        if path == "/":
            nonce = secrets.token_urlsafe(16)
            csp = (f"default-src 'none'; script-src 'nonce-{nonce}'; style-src 'nonce-{nonce}'; connect-src 'self'; "
                   "base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
            return self._send(200, render_page(nonce).encode(), "text/html; charset=utf-8", {"Content-Security-Policy": csp})
        if path == "/api/state":
            try:
                body = json.dumps(state(self.server.db_path)).encode()
            except (OSError, sqlite3.Error):
                return self._text(503, "database unavailable")  # no paths or error text leave the server
            return self._send(200, body, "application/json", {"Content-Security-Policy": "default-src 'none'"})
        self._text(404, "not found")

    do_GET = do_HEAD = _serve

    def _refuse(self) -> None:
        if not self._allowed_host():
            return self._text(403, "forbidden host")
        self._send(405, b"read only", "text/plain; charset=utf-8", {"Allow": "GET, HEAD"})

    do_POST = do_PUT = do_DELETE = do_PATCH = do_OPTIONS = _refuse


def make_server(db_path: Path, port: int) -> ThreadingHTTPServer:
    """Bind 127.0.0.1:port (0 = any free port). Raises OSError if the port is busy."""
    try:
        return _Server((HOST, port), _Handler, db_path)
    except OSError as e:
        raise OSError(f"port {port} is in use; try --port <other>") from e
