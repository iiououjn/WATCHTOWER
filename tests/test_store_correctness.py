"""Phase 8c (audit 2026-10-16 batch 3): under the skeleton the tower never asks for code its own checks reject."""
from devfloor_kit import CODER, SPEC, Script, dev, verdict

from watchtower.engine.workspace import Workspace
from watchtower.floors.f2_dev.devfloor import units
from watchtower.floors.f2_dev.skeleton import apply

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
