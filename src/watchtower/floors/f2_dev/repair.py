from __future__ import annotations

import ast
import io
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


def repair_imports(source: str) -> tuple[str, list[str]]:
    """Add a missing standard import the coder used as `os.path…` but never imported (bound nowhere in the file).
    Static only: the file is parsed, never run. Returns the new text and the modules added."""
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
            return source, []  # a use that is not this module (datetime.now): leave the file alone
    if not wanted:
        return source, []
    after = 0  # insert after a module docstring and any __future__ imports
    for stmt in tree.body:
        if (isinstance(stmt, ast.ImportFrom) and stmt.module == "__future__") or (
                stmt is tree.body[0] and isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant)
                and isinstance(stmt.value.value, str)):
            after = stmt.end_lineno
        else:
            break
    added = sorted(wanted)
    eol = "\r\n" if "\r\n" in source else "\n"
    lines = io.StringIO(source, newline="").readlines()  # \n, \r\n, \r only: the line breaks ast counts
    if after and lines and not lines[after - 1].endswith(("\n", "\r")):
        lines[after - 1] += eol
    lines[after:after] = [f"import {m}{eol}" for m in added]
    return "".join(lines), added
