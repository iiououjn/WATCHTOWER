from __future__ import annotations

import ast
import sys
from pathlib import PurePosixPath

from watchtower.engine.workspace import Workspace


def import_problems(ws: Workspace) -> list[str]:
    """The sandbox has no network, so apps may import only the standard library and their own modules."""
    files = ws.files()
    local = {PurePosixPath(f).parts[0].removesuffix(".py") for f in files if f.endswith(".py")}
    problems = []
    for name in files:
        if not name.endswith(".py"):
            continue
        try:
            tree = ast.parse(ws.read(name))
        except SyntaxError as e:
            problems.append(f"{name} has a syntax error on line {e.lineno}: {e.msg}")
            continue
        modules = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                modules.add(node.module.split(".")[0])
        for mod in sorted(modules - set(sys.stdlib_module_names) - local):
            problems.append(f"{name} imports {mod} (not in the Python standard library)")
    return problems
