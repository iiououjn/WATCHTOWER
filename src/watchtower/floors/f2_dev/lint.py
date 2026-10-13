from __future__ import annotations

import ast
import re
import warnings

from watchtower.engine.workspace import Workspace, WorkspaceError

_PLAIN = re.compile(r"[A-Za-z_][\w.]{0,80}")
_MUTATORS = {"append", "extend", "insert", "update", "add", "setdefault", "pop", "remove", "clear", "discard"}
MAX_LINT_BYTES = 100_000


def _self_attr(node: ast.AST) -> str | None:
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "self":
        return node.attr
    return None


def _writes(fn: ast.FunctionDef) -> tuple[set[str], set[str]]:
    """(rebinds, in-place changes) of self attributes inside one method."""
    rebinds, changes = set(), set()
    for n in ast.walk(fn):
        if isinstance(n, (ast.Assign, ast.AugAssign, ast.AnnAssign)):
            for t in n.targets if isinstance(n, ast.Assign) else [n.target]:
                for part in ast.walk(t):
                    name = _self_attr(part)
                    if name and isinstance(part.ctx, ast.Store):
                        (changes if isinstance(n, ast.AugAssign) else rebinds).add(name)
                    elif isinstance(part, ast.Subscript) and isinstance(part.ctx, ast.Store):
                        name = _self_attr(part.value)
                        if name:
                            changes.add(name)
        elif isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr in _MUTATORS:
            name = _self_attr(n.func.value)
            if name:
                changes.add(name)
    return rebinds, changes


def _reads(fn: ast.FunctionDef) -> set[str]:
    return {n.attr for n in ast.walk(fn) if _self_attr(n) and isinstance(n.ctx, ast.Load)}


# set by http.server for every request: never data the app keeps
_PER_REQUEST = {"path", "headers", "command", "request_version", "requestline", "raw_requestline", "close_connection",
                "protocol_version", "rfile", "wfile", "connection", "request", "client_address", "server"}


def _self_calls(fn: ast.FunctionDef) -> set[str]:
    return {n.func.attr for n in ast.walk(fn) if isinstance(n, ast.Call) and _self_attr(n.func)}


def _handler_problems(name: str, tree: ast.Module) -> list[str]:
    out = []
    for cls in (n for n in tree.body if isinstance(n, ast.ClassDef)):
        if not any(ast.unparse(b).endswith("RequestHandler") for b in cls.bases):
            continue
        shared = {t.id for n in cls.body if isinstance(n, (ast.Assign, ast.AnnAssign))
                  for t in (n.targets if isinstance(n, ast.Assign) else [n.target]) if isinstance(t, ast.Name)}
        methods = {n.name: n for n in cls.body if isinstance(n, ast.FunctionDef)}

        calls = {m: _self_calls(fn) & set(methods) for m, fn in methods.items()}
        own = {m: _writes(fn) for m, fn in methods.items()}
        read = {m: _reads(fn) for m, fn in methods.items()}

        def reach(m: str) -> set[str]:  # the method and every method it calls on self, transitively
            seen, todo = {m}, [m]
            while todo:
                for c in calls[todo.pop()] - seen:
                    seen.add(c)
                    todo.append(c)
            return seen - {"__init__"}
        handlers = [m for m in methods if m.startswith("do_")]
        reaches = {m: reach(m) for m in handlers}  # computed once: a big class stays fast
        rebinds = {m: set().union(*(own[x][0] for x in reaches[m])) for m in handlers}
        changes = {m: set().union(*(own[x][1] for x in reaches[m])) for m in handlers}
        rebound = (own["__init__"][0] if "__init__" in own else set()).union(*rebinds.values())
        changed_in_place = set().union(*changes.values())
        lost = set()
        for w in handlers:
            for attr in (rebinds[w] | changes[w]) - _PER_REQUEST:
                if attr in shared and attr not in rebound:
                    continue  # a class-level list changed in place: shared by every handler, it lives on
                for r in handlers:
                    if r == w or r in reaches[w] or attr in rebinds[r] | changes[r]:
                        continue  # same request (do_POST → self.do_GET()), or r sets it itself first
                    readers = {x for x in reaches[r] if attr in read[x]}
                    if not readers:
                        continue
                    if attr not in changed_in_place and readers <= reaches[w]:
                        continue  # a per-request override (self.status = 201) read by a helper both call
                    lost.add((attr, w))
        for attr, m in sorted(lost)[:2]:
            out.append(f"{name[-25:]}: {cls.name[:20]}.{m[:12]} keeps self.{attr[:18]}, but each request gets a new "
                       "handler, so it is lost. Keep it at module level (outside the class) or in a file.")
    return out


def handler_state_problems(ws: Workspace) -> list[str]:
    """Run 12: the todo list lived on the request handler (self.todo_list), so every item vanished between
    requests. Static: a self attribute one do_* method writes and a different do_* method reads."""
    problems = []
    for name in ws.files():
        if not name.endswith(".py"):
            continue
        try:
            source = ws.read(name)
            if len(source) > MAX_LINT_BYTES:
                continue
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                tree = ast.parse(source)
        except (SyntaxError, ValueError, RecursionError, MemoryError, OSError, WorkspaceError):
            continue  # syntax errors are import_problems' to report
        problems += _handler_problems(name, tree)
    return problems[:3]


def _required_args(fn: ast.FunctionDef) -> bool:
    a = fn.args
    return len(a.posonlyargs + a.args) > len(a.defaults) or any(d is None for d in a.kw_defaults)


def _patched(fn: ast.FunctionDef) -> list[str]:
    """Targets of @patch('mod.name') / @mock.patch('mod.name') on this function."""
    out = []
    for d in fn.decorator_list:
        if (isinstance(d, ast.Call) and ast.unparse(d.func).split(".")[-1] == "patch" and d.args
                and isinstance(d.args[0], ast.Constant) and isinstance(d.args[0].value, str)
                and _PLAIN.fullmatch(d.args[0].value)):
            out.append(d.args[0].value)
    return out


def _decorated(fn: ast.FunctionDef, aliases: set[str]) -> bool:
    """Any patch (patch.object, `patch as mp`) or fixture decorator: something else supplies the arguments."""
    words = ("patch", "fixture", "mock", *aliases)
    return any(w in ast.unparse(d) for d in fn.decorator_list for w in words)


def _test_file_notes(tree: ast.Module) -> tuple[list[str], list[tuple[str, str]]]:
    called = {n.func.id for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    imported = {a.asname or a.name: f"{n.module}.{a.name}" for n in tree.body if isinstance(n, ast.ImportFrom)
                and n.module for a in n.names}
    aliases = {a.asname for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) for a in n.names
               if a.asname and a.name in ("patch", "fixture")}
    fixtures, self_patch = [], []
    for fn in (n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name.startswith("test")):
        if _required_args(fn) and not _decorated(fn, aliases) and fn.name not in called:
            fixtures.append(fn.name)  # a pytest fixture argument: nothing supplies it here, so it never ran
        calls = {n.func.id for n in ast.walk(fn) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
        for target in _patched(fn):
            name = target.rsplit(".", 1)[-1]
            if imported.get(name) == target and name in calls:
                self_patch.append((fn.name, target))
    return fixtures, self_patch


def idiom_notes(ws: Workspace) -> list[str]:
    """Run 15: pytest idioms that silently did nothing. Test functions that take arguments (pytest fixtures such as
    `client`) never ran; a test that patches the very function it imported and calls tests nothing (the real one
    runs). Non-blocking notes, at most 2, each within 200 chars."""
    fixtures, self_patch = [], []
    for name in ws.files():
        if not (name.endswith(".py") and name.rsplit("/", 1)[-1].startswith("test")):
            continue
        try:
            source = ws.read(name)
            if len(source) > MAX_LINT_BYTES:
                continue
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                f, p = _test_file_notes(ast.parse(source))
        except (SyntaxError, ValueError, RecursionError, MemoryError, OSError, WorkspaceError):
            continue
        fixtures += f
        self_patch += p
    notes = []
    if fixtures:
        names = ", ".join(sorted(set(fixtures)))[:70]
        notes.append(f"These tests take arguments, so they never ran (no pytest fixtures such as `client` here): "
                     f"{names}. Make them take no arguments.")
    if self_patch:
        test, target = self_patch[0]
        notes.append(f"{test[:25]} patches {target[:25]} but calls its own imported copy, so the real function runs "
                     "and the mock is never called. Test the real function's result; don't patch it.")
    return [n[:200] for n in notes]
