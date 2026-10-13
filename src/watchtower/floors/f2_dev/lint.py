from __future__ import annotations

import ast
import warnings

from watchtower.engine.workspace import Workspace, WorkspaceError

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
