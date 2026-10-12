"""Fixed programs that run inside deployed containers. Never AI-written."""

# argv: listen_port target_host target_port [entry]. With an entry it is the app's launcher: it starts the
# app with PORT=target_port (exactly as QA did) and forwards 0.0.0.0:listen to it, so an app that binds
# 127.0.0.1 is still reachable. If forwarding ever breaks, the container exits so Docker restarts it.
FORWARD = """\
import os, socket, subprocess, sys, threading
listen, host, port = int(sys.argv[1]), sys.argv[2], int(sys.argv[3])
app = subprocess.Popen([sys.executable, sys.argv[4]], env={**os.environ, "PORT": str(port)}) if len(sys.argv) > 4 else None
IDLE = 300
def pipe(a, b):
    try:
        while True:
            data = a.recv(65536)
            if not data:
                break
            b.sendall(data)
    except OSError:
        pass
    try:
        b.shutdown(socket.SHUT_WR)
    except OSError:
        pass
def serve(c):
    try:
        u = socket.create_connection((host, port), timeout=5)
    except OSError:
        c.close()
        return
    c.settimeout(IDLE)
    u.settimeout(IDLE)
    t = threading.Thread(target=pipe, args=(c, u), daemon=True)
    try:
        t.start()
    except RuntimeError:
        c.close()
        u.close()
        return
    pipe(u, c)
    t.join(IDLE)
    c.close()
    u.close()
def accept():
    try:
        srv = socket.create_server(("0.0.0.0", listen))
        while True:
            try:
                c, _ = srv.accept()
            except OSError:
                continue
            try:
                threading.Thread(target=serve, args=(c,), daemon=True).start()
            except RuntimeError:
                c.close()
    finally:
        os._exit(1)
if app is None:
    accept()
threading.Thread(target=accept, daemon=True).start()
sys.exit(app.wait())
"""

# argv: listen_port target_host target_port. HTTP reverse proxy in front of the app: adds a strict
# Content-Security-Policy (and drops the app's own), so pages cannot load or send data anywhere but the
# app itself, nor call other services on 127.0.0.1 (e.g. Ollama).
EDGE = """\
import http.client, sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
listen, host, port = int(sys.argv[1]), sys.argv[2], int(sys.argv[3])
CSP = ("default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; "
       "img-src 'self' data:; connect-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'")
DROP = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "proxy-connection", "te",
        "trailer", "trailers", "transfer-encoding", "upgrade", "content-length", "content-security-policy",
        "content-security-policy-report-only", "host"}
MAX = 20000000
class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"
    timeout = 60
    def log_message(self, *a):
        pass
    def handle_one(self):
        size = int(self.headers.get("Content-Length") or 0)
        if size < 0 or size > MAX:
            self.send_error(413)
            return
        body = self.rfile.read(size) if size else None
        headers = {k: v for k, v in self.headers.items() if k.lower() not in DROP}
        try:
            conn = http.client.HTTPConnection(host, port, timeout=30)
            conn.request(self.command, self.path, body=body, headers=headers)
            resp = conn.getresponse()
            data = resp.read(MAX)
            conn.close()
        except Exception:
            self.send_error(502)
            return
        self.send_response_only(resp.status, resp.reason)
        for k, v in resp.getheaders():
            if k.lower() not in DROP:
                self.send_header(k, v)
        self.send_header("Content-Security-Policy", CSP)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)
    do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = do_HEAD = do_OPTIONS = handle_one
ThreadingHTTPServer.daemon_threads = True
ThreadingHTTPServer(("0.0.0.0", listen), H).serve_forever()
"""
