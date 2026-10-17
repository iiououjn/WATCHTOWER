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

        def reach(m: str, calls=calls) -> set[str]:  # the method and every method it calls on self, transitively
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


_CONTAINERS = {"list", "dict", "set", "defaultdict", "OrderedDict", "Counter", "deque"}


def _top_bound(tree: ast.Module, containers: bool = False) -> set[str]:
    """Names the module binds itself at top level (imports are not its own). containers=True: only names bound to
    a list/dict/set — the app state a test resets, and the only kind `.clear()` fits."""
    out: set[str] = set()
    for n in tree.body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and not containers:
            out.add(n.name)
        elif isinstance(n, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            value = getattr(n, "value", None)
            if containers and not (isinstance(value, (ast.List, ast.Dict, ast.Set)) or isinstance(value, ast.Call)
                                   and ast.unparse(value.func).split(".")[-1] in _CONTAINERS):
                continue
            for t in n.targets if isinstance(n, ast.Assign) else [n.target]:  # app.config = {} binds no name
                out |= {x.id for x in ast.walk(t) if isinstance(x, ast.Name) and isinstance(x.ctx, ast.Store)}
    return out


def _scope(fn: ast.AST):
    """The nodes of one function's own scope: nested functions and classes are their own scopes."""
    todo = list(ast.iter_child_nodes(fn))
    while todo:
        node = todo.pop()
        yield node
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            todo.extend(ast.iter_child_nodes(node))


def _global_resets(tree: ast.Module, apps: dict[str, set[str]]) -> list[tuple[str, str]]:
    """Run 16: setUp did `global todos; todos = []` after `from todo import ...`: that binds a new todos in the
    test module; todo.todos is never reset. (name, module) pairs: the test does not bind the name itself, a module
    it imports binds it to a container, and the function never touches module.name (aliasing that works)."""
    own = _top_bound(tree)
    sources = [n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module and not n.level]
    sources += [a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names]
    out = []
    for fn in (n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))):
        nodes = list(_scope(fn))
        declared = {g for n in nodes if isinstance(n, ast.Global) for g in n.names}
        assigned = {n.id for n in nodes if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store)}
        touched = {ast.unparse(n) for n in nodes if isinstance(n, ast.Attribute)}  # app.models.todos too
        for name in sorted((declared & assigned) - own):
            mod = next((m for m in sources if name in apps.get(m, set())), None)
            if mod and f"{mod}.{name}" not in touched and (name, mod) not in out:
                out.append((name, mod))
    return out


def idiom_notes(ws: Workspace) -> list[str]:
    """Run 15: pytest idioms that silently did nothing. Test functions that take arguments (pytest fixtures such as
    `client`) never ran; a test that patches the very function it imported and calls tests nothing (the real one
    runs). Non-blocking notes, at most 2, each within 200 chars."""
    fixtures, self_patch, resets = [], [], []
    trees: dict[str, ast.Module] = {}
    for name in ws.files():
        if not name.endswith(".py"):
            continue
        try:
            source = ws.read(name)
            if len(source) <= MAX_LINT_BYTES:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    trees[name] = ast.parse(source)
        except (SyntaxError, ValueError, RecursionError, MemoryError, OSError, WorkspaceError):
            continue
    apps = {n[:-3].replace("/", ".").removesuffix(".__init__"): _top_bound(t, containers=True) for n, t in trees.items()
            if not n.rsplit("/", 1)[-1].startswith("test")}
    for name, tree in trees.items():
        if name.rsplit("/", 1)[-1].startswith("test"):
            resets += [(name[:-3].replace("/", "."), g, m) for g, m in _global_resets(tree, apps)]
            f, p = _test_file_notes(tree)
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
    if resets:
        said = [f"Test `global {var}` binds its own copy; {mod}.{var} stays dirty. In setUp: `import {mod}`; "
                f"`{mod}.{var}.clear()`." for _, var, mod in resets]
        notes += [n for n in said if len(n) <= 200][:1]  # names are never cut (a cut name is wrong code)
    return [n[:200] for n in notes]
