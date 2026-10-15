"""Phase 7a: for the add-and-list apps the tower already checks (contract_checks), the tower writes the web
server and the coder writes only plain Python: store.add(entry) and store.items(). Runs 26-31 failed on HTTP
plumbing the 7B kept getting wrong one piece per attempt (imports, quote_plus, XSS, items not shown)."""
from __future__ import annotations

import sys
from pathlib import PurePosixPath

from watchtower.engine.workspace import Workspace
from watchtower.floors.f4_qa_deploy.contract import contract_checks

STORE, STORE_TESTS = "store.py", "test_store.py"
SHADOWS = {"html.py", "os.py", "traceback.py", "http", "urllib"}  # what the server imports: a coder copy would win
MARK = '"""Web server written by the tower.'

TEMPLATE = '''"""Web server written by the tower. Do not edit: write store.py (add(entry) and items())."""
import html
import os
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import store

__CONFIG__
MAX_BODY = 100_000


def form_html():
    inputs = "".join('<p><label>' + html.escape(f) + ' <input name="' + html.escape(f) + '"></label></p>'
                     for f in FIELDS)
    return ('<form method="post" action="' + html.escape(ADD_PATH) + '">' + inputs
            + '<button type="submit">Add</button></form>')


def items_html():
    rows = []
    for item in store.items():
        if isinstance(item, dict):
            text = " - ".join(html.escape(str(item.get(f, ""))) for f in FIELDS)
        else:
            text = html.escape(str(item))
        rows.append("<li>" + text + "</li>")
    return "<ul>" + "".join(rows) + "</ul>"


class Handler(BaseHTTPRequestHandler):
    def send_page(self, status, body, location=None):
        data = ("<!doctype html><html><head><meta charset=\\"utf-8\\"><title>" + html.escape(TITLE)
                + "</title></head><body><h1>" + html.escape(TITLE) + "</h1>" + body + "</body></html>").encode()
        self.send_response(status)
        if location:
            self.send_header("Location", location)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = urlparse(self.path).path
        try:
            if path == LIST_PAGE or (path == "/" and "/" not in (LIST_PAGE, FORM_PAGE)):
                link = "" if FORM_PAGE == LIST_PAGE else '<p><a href="' + html.escape(FORM_PAGE) + '">Add</a></p>'
                body = (form_html() if FORM_PAGE == LIST_PAGE else link) + items_html()
            elif path == FORM_PAGE:
                body = form_html()
            else:
                return self.send_page(404, "<p>Not found</p>")
        except Exception:
            traceback.print_exc()
            return self.send_page(500, "<p>Server error</p>")
        self.send_page(200, body)

    def do_POST(self):
        if urlparse(self.path).path != ADD_PATH:
            return self.send_page(404, "<p>Not found</p>")
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = -1
        if not 0 <= length <= MAX_BODY:
            return self.send_page(413, "<p>Too much data</p>")
        form = parse_qs(self.rfile.read(length).decode("utf-8", "replace"))
        entry = {f: form.get(f, [""])[0].strip() for f in FIELDS}
        if not all(entry.values()):
            return self.send_page(400, "<p>Please fill in every field.</p>" + form_html())
        try:
            store.add(entry)
        except Exception:
            traceback.print_exc()
            return self.send_page(500, "<p>Server error</p>")
        self.send_page(303, "", location=LIST_PAGE)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    print("Serving on port", port, flush=True)
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
'''


def _store_purpose(fields: list[str]) -> str:
    keys = ", ".join(fields)
    return (f"plain Python, no web code: add(entry) saves one dict with keys {keys}; items() returns all saved "
            "dicts, oldest first (a module-level list is fine)")[:200]


def _drop_stale(ws: Workspace, previous, keep: str = "") -> None:
    """A re-plan without the skeleton (or with a new entry): remove the tower's old server so a unit rewrites
    it (7a review r1). Only a file that still carries the tower's mark: never the coder's own."""
    for path in previous:
        if path != keep and path.endswith(".py") and path in ws.files() and ws.read(path).startswith(MARK):
            ws.delete(path)


def _fits(plan: dict, checks: list[dict]) -> bool:
    entry = plan["entry"]
    paths = [c["path"] for c in checks[:3]]
    return ("/" not in entry and entry.lower() not in (STORE, STORE_TESTS)
            and entry[:-3] not in sys.stdlib_module_names and not any("?" in p for p in paths)
            and all((r["method"], r["path"]) in {("GET", paths[2]), ("GET", paths[0]), ("POST", paths[1])}
                    for r in plan["routes"]))


def apply(plan: dict, title: str, ws: Workspace, previous=frozenset()) -> tuple[dict, set[str]]:
    """(plan, owned paths). Unchanged plan and no owned paths unless the contract is exactly add-and-list."""
    routes = plan["routes"]
    checks, _ = contract_checks(routes, "000000")
    if not checks or not _fits(plan, checks):
        _drop_stale(ws, previous)
        return plan, set()
    form_page, add, page = checks[0]["path"], checks[1]["path"], checks[2]["path"]
    fields = list(checks[1]["form"])
    entry = plan["entry"]
    _drop_stale(ws, previous, keep=entry)
    config = "\n".join(f"{k} = {v!r}" for k, v in (("TITLE", str(title)[:100]), ("FIELDS", fields),
                       ("LIST_PAGE", page), ("FORM_PAGE", form_page), ("ADD_PATH", add)))
    ws.write(entry, TEMPLATE.replace("__CONFIG__", config))
    files = [{"path": entry, "purpose": "web server, written by the tower: do not change it"},
             {"path": STORE, "purpose": _store_purpose(fields)},
             {"path": STORE_TESTS, "purpose": "unittest tests for store.add and store.items"}]
    return {**plan, "files": files}, {entry} | SHADOWS
