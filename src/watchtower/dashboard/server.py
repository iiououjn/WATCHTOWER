"""9a: the read-only dashboard server. Loopback only, GET/HEAD only, Host-checked against DNS rebinding, strict CSP.
It reads the tower's database through a read-only connection and has no way to change anything.
Hardening against a hostile web page or a slow local client: the state endpoint needs the page's own header (a
cross-site request cannot send it without a refused preflight), answers are cached for 2 s, the full audit-chain
check runs at most every 30 s, connections are capped, and every connection has a total deadline."""
from __future__ import annotations

import json
import secrets
import socket
import sqlite3
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from watchtower.dashboard.data import state
from watchtower.dashboard.page import render_page

HOST = "127.0.0.1"
CACHE_SECONDS = 2
CHAIN_SECONDS = 30
MAX_CONNECTIONS = 32
BUSY = b"HTTP/1.1 503 Service Unavailable\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"


class _Server(ThreadingHTTPServer):
    allow_reuse_address = False  # a busy port must be an error, not a silent second listener
    daemon_threads = True
    request_queue_size = 16

    def __init__(self, address, handler, db_path: Path):
        self.db_path = Path(db_path)
        self.max_connections = MAX_CONNECTIONS
        self._slots = threading.BoundedSemaphore(MAX_CONNECTIONS)
        self._lock = threading.Lock()
        self._cached: tuple[float, bytes] | None = None
        self._chain: tuple[float, bool] | None = None
        super().__init__(address, handler)

    def state_json(self) -> bytes:
        with self._lock:  # one computation at a time; polling cannot stack up full scans
            now = time.monotonic()
            if self._cached and now - self._cached[0] < CACHE_SECONDS:
                return self._cached[1]
            check = self._chain is None or now - self._chain[0] >= CHAIN_SECONDS
            data = state(self.db_path, check_chain=check)
            if check:
                self._chain = (now, bool(data["chain_ok"]))
            else:
                data["chain_ok"] = self._chain[1]
            body = json.dumps(data, allow_nan=False).encode()
            self._cached = (now, body)
            return body

    def handle_error(self, request, client_address) -> None:
        pass  # a client that vanished mid-answer is not worth a traceback on the owner's terminal

    def process_request(self, request, client_address):
        if not self._slots.acquire(blocking=False):
            try:
                request.settimeout(0)  # never wait on a full server's client
                try:
                    request.recv(4096)  # take what has already arrived so closing does not reset the answer away
                except OSError:
                    pass
                request.sendall(BUSY)
            except OSError:
                pass
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self._slots.release()  # the thread never started, so its finally will never run
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._slots.release()


class _Handler(BaseHTTPRequestHandler):
    timeout = 10  # per read; `deadline` below bounds the whole connection
    deadline = 15
    server: _Server

    def setup(self) -> None:
        super().setup()
        self._watchdog = threading.Timer(self.deadline, self._cut)
        self._watchdog.daemon = True
        self._watchdog.start()

    def _cut(self) -> None:
        try:
            self.connection.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass

    def finish(self) -> None:
        self._watchdog.cancel()
        super().finish()

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

    def _origin_ok(self) -> bool:
        return self._allowed_host() and self.headers.get("Sec-Fetch-Site", "same-origin") != "cross-site"

    def _serve(self) -> None:
        if not self._origin_ok():
            return self._text(403, "forbidden")
        path = urlsplit(self.path).path
        if path == "/":
            nonce = secrets.token_urlsafe(16)
            csp = (f"default-src 'none'; script-src 'nonce-{nonce}'; style-src 'nonce-{nonce}'; connect-src 'self'; "
                   "base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
            return self._send(200, render_page(nonce).encode(), "text/html; charset=utf-8", {"Content-Security-Policy": csp})
        if path == "/api/state":
            if self.headers.get("X-Watchtower") != "1":  # only this page sends it; a cross-site fetch cannot
                return self._text(403, "forbidden")
            try:
                body = self.server.state_json()
            except (OSError, sqlite3.Error, ValueError, TypeError, AttributeError, KeyError, RecursionError):
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
