from __future__ import annotations

import ast
import builtins
import io
import keyword
import sys
import tokenize
import warnings

# The allow-listed modules, loaded once with the tower itself, so the attribute check below only reads
# sys.modules: nothing is imported (or searched for on disk, where a workspace file could shadow it) at repair time.
import datetime, html, html.parser, http.client, http.cookies, http.server, json, math, os, random  # noqa: E401,F401,I001
import re, shutil, sqlite3, tempfile, time, unittest, unittest.mock, urllib.error, urllib.parse  # noqa: E401,F401,I001
import urllib.request, uuid  # noqa: E401,F401,I001

MAX_REPAIRS, MAX_SPAN, MAX_REPAIR_BYTES = 6, 4, 100_000
_AFTER_CLOSE = set(")]},:+.% \t\r")


def _stands_alone(line: str) -> bool:
    """A line that tokenizes cleanly on its own (`bg = "#000"`, a comment) is a normal line, never the tail of
    a string split by a lost line break — a real tail (`world")`) leaves a quote open and cannot."""
    try:
        for tok in tokenize.generate_tokens(io.StringIO(line.strip() + "\n").readline):
            if tok.type == tokenize.ERRORTOKEN:
                return False
        return True
    except (tokenize.TokenError, SyntaxError):
        return False


def _syntax_error(text: str):
    """compile() quietly: the SyntaxError, None when it compiles, or False when compile itself gives up."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # invalid escapes etc. must not spam the tower's stderr
        try:
            compile(text, "<coder>", "exec", dont_inherit=True)
            return None
        except SyntaxError as e:
            return e
        except (ValueError, RecursionError, MemoryError):
            return False


def _close_at(line: str, quote: str) -> int:
    i = 0
    while i < len(line):
        if line[i] == "\\":
            i += 2
            continue
        if line[i] == quote:
            return i
        i += 1
    return -1


def repair_strings(source: str) -> tuple[str, list[int]]:
    """Undo the coder's most common JSON slip: '\\n' (or '\\r\\n') sent as a real line break, which splits a
    one-line string ('unterminated string literal'). A join is kept only when the string's own quote closes on a
    following line and is followed by what normally follows a string — ')', ',', ':', end of line … — never by
    another quote or a word; and the error must then move past that line. A truly missing quote is left alone."""
    if len(source) > MAX_REPAIR_BYTES:
        return source, []
    text, fixed, removed = source, [], 0
    for _ in range(MAX_REPAIRS):
        err = _syntax_error(text)
        if not err or not (err.lineno and err.offset and "unterminated" in err.msg and "string" in err.msg
                           and "triple" not in err.msg):
            break
        lines = text.split("\n")
        at = err.lineno - 1
        quote = next((c for c in lines[at][err.offset - 1:] if c in "'\""), None) if at < len(lines) else None
        if quote is None:
            break
        joined, used = lines[at], 0
        for k in range(1, MAX_SPAN + 1):
            if at + k >= len(lines):
                break
            crlf = joined.endswith("\r")
            joined = joined[:-1] + "\\r\\n" if crlf else joined + "\\n"
            nxt, close = lines[at + k], _close_at(lines[at + k], quote)
            joined += nxt
            if close >= 0:
                rest = nxt[close + 1:]
                used = k if (not rest or rest[0] in _AFTER_CLOSE) and not _stands_alone(nxt) else 0
                break
        if not used:
            break
        candidate = "\n".join(lines[:at] + [joined] + lines[at + used + 1:])
        after = _syntax_error(candidate)
        if after is False or (after is not None and (not after.lineno or after.lineno <= err.lineno)):
            break
        text = candidate
        fixed.append(err.lineno + removed)  # the line number in the coder's own file
        removed += used
    return text, fixed


# Modules small apps really use. A name like `code`, `string` or `types` is more often a variable the coder forgot
# to set: importing the module there would turn a clear NameError into a confusing AttributeError.
IMPORTABLE = {"os", "sys", "json", "re", "time", "datetime", "html", "sqlite3", "random", "math", "tempfile",
              "shutil", "uuid", "unittest", "io"}
SUBMODULES = {"urllib": {"parse", "request", "error"}, "http": {"server", "client", "cookies"},
              "unittest": {"mock"}, "html": {"parser"}}


# Bare names the coder uses without importing (run 26: parse_qs, NameError in 4 attempts). Only names whose
# meaning is unambiguous in a small stdlib web app.
BARE = {"parse_qs": "urllib.parse", "parse_qsl": "urllib.parse", "urlparse": "urllib.parse", "escape": "html",
        "HTTPServer": "http.server", "ThreadingHTTPServer": "http.server",
        "BaseHTTPRequestHandler": "http.server"}


def _has(module: str, attr: str) -> bool:
    """Does the stdlib module (loaded above) have this attribute? `datetime.now()` means the class, not the module:
    no import there. Submodules a bare import does not load (html.parser, unittest.mock …) are in SUBMODULES and
    handled first; the rest (os.path, json.decoder) come with the package."""
    mod = sys.modules.get(module)
    return mod is not None and hasattr(mod, attr)


def _bound(tree: ast.AST) -> tuple[set[str], set[str], set[str]] | None:
    """Every name the file binds anywhere, the packages bound only by a plain `import pkg…`, and the dotted
    modules it imports (None after a star import: anything may be bound)."""
    names: set[str] = set()
    plain: set[str] = set()
    dotted: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for a in node.names:
                if a.name == "*":
                    return None
                names.add(a.asname or a.name.split(".")[0])
                if isinstance(node, ast.Import) and not a.asname:
                    plain.add(a.name.split(".")[0])
                    dotted.add(a.name)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    dotted.add(f"{node.module}.{a.name}")  # from unittest import mock: unittest.mock is loaded
        elif isinstance(node, ast.Name) and not isinstance(node.ctx, ast.Load):
            names.add(node.id)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.arg):
            names.add(node.arg)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            names.add(node.name)
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            names.update(node.names)
        elif isinstance(node, (ast.MatchAs, ast.MatchStar)) and node.name:
            names.add(node.name)
    return names, {p for p in plain if p in names}, dotted


def repair_imports(source: str, skip: frozenset[str] = frozenset(),
                   allowed: frozenset[str] | None = None) -> tuple[str, list[str]]:
    """Add a missing standard import the coder used as `os.path…` but never imported (bound nowhere in the file).
    Static only: the file is parsed, never run. Returns the new text and the modules added. `skip`: bare names a sibling file defines (6x review r2: a
    stdlib import must not hide `from util import escape`, which repair_names adds). `allowed`: the only top-level
    modules it may add (8c, C-H2: the skeleton's store check rejected the `import os` the repair had added)."""
    if len(source) > MAX_REPAIR_BYTES:
        return source, []
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            tree = ast.parse(source)
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        return source, []
    found = _bound(tree)
    if found is None:
        return source, []
    bound, plain, dotted = found
    wanted: set[str] = set()
    poisoned: set[str] = set()
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)):
            continue
        name, attr = node.value.id, node.attr
        if attr in SUBMODULES.get(name, ()) and (name not in bound or name in plain):
            if f"{name}.{attr}" not in dotted:  # import unittest, then unittest.mock.patch: mock is not loaded
                wanted.add(f"{name}.{attr}")
            continue
        if name in bound or name not in IMPORTABLE:
            continue
        if _has(name, attr):
            wanted.add(name)
        else:
            poisoned.add(name)  # a use that is not this module (datetime.now): no import of it, the rest still repaired
    wanted = {m for m in wanted - poisoned if allowed is None or m.split(".")[0] in allowed}
    used = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)}
    by_module: dict[str, list[str]] = {}
    for name in sorted(n for n in used & set(BARE) - bound - skip
                       if allowed is None or BARE[n].split(".")[0] in allowed):
        by_module.setdefault(BARE[name], []).append(name)
    froms = [f"from {m} import {', '.join(names)}" for m, names in sorted(by_module.items())]
    if not wanted and not froms:
        return source, []
    added = sorted(wanted) + froms
    return _insert(source, tree, [f"import {m}" for m in sorted(wanted)] + froms), added


def _insert(source: str, tree: ast.Module, new: list[str]) -> str:
    """Add lines after a module docstring and any __future__ imports, keeping the file's line breaks."""
    after = 0
    head = source.splitlines()[:2]
    if head and head[0].startswith("#!"):  # a shebang and a coding cookie must stay on lines 1-2
        after = 1
    if len(head) > after and head[after].lstrip().startswith("#") and "coding" in head[after]:
        after += 1
    for stmt in tree.body:
        if (isinstance(stmt, ast.ImportFrom) and stmt.module == "__future__") or (
                stmt is tree.body[0] and isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant)
                and isinstance(stmt.value.value, str)):
            after = stmt.end_lineno
        else:
            break
    eol = "\r\n" if "\r\n" in source else "\n"
    lines = io.StringIO(source, newline="").readlines()  # \n, \r\n, \r only: the line breaks ast counts
    if after and lines and not lines[after - 1].endswith(("\n", "\r")):
        lines[after - 1] += eol
    lines[after:after] = [f"{line}{eol}" for line in new]
    return "".join(lines)


_DECLARE = (ast.Import, ast.ImportFrom, ast.Assign, ast.AnnAssign, ast.FunctionDef, ast.AsyncFunctionDef,
            ast.ClassDef, ast.Pass)


def _no_required_args(fn: ast.FunctionDef) -> bool:
    a = fn.args
    positional = a.posonlyargs + a.args
    return len(a.defaults) == len(positional) and all(d is not None for d in a.kw_defaults)


def _calls(fn: ast.FunctionDef) -> set[str]:
    """Every name the function reads: a call, or a function passed on (Thread(target=run)) both count."""
    return {n.id for n in ast.walk(fn) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)}


def repair_main(source: str) -> tuple[str, str | None]:
    """Run 10: an entry file that defines run() (which calls serve_forever()) but never calls it exits at once.
    Add `if __name__ == "__main__": root()` only when nothing at top level runs code, exactly one top-level
    function calls .serve_forever(), and exactly one top-level function callable with no arguments reaches it
    through direct calls while nothing else calls it (main() → init_db(); run() starts main). Else: alone."""
    if len(source.encode("utf-8", "replace")) > MAX_REPAIR_BYTES:
        return source, None
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            tree = ast.parse(source)
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        return source, None
    body = tree.body[1:] if ast.get_docstring(tree, clean=False) is not None else tree.body
    if not all(isinstance(node, _DECLARE) for node in body):
        return source, None  # a top-level call, loop, if (a __main__ block), with or try: it may already start
    names = [t.id for node in body if isinstance(node, (ast.Assign, ast.AnnAssign))
             for t in (node.targets if isinstance(node, ast.Assign) else [node.target]) for t in ast.walk(t)
             if isinstance(t, ast.Name)]
    names += [node.name for node in body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))]
    names += [(a.asname or a.name).split(".")[0] for node in body if isinstance(node, (ast.Import, ast.ImportFrom))
              for a in node.names]  # from helpers import run: a second run
    fns = {node.name: node for node in body if isinstance(node, ast.FunctionDef) and names.count(node.name) == 1}
    serving = [name for name, fn in fns.items() if any(isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                                                      and n.func.attr == "serve_forever" for n in ast.walk(fn))]
    if len(serving) != 1:
        return source, None
    calls = {name: _calls(fn) & set(fns) for name, fn in fns.items()}

    def reaches(name: str) -> bool:  # breadth-first: linear in the call graph, cycles end it
        seen, todo = {name}, [name]
        while todo:
            current = todo.pop()
            if current == serving[0]:
                return True
            todo += [c for c in calls[current] - seen]
            seen |= calls[current]
        return False
    called = set().union(*calls.values())
    roots = [name for name in fns if name not in called and _no_required_args(fns[name]) and reaches(name)]
    if len(roots) != 1:
        return source, None
    name = roots[0]
    nl = "\r\n" if "\r\n" in source else "\n"
    text = source.rstrip("\r\n") + f'{nl}{nl}{nl}if __name__ == "__main__":{nl}    {name}(){nl}'
    if len(text.encode("utf-8", "replace")) > MAX_REPAIR_BYTES:  # never grow a file past what Workspace takes
        return source, None
    return text, name


def sibling_names(ws, path: str) -> frozenset[str]:
    """Top-level functions and classes the other workspace .py files define: BARE names among them are the
    coder's own, never the stdlib's."""
    out: set[str] = set()
    for f in ws.files():
        if f.endswith(".py") and f != path:
            tree = _parse(ws.read(f))
            if tree is not None:
                out |= _top_names(tree)
    return frozenset(out)


def _top_names(tree: ast.Module) -> set[str]:
    """Functions and classes a module defines at top level. Not variables: `from todo import items` would be a
    copy that goes stale when todo rebinds it."""
    return {node.name for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))}


_SERVES = re.compile(r"serve|server", re.I)


def _quiet(tree: ast.Module) -> bool:
    """Importing this module does nothing but define things: no top-level call that serves or runs, no loop,
    no harness. A `__main__` block is fine (it does not run on import)."""
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef,
                             ast.Pass)):
            continue
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
            continue  # a docstring or a bare constant
        if isinstance(node, ast.If) and isinstance(node.test, ast.Compare) and \
                ast.unparse(node.test).replace("'", '"') == '__name__ == "__main__"':
            continue
        if isinstance(node, (ast.Assign, ast.AnnAssign)) and not any(
                isinstance(n, ast.Call) and _SERVES.search(ast.unparse(n.func))
                for n in ast.walk(node.value if node.value is not None else ast.Pass())):
            continue  # PORT = int(os.getenv(...)) is fine; httpd = HTTPServer(...) binds the port
        return False
    return True


def _parse(source: str) -> ast.Module | None:
    if len(source) > MAX_REPAIR_BYTES:
        return None
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            return ast.parse(source)
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        return None


def repair_names(source: str, module: str, siblings: dict[str, str]) -> tuple[str, list[str]]:
    """Run 11: __main__.py called list_items() and add_item() from todo.py but never imported them. For every
    name the file uses but binds nowhere (and is not a builtin), import it from the one sibling module that
    defines it at top level. Any name with no owner or two owners, a star import, a sibling that imports this
    module back or shadows the standard library: the file is left alone. Static only."""
    tree = _parse(source)
    found = _bound(tree) if tree is not None else None
    if found is None:
        return source, []
    bound = found[0] | set(dir(builtins)) | {"__file__", "__builtins__"}
    missing = sorted({n.id for n in ast.walk(tree) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)}
                     - bound)
    if not missing:
        return source, []
    owners: dict[str, list[str]] = {}
    for name, text in sorted(siblings.items()):
        if (name == module or not name.isidentifier() or keyword.iskeyword(name) or name.startswith("test")
                or name == "__main__"
                or name in sys.stdlib_module_names):
            continue
        other = _parse(text)
        if other is None or not _quiet(other):
            continue  # importing it would bind a port, serve, or run a harness: never link it
        imports_back = any(isinstance(n, ast.Import) and any(a.name.split(".")[0] == module for a in n.names)
                           or isinstance(n, ast.ImportFrom) and (n.module or "").split(".")[0] == module
                           for n in ast.walk(other))
        for defined in _top_names(other) & set(missing):
            owners.setdefault(defined, []).append("" if imports_back else name)
    wanted: dict[str, list[str]] = {}
    for name in missing:
        if len(owners.get(name, [])) != 1 or not owners[name][0]:
            return source, []  # no owner, two owners, or an owner that would import this module back
        wanted.setdefault(owners[name][0], []).append(name)
    added = [f"from {mod} import {', '.join(names)}" for mod, names in sorted(wanted.items())]
    return _insert(source, tree, added), added
