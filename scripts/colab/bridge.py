"""Mac side of the Colab model host. Listens on 127.0.0.1:11434 and forwards to the Colab tunnel with a bearer token,
so the tower still sees a loopback Ollama. Usage: COLAB_URL=https://x.trycloudflare.com COLAB_TOKEN=... python bridge.py"""
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx

UPSTREAM = os.environ.get("COLAB_URL", "").rstrip("/")
TOKEN = os.environ.get("COLAB_TOKEN", "")


class Bridge(BaseHTTPRequestHandler):
    def _forward(self):
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        try:
            r = httpx.request(self.command, UPSTREAM + self.path, content=body, timeout=900, trust_env=False,
                              headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"})
            status, data = r.status_code, r.content
        except httpx.HTTPError as e:
            status, data = 502, f"bridge: {type(e).__name__}".encode()
        self.send_response(status)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(data)

    do_GET = do_POST = do_DELETE = _forward

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    if not UPSTREAM.startswith("https://") or not TOKEN:
        sys.exit("set COLAB_URL (https://...) and COLAB_TOKEN")
    print("bridge on http://127.0.0.1:11434 ->", UPSTREAM)
    ThreadingHTTPServer(("127.0.0.1", 11434), Bridge).serve_forever()
