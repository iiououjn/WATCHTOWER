from watchtower.engine.workspace import Workspace
from watchtower.floors.f2_dev.lint import handler_state_problems

RUN12 = '''from http.server import BaseHTTPRequestHandler
from todo import add_todo, list_todos

class TodoHandler(BaseHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        self.todo_list = []
        super().__init__(*args, **kwargs)

    def do_GET(self):
        content = list_todos(self.todo_list)
        self.wfile.write(content.encode())

    def do_POST(self):
        item = self.rfile.read(5).decode()
        self.todo_list = add_todo(self.todo_list, item)
'''


def problems(tmp_path, source):
    ws = Workspace(tmp_path)
    ws.write("app.py", source)
    return handler_state_problems(ws)


def test_run12_handler_state_is_named(tmp_path):
    (p,) = problems(tmp_path, RUN12)
    assert "app.py" in p and "self.todo_list" in p and "each request gets a new handler" in p and p.endswith("in a file.")
    assert len(problems(tmp_path, RUN12.replace("TodoHandler", "T" * 300))[0]) <= 200


def test_patterns_that_work_are_left_alone(tmp_path):
    shared = RUN12.replace("    def __init__(self, *args, **kwargs):\n        self.todo_list = []\n"
                           "        super().__init__(*args, **kwargs)\n", "    todo_list = []\n").replace(
        "        self.todo_list = add_todo(self.todo_list, item)", "        self.todo_list.append(item)")
    per_request = ("from http.server import BaseHTTPRequestHandler\nclass H(BaseHTTPRequestHandler):\n"
                   "    def do_POST(self):\n        self.form = self.rfile.read(3)\n        self._save()\n"
                   "    def _save(self):\n        print(self.form)\n    def do_GET(self):\n"
                   "        self.wfile.write(b'x')\n")
    module_level = ("from http.server import BaseHTTPRequestHandler\nITEMS = []\nclass H(BaseHTTPRequestHandler):\n"
                    "    def do_POST(self):\n        ITEMS.append(1)\n        self.server.items = ITEMS\n"
                    "    def do_GET(self):\n        self.wfile.write(str(ITEMS).encode())\n")
    not_a_handler = RUN12.replace("(BaseHTTPRequestHandler)", "(object)")
    for source in (shared, per_request, module_level, not_a_handler, "def f(:\n"):
        assert problems(tmp_path, source) == [], source[:80]


def test_mutating_an_instance_list_is_caught(tmp_path):
    source = RUN12.replace("        self.todo_list = add_todo(self.todo_list, item)", "        self.todo_list.append(item)")
    assert len(problems(tmp_path, source)) == 1


def test_f2_does_not_pass_while_handler_state_is_lost(tmp_path):
    from test_devfloor import CODER, ARCH, OK, SPEC, TEST, Runner, Script  # noqa: I001
    from watchtower.floors.f2_dev.devfloor import DevFloor
    todo = {"path": "todo.py", "content": "def add_todo(t, i):\n    return t + [i]\n\ndef list_todos(t):\n    return ''\n"}
    s = Script({"f2.coder": [{"files": [{"path": "app.py", "content": RUN12}, todo, TEST]}]})
    pkg = DevFloor(ARCH, CODER, ask=s, workspace=Workspace(tmp_path), run=Runner([OK]), max_rounds=2).build(
        SPEC, {"files": [], "entry": "app.py"}, [])
    assert pkg.checks_run[-1]["pass"] is False and "each request gets a new handler" in s.prompts["f2.coder"][1]


HEAD = "from http.server import BaseHTTPRequestHandler\nITEMS = []\nclass H(BaseHTTPRequestHandler):\n"


def test_correct_handlers_reported_by_review_are_left_alone(tmp_path):
    cases = [
        # each method sets its own per-request value first
        "    def do_GET(self):\n        self.body = b'x'\n        self.wfile.write(self.body)\n"
        "    def do_POST(self):\n        self.body = b'ok'\n        self.wfile.write(self.body)\n",
        # the stdlib sets path for every request
        "    def do_GET(self):\n        self.path = self.path.rstrip('/')\n"
        "    def do_POST(self):\n        if self.path == '/add':\n            pass\n",
        # POST sets a message, then renders through do_GET in the same request
        "    message = ''\n    def do_POST(self):\n        self.message = 'Added'\n        self.do_GET()\n"
        "    def do_GET(self):\n        self.wfile.write(self.message.encode())\n",
        # the reader loads its value through a helper first
        "    def _load(self):\n        self.data = self.rfile.read(3)\n"
        "    def do_PUT(self):\n        self._load()\n        ITEMS.append(self.data)\n"
        "    def do_POST(self):\n        self.data = self.rfile.read(3)\n        ITEMS.append(self.data)\n",
    ]
    for body in cases:
        assert problems(tmp_path, HEAD + body) == [], body


def test_data_written_through_a_helper_is_still_caught(tmp_path):
    body = ("    def _save(self, item):\n        self.items.append(item)\n"
            "    def do_POST(self):\n        self._save(1)\n"
            "    def do_GET(self):\n        self.wfile.write(str(self.items).encode())\n")
    assert len(problems(tmp_path, HEAD.replace("class H", "class H") + "    def __init__(self, *a):\n        self.items = []\n"
                        "        super().__init__(*a)\n" + body)) == 1


def test_message_never_exceeds_the_note_cut(tmp_path):
    ws = Workspace(tmp_path)
    name = "a" * 40 + "/" + "b" * 40 + ".py"
    ws.write(name, RUN12.replace("TodoHandler", "T" * 60).replace("todo_list", "t" * 60))
    (p,) = handler_state_problems(ws)
    assert len(p) <= 200 and p.endswith("in a file.")


def test_a_per_request_override_read_by_a_shared_helper_is_left_alone(tmp_path):
    body = ("    status = 200\n    def _send(self, body):\n        self.send_response(self.status)\n"
            "        self.wfile.write(body)\n    def do_GET(self):\n        self._send(b'list')\n"
            "    def do_POST(self):\n        self.status = 201\n        self._send(b'created')\n")
    assert problems(tmp_path, HEAD + body) == []


def test_a_big_handler_is_checked_quickly(tmp_path):
    import time
    methods = "".join(f"    def _h{i}(self):\n" + "".join(f"        self.a{j} = self.a{j + 1}\n" for j in range(30))
                      + f"        self._h{(i + 1) % 40}()\n" for i in range(40))
    handlers = "".join(f"    def do_M{i}(self):\n        self._h{i}()\n" for i in range(7))
    start = time.monotonic()
    problems(tmp_path, HEAD + methods + handlers)
    assert time.monotonic() - start < 2


def test_notes_name_fixture_tests_that_never_ran_and_self_patching(tmp_path):
    from watchtower.floors.f2_dev.lint import idiom_notes
    ws = Workspace(tmp_path)
    ws.write("test_app.py", "from unittest.mock import patch\nfrom app import add_todo, get_todos\n\n"
             "def test_request(path):\n    return path\n\ndef test_a():\n    assert test_request('/')\n\n"
             "def test_updated_list(client):\n    assert client.get('/')\n\n"
             "def test_add_item(client):\n    pass\n\n"
             "@patch('app.add_todo')\ndef test_add_todo(mock_add):\n    add_todo('x')\n    mock_add.assert_called_once_with('x')\n\n"
             "@patch('app.get_todos')\ndef test_ok(m):\n    import app\n    app.get_todos()\n")
    notes = idiom_notes(ws)
    assert len(notes) == 2 and all(len(n) <= 200 for n in notes)
    assert "test_add_item, test_updated_list" in notes[0] and "never ran" in notes[0] and "test_request" not in notes[0]
    assert "test_add_todo" in notes[1] and "app.add_todo" in notes[1] and "test_ok" not in notes[1]


def test_the_coder_hears_about_tests_that_never_ran(tmp_path):
    from test_devfloor import ARCH, CODER, FAILED, SPEC, Runner, Script  # noqa: I001
    from watchtower.floors.f2_dev.devfloor import DevFloor
    fixture = {"path": "test_app.py", "content": "from app import f\n\ndef test_a(client):\n    assert f()\n"}
    s = Script({"f2.coder": [{"files": [{"path": "app.py", "content": "def f():\n    return 1\n"}, fixture]}]})
    DevFloor(ARCH, CODER, ask=s, workspace=Workspace(tmp_path), run=Runner([FAILED]), max_rounds=2).build(
        SPEC, {"files": [], "entry": "app.py"}, [])
    assert "so they never ran" in s.prompts["f2.coder"][1]


def test_patched_or_fixture_functions_get_no_never_ran_note(tmp_path):
    from watchtower.floors.f2_dev.lint import idiom_notes
    ws = Workspace(tmp_path)
    ws.write("test_app.py", "import app, pytest\nfrom unittest import mock\nfrom unittest.mock import patch as mp\n\n"
             "@mock.patch.object(app, 'save')\ndef test_a(m):\n    app.add('x')\n\n"
             "@mp('app.save')\ndef test_b(m):\n    pass\n\n@pytest.fixture\ndef test_client(app):\n    return app\n")
    assert idiom_notes(ws) == []


def test_self_patch_note_keeps_its_advice_and_only_plain_names(tmp_path):
    from watchtower.floors.f2_dev.lint import idiom_notes
    ws = Workspace(tmp_path)
    ws.write("test_app.py", "from unittest.mock import patch\nfrom app_module_name import add_todo_to_file_now\n\n"
             "@patch('app_module_name.add_todo_to_file_now')\ndef test_add_todo_appends_item_to_the_file(m):\n"
             "    add_todo_to_file_now('x')\n")
    (note,) = idiom_notes(ws)
    assert note.endswith("don't patch it.") and len(note) <= 200


RUN16_TEST = ("import unittest\nfrom todo import add_todo, list_todos\n\nclass T(unittest.TestCase):\n"
              "    def setUp(self):\n        global todos\n        todos = []\n\n"
              "    def test_a(self):\n        add_todo('x')\n")


def test_a_reset_of_the_tests_own_copy_is_named(tmp_path):
    from watchtower.floors.f2_dev.lint import idiom_notes
    ws = Workspace(tmp_path)
    ws.write("todo.py", "todos = []\n\ndef add_todo(i):\n    todos.append(i)\n\ndef list_todos():\n    return todos\n")
    ws.write("test_todo.py", RUN16_TEST)
    (note,) = idiom_notes(ws)
    assert "todo.todos" in note and "todo.todos.clear()" in note and len(note) <= 200


def test_a_global_the_test_really_owns_is_left_alone(tmp_path):
    from watchtower.floors.f2_dev.lint import idiom_notes
    ws = Workspace(tmp_path)
    ws.write("todo.py", "todos = []\n\ndef add_todo(i):\n    todos.append(i)\n\ndef list_todos():\n    return todos\n")
    ws.write("other.py", "seen = []\n")
    ws.write("test_todo.py", "todos = None\n" + RUN16_TEST)                             # its own top-level name
    ws.write("test_b.py", RUN16_TEST.replace("from todo import", "from other import seen  #").replace(
        "global todos\n        todos", "global seen2\n        seen2"))                   # nothing binds seen2
    assert idiom_notes(ws) == []


def test_global_reset_review_cases(tmp_path):
    from watchtower.floors.f2_dev.lint import idiom_notes
    app = "PORT = 8000\nserver = None\ntodos = []\n\ndef add_todo(i):\n    todos.append(i)\n"

    def notes(test):
        ws = Workspace(tmp_path / str(abs(hash(test))))
        ws.write("app.py", app)
        ws.write("test_app.py", test)
        return idiom_notes(ws)
    assert notes("from app import add_todo\ndef setUpModule():\n    global PORT, server\n    PORT = 1\n    server = 2\n") == []
    assert notes("import app\ndef setUp():\n    global todos\n    todos = app.todos\n    todos.clear()\n") == []
    assert notes("from app import add_todo\ndef setUp():\n    todos = []\n    def h():\n        global todos\n"
                 "        print(todos)\n") == []                                   # the inner scope only reads
    (n,) = notes("from app import add_todo, todos\ndef setUp():\n    global todos\n    todos = []\n")
    assert "app.todos.clear()" in n                                               # imported name: still the app's


def test_global_reset_note_keeps_its_advice_with_long_names(tmp_path):
    from watchtower.floors.f2_dev.lint import idiom_notes
    ws = Workspace(tmp_path)
    ws.write("myapp/storage_memory.py", "registered_users_list = {}\n")
    ws.write("tests_x/test_storage_backend.py", "from myapp.storage_memory import registered_users_list as r\n"
             "def setUp():\n    global registered_users_list\n    registered_users_list = {}\n")
    assert idiom_notes(ws) == []  # too long to say whole: no note rather than a cut (wrong) name
    ws.write("myapp/store.py", "users_list = {}\n")
    ws.write("tests_x/test_store.py", "from myapp.store import users_list as u\n"
             "def setUp():\n    global users_list\n    users_list = {}\n")
    (n,) = idiom_notes(ws)
    assert n.endswith("`myapp.store.users_list.clear()`.") and len(n) <= 200


def test_an_attribute_or_item_assignment_is_not_a_container_binding(tmp_path):
    from watchtower.floors.f2_dev.lint import idiom_notes
    ws = Workspace(tmp_path)
    ws.write("todo.py", "app = object()\napp.config = {}\nCACHE = {}\nCACHE['x'] = []\n")
    ws.write("test_todo.py", "from todo import app\ndef setUp():\n    global app\n    app = object()\n")
    assert idiom_notes(ws) == []
