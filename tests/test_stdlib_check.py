
from watchtower.floors.f2_dev.stdlib_check import import_problems
from watchtower.engine.workspace import Workspace


def ws_with(tmp_path, files):
    ws = Workspace(tmp_path)
    for name, body in files.items():
        ws.write(name, body)
    return ws


def test_stdlib_and_local_modules_are_fine(tmp_path):
    ws = ws_with(tmp_path, {"app.py": "import json, sqlite3\nfrom http.server import HTTPServer\nimport store\n",
                            "store.py": "import os\n", "pkg/util.py": "x = 1\n", "main.py": "from pkg import util\n"})
    assert import_problems(ws) == []


def test_third_party_imports_flagged(tmp_path):
    ws = ws_with(tmp_path, {"app.py": "import requests\nfrom flask import Flask\n"})
    assert import_problems(ws) == ["app.py imports flask (not in the Python standard library)",
                                   "app.py imports requests (not in the Python standard library)"]


def test_syntax_errors_reported(tmp_path):
    ws = ws_with(tmp_path, {"app.py": "def broken(:\n"})
    assert import_problems(ws)[0].startswith("app.py has a syntax error")


def test_relative_imports_ok(tmp_path):
    ws = ws_with(tmp_path, {"pkg/a.py": "from . import b\nfrom .b import x\n", "pkg/b.py": "x = 1\n"})
    assert import_problems(ws) == []


def test_parens_too_deep_is_reported(tmp_path):
    ws = ws_with(tmp_path, {"app.py": "x = " + "(" * 2000 + "1" + ")" * 2000 + "\n"})
    assert import_problems(ws)[0].startswith("app.py ")


def test_parser_recursion_is_reported_not_crash(tmp_path, monkeypatch):
    from watchtower.floors.f2_dev import stdlib_check

    def boom(source):
        raise RecursionError("maximum recursion depth exceeded")

    ws = ws_with(tmp_path, {"app.py": "x = 1\n"})
    monkeypatch.setattr(stdlib_check.ast, "parse", boom)
    assert import_problems(ws) == ["app.py could not be parsed (RecursionError); simplify it"]


def test_modules_removed_in_313_are_flagged_on_any_tower_python(tmp_path):  # 8c (C-M4): the sandbox runs 3.14
    ws = ws_with(tmp_path, {"app.py": "import cgi\nfrom telnetlib import Telnet\nimport json\n"})
    problems = import_problems(ws)
    assert len(problems) == 2 and all("removed in Python 3.13" in p for p in problems), problems
    assert "parse_qs" in next(p for p in problems if "cgi" in p)
    ws = ws_with(tmp_path, {"app.py": "import cgi\n", "cgi.py": "x = 1\n"})  # its own cgi.py is the app's
    assert import_problems(ws) == []


def test_modules_added_since_the_tower_s_python_are_fine(tmp_path):  # 8c review r1: the sandbox runs 3.14
    ws = ws_with(tmp_path, {"app.py": "import annotationlib\nfrom compression import zstd\n"})
    assert import_problems(ws) == []
