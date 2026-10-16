from __future__ import annotations

import ast
import sys
from pathlib import PurePosixPath

from watchtower.engine.workspace import Workspace

# 8c (C-M4): PEP 594 and lib2to3, gone since Python 3.13. The sandbox runs 3.14 whatever Python the tower has
# (3.12 still lists cgi in sys.stdlib_module_names), so they are named here, not read from this interpreter.
REMOVED_313 = {"aifc", "audioop", "cgi", "cgitb", "chunk", "crypt", "imghdr", "lib2to3", "mailcap", "msilib", "nis",
               "nntplib", "ossaudiodev", "pipes", "sndhdr", "spwd", "sunau", "telnetlib", "uu", "xdrlib"}
INSTEAD = {"cgi": "use urllib.parse.parse_qs", "cgitb": "use traceback", "pipes": "use shlex.quote",
           "imghdr": "check the file's first bytes"}


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
        except (RecursionError, MemoryError, ValueError, OSError) as e:
            problems.append(f"{name} could not be parsed ({type(e).__name__}); simplify it")
            continue
        modules = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                modules.add(node.module.split(".")[0])
        for mod in sorted(modules - local):
            if mod in REMOVED_313:
                problems.append(f"{name} imports {mod} (removed in Python 3.13; the sandbox runs 3.14): "
                                + INSTEAD.get(mod, "use another standard module"))
            elif mod not in sys.stdlib_module_names:
                problems.append(f"{name} imports {mod} (not in the Python standard library)")
    return problems
