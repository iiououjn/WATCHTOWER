"""Which files are the coder's tests, and do they test the app at all (8d: moved out of devfloor.py)."""
from __future__ import annotations

import ast
from fnmatch import fnmatch
from pathlib import PurePosixPath

from watchtower.engine.workspace import Workspace


def is_test_file(path: str) -> bool:
    """Exactly what the runner discovers: test*.py anywhere (_ensure_packages makes every folder a package)."""
    return fnmatch(PurePosixPath(path).name, "test*.py")


def _imported(node: ast.AST) -> list[str]:
    """Module names one node imports: import x, from x import y, importlib.import_module("x"), __import__("x")."""
    if isinstance(node, ast.Import):
        return [a.name for a in node.names]
    if isinstance(node, ast.ImportFrom):
        return [node.module or ""]
    if (isinstance(node, ast.Call) and node.args and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
            and getattr(node.func, "attr", getattr(node.func, "id", "")) in ("import_module", "__import__")):
        return [node.args[0].value]
    return []


def app_is_tested(ws: Workspace) -> bool:
    """At least one test file imports a module of the app itself (not only unittest or another test file):
    a test that never touches the app proves nothing."""
    py = [f for f in ws.files() if f.endswith(".py")]
    tests = [f for f in py if is_test_file(f)]
    app = {PurePosixPath(f).with_suffix("").as_posix().replace("/", ".") for f in py
           if f not in tests and PurePosixPath(f).stem not in ("__init__", "conftest")
           and not {"tests", "test"} & set(PurePosixPath(f).parts[:-1])}  # helpers in tests/ are not the app
    app |= {m.split(".")[0] for m in app}  # 'import store' counts for store/db.py
    for name in tests:
        try:
            tree = ast.parse(ws.read(name))
        except (SyntaxError, ValueError, RecursionError, MemoryError):
            continue
        if any(m in app for node in ast.walk(tree) for m in _imported(node)):
            return True
    return False
