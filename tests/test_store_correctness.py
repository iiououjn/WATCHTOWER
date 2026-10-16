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
