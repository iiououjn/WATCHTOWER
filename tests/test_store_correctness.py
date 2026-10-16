"""Phase 8c (audit 2026-10-16 batch 3): under the skeleton the tower never asks for code its own checks reject."""
from devfloor_kit import CODER, SPEC, Script, dev, verdict

from watchtower.engine.workspace import Workspace
from watchtower.floors.f2_dev.devfloor import units
from watchtower.floors.f2_dev.skeleton import apply
from conftest import start_signed
from runner_kit import app_tower  # noqa: F401 — pipeline fixture

ROUTES = [{"method": "GET", "path": "/", "fields": [], "shows": "All todo items and an add form"},
          {"method": "POST", "path": "/add", "fields": ["item"], "shows": "Confirmation message."}]
STORE = "ENTRIES = []\n\ndef add(entry):\n    ENTRIES.append(dict(entry))\n\ndef items():\n    return list(ENTRIES)\n"


def _owned(tmp_path, script=None, runner=None):
    floor = dev(tmp_path, script or (lambda role, prompt: {}), runner or (lambda cmd: verdict()))
    plan = {"files": [{"path": "app.py", "purpose": "server"}], "entry": "app.py", "routes": ROUTES}
    plan, floor.owned = apply(plan, "Todo", Workspace(tmp_path))
    return floor, plan


def test_the_store_is_written_before_its_tests(tmp_path):  # C-H1 (run 38: the store copied the tests' names)
    floor, plan = _owned(tmp_path)
    assert [[f["path"] for f in u] for u in units(plan, floor.owned)] == [["app.py"], ["store.py"], ["test_store.py"]]
    script = Script({CODER.id: [{"files": [{"path": "store.py", "content": STORE}]},
                                {"files": [{"path": "test_store.py", "content": "import store\n"}]}]})
    floor._ask = script
    written = []
    floor.write_units(SPEC, plan, on_unit=lambda i, n, paths: written.append(paths))
    assert written == [["store.py"], ["test_store.py"]]
    assert "def add(entry)" in script.prompts[CODER.id][1]  # the test writer sees the real store


def test_the_test_unit_names_the_store_calls(tmp_path):  # C-H1: the test writer never sees _store_purpose
    _, plan = _owned(tmp_path)
    purpose = next(f["purpose"] for f in plan["files"] if f["path"] == "test_store.py")
    assert "import store" in purpose and "store.add(entry)" in purpose and "store.items()" in purpose


def test_owned_test_notes_point_at_test_store_and_import_store(tmp_path):  # C-H2.1: 'from app import' is rejected
    script = Script({CODER.id: [{"files": [{"path": "store.py", "content": STORE},
                                           {"path": "test_store.py", "content": "import unittest\n"}]},
                                {"files": [{"path": "store.py", "content": STORE}]}]})
    floor, plan = _owned(tmp_path, script)
    floor._max_rounds = 2
    floor.build(SPEC, plan, [])
    second = script.prompts[CODER.id][1]
    assert "import store" in second and "from app import" not in second
    Workspace(tmp_path).delete("test_store.py")
    script.prompts[CODER.id].clear()
    floor.build(SPEC, plan, [])
    assert "test_store.py" in script.prompts[CODER.id][1] and "test_*.py" not in script.prompts[CODER.id][1]


def test_the_reset_hint_is_code_the_store_check_accepts(tmp_path):  # C-H2.2: `store._entries.clear()`
    from watchtower.floors.f2_dev.lint import idiom_notes
    from watchtower.floors.f2_dev.skeleton import store_problems
    ws = Workspace(tmp_path)
    ws.write("store.py", "_entries = []\n\ndef add(entry):\n    _entries.append(entry)\n\ndef items():\n"
                         "    return list(_entries)\n")
    ws.write("test_store.py", "import unittest\nfrom store import _entries\n\nclass T(unittest.TestCase):\n"
                              "    def setUp(self):\n        global _entries\n        _entries = []\n")
    hint = next(n for n in idiom_notes(ws) if "global _entries" in n)
    assert "store._entries.clear()" in hint
    ws.write("test_store.py", "import unittest\nimport store\n\nclass T(unittest.TestCase):\n"
                              "    def setUp(self):\n        store._entries.clear()\n")
    assert store_problems(ws) == []
    ws.write("test_store.py", "import store\nstore.add.__globals__\n")  # dunders stay banned in tests
    assert any("__globals__" in p for p in store_problems(ws))


def test_auto_repair_adds_only_imports_the_file_may_have(tmp_path):  # C-H2.3: `import os` then "imports os"
    floor, _ = _owned(tmp_path)
    notes = floor._write([{"path": "store.py", "content": STORE + "P = os.path.join('a', 'b')\nE = escape('<')\n"
                                                             "D = json.dumps([])\n"}])
    text = Workspace(tmp_path).read("store.py")
    assert "import json" in text and "import os" not in text and "import escape" not in text
    assert not any("import os" in n or "escape" in n for n in notes)
    floor._write([{"path": "test_store.py", "content": "import store\nD = tempfile.mkdtemp()\nX = os.sep\n"}])
    text = Workspace(tmp_path).read("test_store.py")
    assert "import os" in text and "import tempfile" not in text


def test_ordinary_store_code_is_not_rejected(tmp_path):  # C-M1: re.compile, __all__, __slots__
    from watchtower.floors.f2_dev.skeleton import store_problems
    ws = Workspace(tmp_path)
    for fine in ("import re\nPAT = re.compile('[a-z]+')\n", "__all__ = ['add', 'items']\n",
                 "class Entry:\n    __slots__ = ('name',)\n"):
        ws.write("store.py", STORE + fine)
        assert store_problems(ws) == [], fine


def test_every_store_problem_says_what_to_do(tmp_path):  # C-M1: "only keeps data in memory" was no fix
    from watchtower.floors.f2_dev.skeleton import store_problems
    ws = Workspace(tmp_path)
    ws.write("store.py", STORE)
    ws.write("test_store.py", "import tempfile\nimport store\n")
    [p] = store_problems(ws)
    assert "imports tempfile: import only" in p and "unittest" in p and "in memory" not in p and len(p) <= 200
    ws.delete("test_store.py")
    for code, fix in (("import os\n", "import only collections"), ("exec('1')\n", "remove it"),
                      ("class S:\n    def __init__(self):\n        self._rows = []\n", "leading underscore")):
        ws.write("store.py", STORE + code)
        [p] = store_problems(ws)
        assert fix in p and len(p) <= 200, p


def test_a_garbled_reply_after_hr_keeps_the_verdict_and_the_objection(tmp_path):  # C-M6: PASS vs pass False
    from devfloor_kit import APP, ARCH, HR, OK, PLAN3, TEST, Runner
    from watchtower.engine.model_socket import BadModelOutput
    from watchtower.floors.f2_dev.devfloor import DevFloor
    replies = [{"files": [APP, TEST]}, "garbled"]

    def ask(role, prompt):
        if role.id == HR.id:
            return {"pass": False, "reason": "add a delete route"}
        r = replies.pop(0)
        if r == "garbled":
            raise BadModelOutput("x")
        return r
    pkg = DevFloor(ARCH, CODER, ask=ask, workspace=Workspace(tmp_path), run=Runner([OK]), max_rounds=2,
                   hr=HR).build(SPEC, PLAN3, [])
    assert ("Tests: PASS" in pkg.summary) == pkg.checks_run[-1]["pass"] is True  # the files did not change
    assert any("add a delete route" in q for q in pkg.open_questions)
    assert not any(q.startswith("tests still failing") for q in pkg.open_questions)


def test_an_invalid_entry_renamed_to_app_py_leaves_no_second_server(tmp_path):  # C-M7
    s = Script({"f2.architect": [{"files": [{"path": "my-app.py", "purpose": "server"},
                                            {"path": "test_x.py", "purpose": "tests"}], "entry": "my-app.py"}],
                CODER.id: [{}]})
    plan = dev(tmp_path, s, lambda cmd: verdict()).plan(SPEC, "", [])
    assert plan["entry"] == "app.py" and [f["path"] for f in plan["files"]] == ["test_x.py", "app.py"]


def test_a_case_only_name_is_written_under_the_planned_name(tmp_path):  # C-M3: endless "create app.py"
    ws = Workspace(tmp_path)
    ws.write("App.py", "x = 0\n")
    floor = dev(tmp_path, lambda role, prompt: {}, lambda cmd: verdict())
    floor._write([{"path": "app.py", "content": "x = 1\n"}], "app.py")
    assert ws.files() == ["app.py"] and ws.read("app.py") == "x = 1\n"
    floor._write([{"path": "APP.py", "content": "x = 2\n"}], "app.py")
    assert ws.files() == ["app.py"] and ws.read("app.py") == "x = 2\n"


def test_a_case_only_name_for_another_file_keeps_the_existing_name(tmp_path):  # 8c review r1: import utils broke
    ws = Workspace(tmp_path)
    ws.write("utils.py", "x = 0\n")
    ws.write("test_app.py", "x = 0\n")
    floor = dev(tmp_path, lambda role, prompt: {}, lambda cmd: verdict())
    floor._write([{"path": "Utils.py", "content": "x = 1\n"}, {"path": "Test_app.py", "content": "x = 1\n"}], "app.py")
    assert ws.files() == ["test_app.py", "utils.py"] and ws.read("utils.py") == "x = 1\n"


def test_a_rejected_case_only_write_keeps_the_old_file(tmp_path):  # 8c review r1: deleted before a failed write
    ws = Workspace(tmp_path)
    ws.write("App.py", "x = 0\n")
    floor = dev(tmp_path, lambda role, prompt: {}, lambda cmd: verdict())
    notes = floor._write([{"path": "app.py", "content": "x" * 200_000}], "app.py")
    assert ws.files() == ["App.py"] and ws.read("App.py") == "x = 0\n"
    assert any("larger than 100 KB" in n for n in notes)


def test_a_private_store_import_in_tests_points_at_store_dot_name(tmp_path):  # 8c review r1: "public names"
    from watchtower.floors.f2_dev.skeleton import store_problems
    ws = Workspace(tmp_path)
    ws.write("store.py", STORE)
    ws.write("test_store.py", "from store import _entries\n")
    problem = next(p for p in store_problems(ws) if "_entries" in p)
    assert "store._entries" in problem and "public" not in problem


def test_under_the_skeleton_no_coder_message_asks_for_a_web_app(app_tower):  # 8c review r3: Review Focus 1
    from conftest import APP_REPLIES, STORE_CODER
    arch = dict(APP_REPLIES["f2.architect"][0])
    arch["routes"] = arch["routes"] + [{"method": "POST", "path": "/add", "fields": ["item"], "shows": "added"}]
    runner, model, _, job = app_tower({"f2.architect": [arch], "f2.coder": ["I will write it now."] + STORE_CODER})
    assert start_signed(runner, job.id).status == "done"
    convos = [m for c, m in zip(model.calls, model.messages) if c == "f2.coder"]
    retries = [m[-1]["content"].split("no usable files", 1)[1] for m in convos if "no usable files" in m[-1]["content"]]
    assert convos and retries
    for system in {m[0]["content"] for m in convos}:
        assert "store.py" in system and "add(entry)" in system and "items()" in system
        assert not any(bad in system for bad in ("app.py", "test_*.py", "add_todo", "PORT")), system
    for text in retries + [m[-1]["content"] for m in convos]:
        assert "test_*.py" not in text and "add_todo" not in text
    assert all("app.py" not in r and "### FILE: store.py" in r for r in retries)
    runner.close()


def test_the_coder_keeps_its_web_app_prompt_without_the_skeleton(app_tower):  # 8c review r3: only owned mode
    runner, model, _, job = app_tower()
    assert start_signed(runner, job.id).status == "done"
    systems = {m[0]["content"] for c, m in zip(model.calls, model.messages) if c == "f2.coder"}
    assert systems and all("PORT" in s and "### FILE: app.py" in s for s in systems)
    runner.close()


def test_store_problem_fixes_fit_their_file(tmp_path):  # 8c review r3 minors: test dunders, long names, ._os
    from watchtower.floors.f2_dev.skeleton import store_problems
    ws = Workspace(tmp_path)
    ws.write("store.py", STORE)
    ws.write("test_store.py", "import store\n\ndef name(x):\n    return type(x).__name__\n")
    [p] = store_problems(ws)
    assert "compare values directly" in p and "class" not in p, p
    ws.write("test_store.py", "import xml.etree.ElementTree\nimport store\n")
    [p] = store_problems(ws)
    assert len(p) <= 200 and p.endswith("uuid"), p
    ws.delete("test_store.py")
    ws.write("store.py", STORE + "import threading\nX = threading._os\n")
    [p] = store_problems(ws)
    assert "uses ._os: remove it" in p and "underscore" not in p, p
