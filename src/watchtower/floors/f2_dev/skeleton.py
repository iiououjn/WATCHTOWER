"""Phase 7a: for the add-and-list apps the tower already checks (contract_checks), the tower writes the web
server and the coder writes only plain Python: store.add(entry) and store.items(). Runs 26-31 failed on HTTP
plumbing the 7B kept getting wrong one piece per attempt (imports, quote_plus, XSS, items not shown)."""
from __future__ import annotations

import ast
import sys
from pathlib import PurePosixPath

import html

from watchtower.engine.workspace import TOWER_MARK, Workspace, WorkspaceError
from watchtower.floors.f4_qa_deploy.contract import contract_checks

STORE, STORE_TESTS = "store.py", "test_store.py"
SHADOWS = {"html.py", "os.py", "traceback.py", "http", "urllib", "store"}  # 'store/' would shadow store.py  # what the server imports: a coder copy would win
MARK = TOWER_MARK
ONLY_NOTE = "Write only store.py and test_store.py; any other file is rejected.\n"  # 7c review r1 I3
SAFE = {"__future__", "json", "copy", "threading", "collections", "dataclasses", "typing", "datetime", "time",
        "uuid", "itertools", "functools", "re", "html"}  # 7c review r2: store.py runs inside the tower's server
SAFE_TESTS = SAFE | {"unittest", "store", "importlib", "sys", "os"}  # tests run in Docker; reload(store), sys.path
BANNED = {"exec", "eval", "compile", "open", "__import__", "import_module", "breakpoint", "input", "getattr",
          "setattr", "delattr", "globals", "vars", "locals"}  # by name, called or aliased (review r3)
DANGER = {"os", "sys", "subprocess", "builtins", "importlib", "inspect", "ctypes", "socket", "shutil", "pty", "posix",
          "runpy", "code", "pickle", "marshal", "gc", "signal", "urllib", "http", "xmlrpc", "ftplib", "smtplib",
          "asyncio", "multiprocessing", "io", "pathlib"}  # reachable through allowed modules: uuid.os, typing.sys
STORE_NOTE = ("The tower's server escapes all text when it builds the page: store.py keeps text exactly as "
              "given. Never call html.escape or quote on it.\n")  # 7b (run 33): the escape hint made it escape twice

TEMPLATE = '''"""Web server written by the tower. Do not edit: write store.py (add(entry) and items())."""
import sys

HERE = sys.path.pop(0)  # the standard library first: a file named http.py or copy.py here must not replace it
import html  # noqa: E402
import os  # noqa: E402
import threading  # noqa: E402
import traceback  # noqa: E402
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer  # noqa: E402
from urllib.parse import parse_qs, urlparse  # noqa: E402

sys.path.insert(0, HERE)
import store  # noqa: E402

__CONFIG__
MAX_BODY = 100_000
LOCK = threading.Lock()  # one request at a time touches the store: a JSON-file store stays whole


def form_html():
    inputs = "".join('<p><label>' + html.escape(f) + ' <input name="' + html.escape(f) + '"></label></p>'
                     for f in FIELDS)
    return ('<form method="post" action="' + html.escape(ADD_PATH) + '">' + inputs
            + '<button type="submit">Add</button></form>')


def show(text):
    """User text escaped exactly once, however often store.py escaped it (7b, run 33)."""
    text = str(text)
    for _ in range(5):
        plain = html.unescape(text)
        if plain == text:
            break
        text = plain
    return html.escape(text)


def items_html():
    rows = []
    with LOCK:
        saved = store.items() or []
        saved = list(saved.values() if isinstance(saved, dict) else saved)
    for item in saved:
        if isinstance(item, dict):
            text = " - ".join(show(item.get(f, "")) for f in FIELDS)
        else:
            text = show(item)
        rows.append("<li>" + text + "</li>")
    return "<ul>" + "".join(rows) + "</ul>"


class Handler(BaseHTTPRequestHandler):
    timeout = 15  # a slow or lying client cannot hold a thread forever
    def send_page(self, status, body, location=None):
        data = ("<!doctype html><html><head><meta charset=\\"utf-8\\"><title>" + html.escape(TITLE)
                + "</title></head><body><h1>" + html.escape(TITLE) + "</h1>" + body + "</body></html>").encode("utf-8", "replace")
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
            with LOCK:
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
    keys = ", ".join(fields)[:60]
    return (f"no web code: add(entry) keeps a dict ({keys}) as given (no html.escape: the server escapes it) in memory, a "
            "module-level list, never files; items() returns them oldest first")[:200]


def page_text(title: str) -> str:
    """What F3 can expect on the tower's home page: the title, when HTML shows it unchanged."""
    return title if title and html.escape(title) == title else ""


def store_problems(ws: Workspace) -> list[str]:
    """7c: the store only keeps data — an import allowlist (review r2: a denylist was evaded by xmlrpc, os.system,
    exec, string-built imports), no dynamic code, no dunder attributes. The tower's server imports store.py."""
    out = []
    for name, safe in ((STORE, SAFE), (STORE_TESTS, SAFE_TESTS)):
        if name not in ws.files():
            continue
        try:
            tree = ast.parse(ws.read(name))
        except (SyntaxError, ValueError):
            continue  # the unit tests report it
        except (RecursionError, MemoryError):
            tree = None
        try:
            if tree is None:
                raise RecursionError
            out += _scan(name, safe, tree) + (_contract(tree) if name == STORE else [])
        except (RecursionError, MemoryError):  # 7d review r2: too deep to check is a problem, never a pass or a crash
            out.append(f"{name} is nested too deeply to check: keep it a short list and two plain functions")
    return out


def _scan(name: str, safe: set[str], tree: ast.Module) -> list[str]:
    """7c: imports, banned names and dunders, for one file; the first problem only, with its fix (8c, C-M1)."""
    test = name == STORE_TESTS
    allowed = f"import only {', '.join(sorted(safe - {'__future__'}))}"
    for node in ast.walk(tree):  # an accident guard, not a sandbox: Docker and the owner's read are that
        why, fix = "", "remove it"
        if isinstance(node, ast.Import):
            why, fix = next((f"imports {a.name}" for a in node.names if a.name.split(".")[0] not in safe), ""), allowed
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            bad = next((a.name for a in node.names if a.name == "*" or a.name.startswith("_") and mod != "__future__"
                        or a.name in DANGER - safe), "")
            why, fix = ((f"imports {'.' * node.level}{mod}", allowed) if node.level or mod.split(".")[0] not in safe
                        else (f"imports {bad} from {mod}" if bad else "",  # 8c r1: tests may use store._entries
                              f"import {mod} itself and use {mod}.{bad}" if test and bad.startswith("_")
                              else f"import {mod} itself and use its public names"))
        elif isinstance(node, ast.Attribute):  # private module aliases (collections._sys) reach sys: store.py only
            dunder, private = node.attr.startswith("__"), node.attr.startswith("_") and not test
            why = f"uses .{node.attr}" if (dunder or private or node.attr in BANNED - {"compile"}  # re.compile
                                           or node.attr in DANGER - safe) else ""
            fix = "rename it without the leading underscore" if private and not dunder else fix
        elif isinstance(node, ast.Name):
            n = node.id
            why = f"uses {n}" if n in BANNED or n.startswith("__") and n not in (
                "__name__", "__init__", "__all__", "__slots__", *(("__file__",) if test else ())) else ""
        if why:
            return [f"{name} {why}: {fix}" + ("" if test else f" ({name} only keeps data in memory)")]
    return []


def _contract(tree: ast.Module) -> list[str]:
    """7d (run 38: a list named items, the function get_items): the tower's server calls store.add(entry) and
    store.items(). Both must be plain module-level functions that take those arguments, and nothing rebinds them."""
    defs, rebound = {}, set()
    scoped = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)

    def bound(node) -> None:  # module-level bindings only: a function's or class's own names stay local (r1 M1)
        if isinstance(node, ast.comprehension):  # its target is comprehension-local; a walrus inside still binds
            rebound.update(w.target.id for w in ast.walk(node) if isinstance(w, ast.NamedExpr)
                           and w.target.id in ("add", "items"))
            return
        if isinstance(node, ast.AnnAssign) and node.value is None:  # 'items: list' binds nothing at runtime
            return
        names = ([node.id] if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del))
                 else [a.asname or a.name.split(".")[0] for a in node.names]
                 if isinstance(node, (ast.Import, ast.ImportFrom)) else
                 [node.name] if isinstance(node, (ast.ExceptHandler, ast.MatchAs, ast.MatchStar)) and node.name else [])
        rebound.update(n for n in names if n in ("add", "items"))
        for child in ast.iter_child_nodes(node):
            if not isinstance(child, scoped):
                bound(child)
            elif not isinstance(child, ast.Lambda):
                rebound.update({child.name} & {"add", "items"})
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name not in defs:
            defs[node.name] = node
        elif isinstance(node, scoped):  # a second def, an async def or a class of that name replaces the first
            rebound.update({node.name} & {"add", "items"})
        else:
            bound(node)
    rebound |= {n for g in ast.walk(tree) if isinstance(g, ast.Global) for n in g.names if n in ("add", "items")}
    out = []
    for fn, want, ok in (("add", "def add(entry): saves one entry",
                          lambda a, n, req: req <= 1 and (n >= 1 or a.vararg is not None)),
                         ("items", "def items(): returns the saved entries, oldest first",
                          lambda a, n, req: req == 0)):
        node = defs.get(fn)
        if node is not None and fn not in rebound:
            a = node.args
            n = len(a.posonlyargs) + len(a.args)
            required = n - len(a.defaults)
            if ok(a, n, required) and all(d is not None for d in a.kw_defaults):
                continue
        why = (f"'{fn}' is also assigned or imported: rename that" if fn in rebound
               else "it is missing" if node is None else "its arguments do not match")
        out.append(f"{STORE} must define {want} ({why}): the tower's server calls it")
    return out


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
    for path in ws.files():  # 7c review r1 I2: an earlier plan's AI-written files must not ship with the server
        if path not in (entry, STORE, STORE_TESTS):
            try:
                ws.delete(path)
            except WorkspaceError:  # review r2: a file the workspace refuses (todo.db) must not stop the job
                pass
    config = "\n".join(f"{k} = {v!r}" for k, v in (("TITLE", str(title).encode("utf-8", "replace").decode()[:100]), ("FIELDS", fields),
                       ("LIST_PAGE", page), ("FORM_PAGE", form_page), ("ADD_PATH", add)))
    ws.write(entry, TEMPLATE.replace("__CONFIG__", config))
    files = [{"path": entry, "purpose": "web server, written by the tower: do not change it"},
             {"path": STORE, "purpose": _store_purpose(fields)},
             {"path": STORE_TESTS, "purpose": "unittest tests: import store; call store.add(entry) and "
                                                     "store.items()"}]
    return {**plan, "files": files}, {entry} | SHADOWS
