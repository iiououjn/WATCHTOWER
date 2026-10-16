"""Shared helpers and fixtures for test_devfloor*.py (split from one file to stay under 500 lines)."""
import pytest

from watchtower.floors.f2_dev.devfloor import TEST_COMMAND, DevFloor

from watchtower.engine.sandbox import SandboxResult

from watchtower.engine.workspace import Workspace

from watchtower.roles import Role

ARCH = Role("f2.architect", "Architect", "f2", "work", "a")

CODER = Role("f2.coder", "Coder", "f2", "work", "c")

SPEC = {"title": "Todo", "goal": "todo app", "acceptance": ["lists todos"], "out_of_scope": []}

APP = {"path": "app.py", "content": "import json\nprint('app')\n"}

TEST = {"path": "test_app.py", "content": "import unittest\nimport app\n"}

class Script:
    def __init__(self, replies):
        self.replies = {k: list(v) for k, v in replies.items()}
        self.prompts = {k: [] for k in replies}

    def __call__(self, role, prompt):
        self.prompts[role.id].append(prompt)
        q = self.replies[role.id]
        return q.pop(0) if len(q) > 1 else q[0]

class Runner:
    def __init__(self, results):
        self.results, self.calls = list(results), []

    def __call__(self, cmd):
        self.calls.append(cmd)
        return self.results.pop(0) if len(self.results) > 1 else self.results[0]

OK = SandboxResult(0, 'WATCHTOWER_TESTS {"run": 2, "skipped": 0, "failures": 0, "errors": 0}\n', "", False)

FAIL = SandboxResult(1, "", "AssertionError: expected 3 got 2\nFAILED (failures=1)\n", False)

def dev(tmp_path, script, runner, rounds=4):
    return DevFloor(ARCH, CODER, ask=script, workspace=Workspace(tmp_path), run=runner, max_rounds=rounds)

def verdict(run=2, skipped=0, failures=0, errors=0, exit_code=0):
    import json as _json
    line = "WATCHTOWER_TESTS " + _json.dumps({"run": run, "skipped": skipped, "failures": failures, "errors": errors})
    return SandboxResult(exit_code, line + "\n", "", False)

HR = Role("f2.hr", "Dev HR", "f2", "small", "h")

def hr_dev(tmp_path, script, runner, rounds=4):
    return DevFloor(ARCH, CODER, ask=script, workspace=Workspace(tmp_path), run=runner, max_rounds=rounds, hr=HR)

from watchtower.engine.model_socket import BadModelOutput  # noqa: E402

from watchtower.floors.f2_dev.devfloor import units  # noqa: E402

PLAN3 = {"entry": "app.py", "routes": [], "files": [
    {"path": "store.py", "purpose": "data"}, {"path": "app.py", "purpose": "server"},
    {"path": "test_app.py", "purpose": "tests"}]}

from watchtower.floors.f2_dev.devfloor import app_is_tested  # noqa: E402

from watchtower.floors.f2_dev.devfloor import failures  # noqa: E402

REAL = """.FF
======================================================================
FAIL: test_list_todos (test_todo.TestTodoFunctions.test_list_todos)
----------------------------------------------------------------------
Traceback (most recent call last):
  File "/work/test_todo.py", line 6, in test_list_todos
    self.assertEqual(list_todos(), '<ul></ul>')
    ~~~~~~~~~~~~~~~~^^^^^^^^^^^^^^^^^^^^^^^^^^^
AssertionError: '<ul><li>Buy milk</li></ul>' != '<ul></ul>'
- <ul><li>Buy milk</li></ul>
+ <ul></ul>


======================================================================
FAIL: test_render_todo_form (test_todo.TestTodoFunctions.test_render_todo_form)
----------------------------------------------------------------------
Traceback (most recent call last):
  File "/work/test_todo.py", line 18, in test_render_todo_form
    self.assertEqual(render_todo_form(), expected)
    ~~~~~~~~~~~~~~~~^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
AssertionError: '<for[35 chars]     <input' != '<for[35 chars]         <input'
  <form action="/add" method="post">
-         <input type="text" name="item">
+             <input type="text" name="item">
? ++++
-     </form>
+         </form>
? ++++


----------------------------------------------------------------------
Ran 3 tests in 0.001s

FAILED (failures=2)
""" + "x" * 3000  # long noise after: the old 1200-char tail would lose the first failure

FAILED = SandboxResult(1, 'WATCHTOWER_TESTS {"run": 3, "skipped": 0, "failures": 2, "errors": 0}\n', REAL, False)

HR = Role("f2.hr", "HR", "f2", "small", "h")

from pathlib import Path as _Path  # noqa: E402

PY314 = (_Path(__file__).parent / "fixtures" / "unittest_report_py314.txt").read_text()

PY314B = (_Path(__file__).parent / "fixtures" / "unittest_report_py314_b.txt").read_text()

APP_ERROR = """E
======================================================================
ERROR: test_add (test_app.T.test_add)
----------------------------------------------------------------------
Traceback (most recent call last):
  File "/work/test_app.py", line 5, in test_add
    add_todo("x")
    ~~~~~~~~^^^^^
  File "/work/app.py", line 42, in add_todo
    return TODOS[kind]
           ~~~~~^^^^^^
KeyError: 'default'

----------------------------------------------------------------------
Ran 1 test in 0.001s

FAILED (errors=1)
"""

BROKEN_MAIN = ("import os\nfrom todo import add_todo\nhtml = '<h1>Todo</h1>'\nhtml += '<form>\n"
               "    <input name=item>\n  </form>'\nprint(html)\n")

from watchtower.floors.f2_dev.devfloor import repair_strings  # noqa: E402

def _run_runner(tmp_path, files):
    import subprocess
    import sys
    from watchtower.floors.f2_dev.devfloor import TEST_RUNNER, test_summary
    for name, body in files.items():
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_text(body)
    out = subprocess.run([sys.executable, "-I", "-c", TEST_RUNNER], cwd=tmp_path, capture_output=True, text=True,
                         timeout=60)
    return test_summary(out.stdout), out.stderr


__all__ = ['APP', 'APP_ERROR', 'ARCH', 'BROKEN_MAIN', 'BadModelOutput', 'CODER', 'DevFloor', 'FAIL', 'FAILED', 'HR', 'OK', 'PLAN3', 'PY314', 'PY314B', 'REAL', 'Role', 'Runner', 'SPEC', 'SandboxResult', 'Script', 'TEST', 'TEST_COMMAND', 'Workspace', '_Path', '_run_runner', 'app_is_tested', 'dev', 'failures', 'hr_dev', 'pytest', 'repair_strings', 'units', 'verdict']
