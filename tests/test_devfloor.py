import pytest

from watchtower.engine.devfloor import TEST_COMMAND, DevFloor
from watchtower.engine.sandbox import SandboxResult
from watchtower.engine.workspace import Workspace
from watchtower.roles import Role

ARCH = Role("f2.architect", "Architect", "f2", "work", (), "a")
CODER = Role("f2.coder", "Coder", "f2", "work", (), "c")
SPEC = {"title": "Todo", "goal": "todo app", "acceptance": ["lists todos"], "out_of_scope": []}
APP = {"path": "app.py", "content": "import json\nprint('app')\n"}
TEST = {"path": "test_app.py", "content": "import unittest\n"}


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


OK = SandboxResult(0, "", "Ran 2 tests in 0.01s\n\nOK\n", False)
FAIL = SandboxResult(1, "", "AssertionError: expected 3 got 2\nFAILED (failures=1)\n", False)


def dev(tmp_path, script, runner, rounds=4):
    return DevFloor(ARCH, CODER, ask=script, workspace=Workspace(tmp_path), run=runner, max_rounds=rounds)


def test_plan_normalises_entry_and_files(tmp_path):
    s = Script({"f2.architect": [{"files": [{"path": "app.py", "purpose": "server"}, "junk"]}], "f2.coder": [{}]})
    plan = dev(tmp_path, s, Runner([OK])).plan(SPEC, "", [])
    assert plan == {"files": [{"path": "app.py", "purpose": "server"}], "entry": "app.py"}


def test_coder_fixes_failing_tests_from_real_output(tmp_path):
    s = Script({"f2.architect": [{}], "f2.coder": [{"files": [APP, TEST]}, {"files": [APP]}]})
    runner = Runner([FAIL, OK])
    pkg = dev(tmp_path, s, runner).build(SPEC, {"files": [], "entry": "app.py"}, [])
    assert runner.calls == [TEST_COMMAND, TEST_COMMAND]
    second = s.prompts["f2.coder"][1]
    assert '<untrusted source="sandbox">' in second and "expected 3 got 2" in second
    assert pkg.checks_run[-1]["pass"] is True and pkg.validate() == []
    assert pkg.artifacts == ["app.py", "test_app.py"]


def test_third_party_import_is_not_a_pass(tmp_path):
    bad = {"path": "app.py", "content": "import requests\n"}
    s = Script({"f2.architect": [{}], "f2.coder": [{"files": [bad, TEST]}]})
    pkg = dev(tmp_path, s, Runner([OK]), rounds=2).build(SPEC, {"files": [], "entry": "app.py"}, [])
    assert pkg.checks_run[-1]["pass"] is False
    assert "requests (not in the Python standard library)" in s.prompts["f2.coder"][1]
    assert "reality check failed" in " ".join(pkg.validate())


def test_zero_tests_is_not_a_pass(tmp_path):
    s = Script({"f2.architect": [{}], "f2.coder": [{"files": [APP, TEST]}]})
    none = SandboxResult(0, "", "Ran 0 tests in 0.000s\n\nNO TESTS RAN\n", False)
    pkg = dev(tmp_path, s, Runner([none]), rounds=1).build(SPEC, {"files": [], "entry": "app.py"}, [])
    assert pkg.checks_run[-1]["pass"] is False


def test_missing_test_file_is_not_a_pass(tmp_path):
    s = Script({"f2.architect": [{}], "f2.coder": [{"files": [APP]}]})
    pkg = dev(tmp_path, s, Runner([OK]), rounds=1).build(SPEC, {"files": [], "entry": "app.py"}, [])
    assert pkg.checks_run[-1]["pass"] is False


def test_unsafe_paths_rejected_and_reported(tmp_path):
    evil = {"path": "../evil.py", "content": "x"}
    s = Script({"f2.architect": [{}], "f2.coder": [{"files": [evil, APP, TEST]}, {"files": [APP]}]})
    dev(tmp_path, s, Runner([OK]), rounds=2).build(SPEC, {"files": [], "entry": "app.py"}, [])
    assert not (tmp_path.parent / "evil.py").exists()


def test_at_most_three_files_per_round(tmp_path):
    many = [{"path": f"m{i}.py", "content": "x = 1\n"} for i in range(6)]
    s = Script({"f2.architect": [{}], "f2.coder": [{"files": many}]})
    d = dev(tmp_path, s, Runner([FAIL]), rounds=1)
    d.build(SPEC, {"files": [], "entry": "app.py"}, [])
    assert Workspace(tmp_path).files() == ["m0.py", "m1.py", "m2.py"]


def test_gate_feedback_reaches_coder(tmp_path):
    s = Script({"f2.architect": [{}], "f2.coder": [{"files": [APP, TEST]}]})
    dev(tmp_path, s, Runner([OK])).build(SPEC, {"files": [], "entry": "app.py"}, ["add a delete button"])
    assert "add a delete button" in s.prompts["f2.coder"][0]


def test_test_folders_become_packages_so_unittest_finds_them(tmp_path):
    nested = {"path": "tests/test_app.py", "content": "import unittest\n"}
    s = Script({"f2.architect": [{}], "f2.coder": [{"files": [APP, nested]}]})
    dev(tmp_path, s, Runner([OK]), rounds=1).build(SPEC, {"files": [], "entry": "app.py"}, [])
    assert (tmp_path / "tests" / "__init__.py").exists()
    assert not (tmp_path / "__init__.py").exists()


def test_zero_tests_feedback_explains_why(tmp_path):
    s = Script({"f2.architect": [{}], "f2.coder": [{"files": [APP, TEST]}]})
    none = SandboxResult(5, "", "Ran 0 tests in 0.000s\n\nNO TESTS RAN\n", False)
    dev(tmp_path, s, Runner([none]), rounds=2).build(SPEC, {"files": [], "entry": "app.py"}, [])
    assert "test_*.py" in s.prompts["f2.coder"][1] and "unittest.TestCase" in s.prompts["f2.coder"][1]
