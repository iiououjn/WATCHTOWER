from watchtower.engine.stdlib_check import import_problems
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
