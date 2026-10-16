"""Phase 7a: the tower writes the web server for add-and-list apps; the coder writes only store.py."""
import json
import os
import socket
import subprocess
import sys

from watchtower.engine.sandbox import SandboxResult
from watchtower.engine.workspace import Workspace
from watchtower.floors.f2_dev.skeleton import apply
from watchtower.floors.f4_qa_deploy.contract import contract_checks
from watchtower.floors.f4_qa_deploy.qafloor import QA_SCRIPT, run_qa
from runner_kit import app_tower  # noqa: F401 — pipeline fixture

TODO = [{"method": "GET", "path": "/", "fields": [], "shows": "All todo items and an add form"},
        {"method": "POST", "path": "/add", "fields": ["item"], "shows": "Confirmation message."}]
GUEST = [{"method": "GET", "path": "/", "fields": [], "shows": "All messages"},
         {"method": "GET", "path": "/sign", "fields": [], "shows": "The sign form"},
         {"method": "POST", "path": "/sign", "fields": ["name", "message"], "shows": "Saved."}]
STORE = "ENTRIES = []\n\ndef add(entry):\n    ENTRIES.append(dict(entry))\n\ndef items():\n    return list(ENTRIES)\n"


def _plan(routes, entry="app.py"):
    return {"files": [{"path": entry, "purpose": "server"}, {"path": "todo.py", "purpose": "logic"}],
            "entry": entry, "routes": routes}


def _port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _qa(tmp_path, routes, store=STORE, title="My <b>Todo</b>"):
    plan, owned = apply(_plan(routes), title, Workspace(tmp_path))
    (tmp_path / "store.py").write_text(store)
    checks, decide = contract_checks(routes, "240940")
    proc = subprocess.run([sys.executable, "-I", "-c", QA_SCRIPT, plan["entry"], json.dumps(checks)], cwd=tmp_path,
                          capture_output=True, text=True, timeout=60, env={**os.environ, "WT_PORT": str(_port())})
    return run_qa(lambda cmd: SandboxResult(proc.returncode, proc.stdout, proc.stderr, False), plan["entry"],
                  checks, decide=decide)


def test_applies_to_a_plain_add_and_list_contract(tmp_path):
    plan, owned = apply(_plan(TODO), "Todo", Workspace(tmp_path))
    assert "app.py" in owned and "html.py" in owned and (tmp_path / "app.py").exists()
    assert [f["path"] for f in plan["files"]] == ["app.py", "store.py", "test_store.py"]
    assert "add(entry" in plan["files"][1]["purpose"] and "items()" in plan["files"][1]["purpose"]
    compile((tmp_path / "app.py").read_text(), "app.py", "exec")


def test_any_other_route_keeps_the_coder_path(tmp_path):
    routes = TODO + [{"method": "POST", "path": "/delete", "fields": ["item"], "shows": ""}]
    plan, owned = apply(_plan(routes), "Todo", Workspace(tmp_path))
    assert owned == set() and plan == _plan(routes) and not (tmp_path / "app.py").exists()
    assert apply(_plan([TODO[0]]), "Todo", Workspace(tmp_path))[1] == set()  # no adding route


def test_template_with_a_correct_store_passes_every_tower_check(tmp_path):
    pkg = _qa(tmp_path, TODO)
    assert pkg.checks_run[-1]["pass"] is True, pkg.summary


def test_separate_form_page_and_two_fields_pass(tmp_path):
    pkg = _qa(tmp_path, GUEST)
    assert all(r["pass"] for r in pkg.checks_run[-1]["results"]), pkg.summary


def test_store_returning_plain_strings_still_renders_escaped(tmp_path):
    store = "E = []\n\ndef add(entry):\n    E.append(entry['item'])\n\ndef items():\n    return E\n"
    assert _qa(tmp_path, TODO, store).checks_run[-1]["pass"] is True


def test_title_is_escaped_and_blank_fields_get_400(tmp_path):
    plan, _ = apply(_plan(TODO), "My <b>Todo</b>", Workspace(tmp_path))
    source = (tmp_path / "app.py").read_text()
    assert "<b>" in source  # stored as data, escaped at render time
    (tmp_path / "store.py").write_text(STORE)
    port = _port()
    proc = subprocess.Popen([sys.executable, "app.py"], cwd=tmp_path, env={**os.environ, "PORT": str(port)},
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        import time
        import urllib.error
        import urllib.request
        for _ in range(50):
            try:
                page = urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=1).read().decode()
                break
            except OSError:
                time.sleep(0.1)
        assert "&lt;b&gt;Todo&lt;/b&gt;" in page and "<b>Todo" not in page
        try:
            urllib.request.urlopen(urllib.request.Request(f"http://127.0.0.1:{port}/add", data=b"item=+",
                                                          method="POST"), timeout=2)
            status = 200
        except urllib.error.HTTPError as e:
            status = e.code
        assert status == 400
    finally:
        proc.kill()
        proc.wait()


def test_coder_cannot_overwrite_or_delete_an_owned_file(tmp_path):
    from devfloor_kit import dev
    floor = dev(tmp_path, lambda role, prompt: {}, lambda cmd: None)
    Workspace(tmp_path).write("app.py", "TOWER")
    floor.owned = {"app.py"}
    for f in ({"path": "app.py", "content": "x"}, {"path": "./App.py", "content": "x"},
              {"path": "app.py", "delete": True}):
        notes = floor._write([f])
        assert Workspace(tmp_path).read("app.py") == "TOWER" and any("store.py" in n for n in notes)


def test_tower_writes_the_server_and_tells_the_coder_the_store_contract(app_tower):
    from conftest import APP_REPLIES, STORE_CODER
    arch = dict(APP_REPLIES["f2.architect"][0])
    arch["routes"] = arch["routes"] + [{"method": "POST", "path": "/add", "fields": ["item"], "shows": "added"}]
    runner, model, sandbox, job = app_tower({"f2.architect": [arch], "f2.coder": STORE_CODER})
    assert runner.start(job.id, extra={"auto_approve": True}).status == "done"
    coder = [p for c, p in zip(model.calls, model.prompts) if c == "f2.coder"]
    assert coder and "store.py" in coder[0] and "add(entry)" in coder[0]
    assert "written by the tower" in Workspace(sandbox.workspace(job.id)).read("app.py")
    assert "f3.lead" not in model.calls  # 7a review r2: F3 expects the title, not a model guess
    runner.close()


def test_list_page_off_root_still_answers_root(tmp_path):  # 7a review r1: F3 and deploy probe GET /
    routes = [{"method": "GET", "path": "/todos", "fields": [], "shows": "All todos"},
              {"method": "POST", "path": "/add", "fields": ["item"], "shows": "added"}]
    assert _qa(tmp_path, routes).checks_run[-1]["pass"] is True
    assert "if path == LIST_PAGE or" in (tmp_path / "app.py").read_text()


def test_unsafe_entries_and_query_paths_keep_the_coder_path(tmp_path):
    for entry in ("src/app.py", "Store.py", "TEST_STORE.py", "html.py", "json.py"):
        assert apply(_plan(TODO, entry), "T", Workspace(tmp_path))[1] == set(), entry
    routes = [{**TODO[0], "path": "/?view=all"}, TODO[1]]
    assert apply(_plan(routes), "T", Workspace(tmp_path))[1] == set()


def test_replan_without_the_skeleton_removes_the_tower_server(tmp_path):
    ws = Workspace(tmp_path)
    _, owned = apply(_plan(TODO), "T", ws)
    routes = TODO + [{"method": "POST", "path": "/delete", "fields": ["item"], "shows": ""}]
    _, again = apply(_plan(routes), "T", ws, previous=owned)
    assert again == set() and "app.py" not in ws.files()
    ws.write("app.py", "coder's own")  # never delete a file the tower did not write
    apply(_plan(routes), "T", ws, previous={"app.py"})
    assert ws.read("app.py") == "coder's own"


def test_coder_cannot_shadow_modules_the_server_imports(tmp_path):
    from devfloor_kit import dev
    floor = dev(tmp_path, lambda role, prompt: {}, lambda cmd: None)
    _, floor.owned = apply(_plan(TODO), "T", Workspace(tmp_path))
    for path in ("html.py", "urllib/parse.py", "traceback.py"):
        notes = floor._write([{"path": path, "content": "x"}])
        assert path not in Workspace(tmp_path).files() and any("store.py" in n for n in notes), path


def test_coder_modules_named_like_the_stdlib_cannot_replace_it(tmp_path):  # 7a review r3
    (tmp_path / "http.py").write_text("raise SystemExit('shadowed')\n")
    (tmp_path / "copy.py").write_text("raise SystemExit('shadowed')\n")
    assert _qa(tmp_path, TODO).checks_run[-1]["pass"] is True


def test_store_package_and_robustness(tmp_path):
    from devfloor_kit import dev
    floor = dev(tmp_path, lambda role, prompt: {}, lambda cmd: None)
    _, floor.owned = apply(_plan(TODO), "T", Workspace(tmp_path))
    floor._write([{"path": "store/x.py", "content": "x"}])
    assert "store/x.py" not in Workspace(tmp_path).files()
    source = (tmp_path / "app.py").read_text()
    assert "timeout = 15" in source and "LOCK" in source


def test_a_lone_surrogate_title_still_serves(tmp_path):
    assert _qa(tmp_path, TODO, title="Todo \ud800").checks_run[-1]["pass"] is True


def test_snapshot_shows_the_tower_server_as_a_stub(tmp_path):  # 7a review r2: store.py must stay visible
    ws = Workspace(tmp_path)
    apply(_plan(TODO), "Todo", ws)
    ws.write("store.py", STORE)
    snap = ws.snapshot(1500)
    assert "ENTRIES = []" in snap and "ADD_PATH = '/add'" in snap and "def items_html" not in snap


def test_store_contract_says_raw_text_in_memory():
    from watchtower.floors.f2_dev.skeleton import _store_purpose
    text = _store_purpose(["item"])
    assert "as given" in text and "memory" in text and "files" in text and len(text) <= 200


def test_page_text_for_f3_is_the_title_when_it_reads_the_same():
    from watchtower.floors.f2_dev.skeleton import page_text
    assert page_text("Todo List") == "Todo List" and page_text("Tom & Jerry") == ""


def test_items_as_a_dict_render_its_values(tmp_path):
    store = "E = {}\n\ndef add(entry):\n    E[len(E)] = entry\n\ndef items():\n    return E\n"
    assert _qa(tmp_path, TODO, store).checks_run[-1]["pass"] is True


def test_missing_store_problem_names_store_py(tmp_path):
    from devfloor_kit import dev
    floor = dev(tmp_path, lambda role, prompt: {}, lambda cmd: None)
    _, floor.owned = apply(_plan(TODO), "T", Workspace(tmp_path))
    problems = floor._problems()
    assert problems and all("not in the Python standard library" not in p for p in problems)
    assert any("write store.py" in p for p in problems)


ESCAPING = ("import html\nE = []\n\ndef add(entry):\n    E.append({k: html.escape(v) for k, v in entry.items()})\n\n"
            "def items():\n    return list(E)\n")  # run 33: the coder escaped on save; the server escaped again


def test_a_store_that_escapes_on_save_still_shows_text_once(tmp_path):  # 7b
    book = [{"method": "GET", "path": "/", "fields": [], "shows": "All messages"},
            {"method": "POST", "path": "/add", "fields": ["name", "message"], "shows": "Saved."}]
    pkg = _qa(tmp_path, book, ESCAPING)
    assert pkg.checks_run[-1]["results"] and pkg.checks_run[-1]["pass"] is True, pkg.summary


def test_a_store_that_escapes_twice_still_shows_text_once(tmp_path):  # 7b
    twice = ESCAPING.replace("html.escape(v)", "html.escape(html.escape(v))")
    assert _qa(tmp_path, TODO, twice).checks_run[-1]["pass"] is True


def test_store_contract_says_never_escape():  # 7b: the server escapes; store.py keeps text as given
    from watchtower.floors.f2_dev.skeleton import _store_purpose
    text = _store_purpose(["name", "message"])
    assert "no html.escape" in text and len(text) <= 200


def test_release_note_says_who_wrote_what_and_data_is_in_memory(app_tower):  # 7b (run 34)
    from conftest import APP_REPLIES, STORE_CODER
    arch = dict(APP_REPLIES["f2.architect"][0])
    arch["routes"] = arch["routes"] + [{"method": "POST", "path": "/add", "fields": ["item"], "shows": "added"}]
    runner, model, sandbox, job = app_tower({"f2.architect": [arch], "f2.coder": STORE_CODER})
    answer = runner.start(job.id, extra={"auto_approve": True}).answer
    assert "the tower wrote the web server" in answer and "in memory" in answer
    runner.close()


def test_a_store_returning_a_lone_surrogate_still_answers(tmp_path):  # 7b review r3 M5
    store = "def add(entry):\n    pass\n\ndef items():\n    return ['bad \\ud800 text']\n"
    plan, _ = apply(_plan(TODO), "Todo", Workspace(tmp_path))
    (tmp_path / "store.py").write_text(store)
    port = _port()
    proc = subprocess.Popen([sys.executable, plan["entry"]], cwd=tmp_path, env={**os.environ, "PORT": str(port)},
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    try:
        import time
        import urllib.request
        for _ in range(50):  # the server prints before it binds
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=5) as r:
                    assert r.status == 200 and b"bad" in r.read()
                    break
            except OSError as e:
                if "Connection refused" not in str(e):
                    raise
                time.sleep(0.1)
        else:
            raise AssertionError("server never answered")
    finally:
        proc.kill()
        proc.wait()


def test_a_skeleton_coder_writes_only_the_store_and_its_tests(tmp_path):  # 7c (run 36: a stray XSS app.py shipped)
    from devfloor_kit import dev
    floor = dev(tmp_path, lambda role, prompt: {}, lambda cmd: None)
    _, floor.owned = apply(_plan(TODO), "Todo", Workspace(tmp_path))
    for path in ("server.py", "test_server.py", "tests/test_store.py", "data.json", "store/__init__.py", "README.md"):
        notes = floor._write([{"path": path, "content": "x = 1\n"}])
        assert path not in Workspace(tmp_path).files() and any("store.py" in n for n in notes), path
    notes = floor._write([{"path": "store.py", "content": STORE}, {"path": "test_store.py", "content": "import store\n"},
                          {"path": "Store.py", "content": "x = 1\n"}])  # 7c r1 M4: exact names only
    assert set(Workspace(tmp_path).files()) == {"app.py", "store.py", "test_store.py"}
    assert any("'Store.py'" in n for n in notes)


def test_a_skeleton_coder_may_still_delete_a_stray_file(tmp_path):  # 7c
    from devfloor_kit import dev
    floor = dev(tmp_path, lambda role, prompt: {}, lambda cmd: None)
    _, floor.owned = apply(_plan(TODO), "Todo", Workspace(tmp_path))
    Workspace(tmp_path).write("server.py", "x = 1\n")
    floor._write([{"path": "server.py", "delete": True}])
    assert "server.py" not in Workspace(tmp_path).files()


def test_without_the_skeleton_any_file_may_be_written(tmp_path):  # 7c: the coder path is unchanged
    from devfloor_kit import dev
    floor = dev(tmp_path, lambda role, prompt: {}, lambda cmd: None)
    floor._write([{"path": "server.py", "content": "x = 1\n"}])
    assert "server.py" in Workspace(tmp_path).files()


def test_a_server_inside_the_store_is_a_problem(tmp_path):  # 7c review r1 I1: the allowlist moves it into store.py
    from devfloor_kit import dev
    from watchtower.floors.f2_dev.skeleton import store_problems
    ws = Workspace(tmp_path)
    apply(_plan(TODO), "Todo", ws)
    for code in ("import http.server\n", "from socketserver import TCPServer\n", "import subprocess as s\n",
                 "import importlib\nimportlib.import_module('socket')\n", "x = __import__('wsgiref.simple_server')\n"):
        ws.write("store.py", code)
        assert any("store.py" in p for p in store_problems(ws)), code
    ws.write("store.py", STORE)
    ws.write("test_store.py", "import unittest\nimport store\nstore.add({'item': 'http'})\nprint('socket')\n")
    assert store_problems(ws) == []  # a string that names a module is not an import
    floor = dev(tmp_path, lambda role, prompt: {}, lambda cmd: None)
    floor.owned = {"app.py"}
    ws.write("test_store.py", "import socket\n")
    assert any("test_store.py" in p for p in floor._problems())


def test_the_skeleton_removes_an_earlier_plan_s_files(tmp_path):  # 7c review r1 I2
    ws = Workspace(tmp_path)
    ws.write("server.py", "import http.server\n")
    ws.write("lib/handlers.py", "x = 1\n")
    ws.write("store.py", STORE)
    apply(_plan(TODO), "Todo", ws)
    assert set(ws.files()) == {"app.py", "store.py"}


def test_a_skeleton_coder_hears_the_file_rule_up_front():  # 7c review r1 I3
    from watchtower.floors.f2_dev.devfloor import _qa_block
    assert "Write only store.py and test_store.py" in _qa_block("QA:\n", [], store_only=True)
    assert "Write only" not in _qa_block("QA:\n", contract_checks(TODO, "1")[0])


def test_a_rejected_file_is_a_change(tmp_path):  # 7c review r1 M5: no 'nothing could get better'
    from devfloor_kit import dev
    floor = dev(tmp_path, lambda role, prompt: {}, lambda cmd: None)
    _, floor.owned = apply(_plan(TODO), "Todo", Workspace(tmp_path))
    floor._write([{"path": "store.py", "content": STORE}])
    notes = floor._write([{"path": "store.py", "content": STORE}, {"path": "app2.py", "content": "x"}])
    assert not any("unchanged" in n.lower() or "nothing could get better" in n.lower() for n in notes)


EVASIONS = ("from xmlrpc.server import SimpleXMLRPCServer\n", "import _socket\n", "import urllib.request\n",
            "import os\nos.system('x')\n", "exec('import socket')\n", "eval('1')\n", "f = open('d.json', 'w')\n",
            "x = __import__('so' + 'cket')\n", "import importlib\nim = importlib.import_module\n",
            "import __main__\n", "def add(e):\n    e.__class__.__init__.__globals__\n", "import ctypes\n",
            "from . import x\n")


def test_the_store_may_import_only_safe_modules(tmp_path):  # 7c review r2 I1: an allowlist, not a denylist
    from watchtower.floors.f2_dev.skeleton import store_problems
    ws = Workspace(tmp_path)
    for code in EVASIONS:
        ws.write("store.py", code)
        assert any("store.py" in p for p in store_problems(ws)), code


def test_a_plain_store_and_its_tests_pass(tmp_path):  # 7c review r2 M5: no false positives
    from watchtower.floors.f2_dev.skeleton import store_problems
    ws = Workspace(tmp_path)
    ws.write("store.py", "from __future__ import annotations\nimport json, threading, copy, html\n"
                         "from datetime import datetime\nfrom collections import OrderedDict\n" + STORE
             + "if __name__ == '__main__':\n    print(items())\n")
    ws.write("test_store.py", "import importlib\nimport unittest\nimport store\n\nclass T(unittest.TestCase):\n"
                              "    def setUp(self):\n        importlib.reload(store)\n\n"
                              "    def test_add(self):\n        store.add({'item': 'http'})\n"
                              "        self.assertEqual(store.items(), [{'item': 'http'}])\n\n"
                              "if __name__ == '__main__':\n    unittest.main()\n")
    assert store_problems(ws) == []


def test_store_problems_come_first(tmp_path):  # 7c review r2 M4: the coder sees only the first 3
    from devfloor_kit import dev
    floor = dev(tmp_path, lambda role, prompt: {}, lambda cmd: None)
    _, floor.owned = apply(_plan(TODO), "Todo", Workspace(tmp_path))
    Workspace(tmp_path).write("store.py", "import requests\nimport yaml\nimport flask\nimport socket\n")
    problems = floor._problems()
    assert len(problems) > 1 and "only keeps data" in problems[0]


def test_the_only_note_survives_checks_without_escapes():  # 7c review r2 M3 (operator precedence)
    from watchtower.floors.f2_dev.devfloor import _qa_block
    checks = [{"name": "x", "path": "/", "expect_text": "a"}]
    assert "Write only store.py" in _qa_block("QA:\n", checks, store_only=True)


def test_a_file_the_workspace_cannot_delete_does_not_stop_the_plan(tmp_path):  # 7c review r2 M2
    from watchtower.engine.workspace import WorkspaceError
    ws = Workspace(tmp_path)
    (tmp_path / "todo.db").write_bytes(b"x")
    try:
        ws.delete("todo.db")
        undeletable = False
    except WorkspaceError:
        undeletable = True
    plan, owned = apply(_plan(TODO), "Todo", ws)
    assert owned and (not undeletable or (tmp_path / "todo.db").exists())
