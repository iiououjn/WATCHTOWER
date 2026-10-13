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
    assert "app.py" in p and "self.todo_list" in p and "new handler per request" in p and p.endswith("in a file.")
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
    assert pkg.checks_run[-1]["pass"] is False and "new handler per request" in s.prompts["f2.coder"][1]
