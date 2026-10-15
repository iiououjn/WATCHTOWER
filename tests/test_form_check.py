"""Phase 6w: the tower checks the list page offers a real form (run 25: text/plain, no form, passed F4),
and classifies contract fields by their name parts (run 24: 'new_item' got no tower checks)."""
from watchtower.floors.f4_qa_deploy.contract import contract_checks
from watchtower.floors.f4_qa_deploy.qafloor import parse_checks
from test_qafloor import ECHO_APP, _live

LIST = {"method": "GET", "path": "/", "fields": [], "shows": "all items"}
FORM = '<form method="post" action="/add"><input name="item"><button>Add</button></form>'


def _form_check(tmp_path, app):
    checks = parse_checks({"checks": [{"name": "form", "path": "/", "expect_text": "",
                                       "expect_form": {"action": "/add", "fields": ["item"]}}]})
    return _live(tmp_path, app, checks).checks_run[-1]


def test_a_page_with_the_form_passes(tmp_path):
    app = ECHO_APP.replace('self.wfile.write(("<ul>"', f"self.wfile.write(('{FORM}' + \"<ul>\"")
    assert app != ECHO_APP and _form_check(tmp_path, app)["pass"] is True


def test_a_page_without_the_form_fails_and_says_why(tmp_path):  # run 25
    result = _form_check(tmp_path, ECHO_APP)
    assert result["pass"] is False and "<form" in result["results"][0]["detail"]


def test_a_get_form_or_wrong_field_fails(tmp_path):
    for bad in (FORM.replace('method="post"', 'method="get"'), FORM.replace('name="item"', 'name="text"')):
        app = ECHO_APP.replace('self.wfile.write(("<ul>"', f"self.wfile.write(('{bad}' + \"<ul>\"")
        assert _form_check(tmp_path, app)["pass"] is False, bad


def test_expect_form_is_kept_only_when_valid():
    ok = parse_checks({"checks": [{"name": "f", "path": "/", "expect_form": {"action": "/add", "fields": ["item"]}}]})
    assert ok[0]["expect_form"] == {"action": "/add", "fields": ["item"]}
    for bad in ({"action": "http://evil/", "fields": ["item"]}, {"action": "/add", "fields": ["a b"]}, "x"):
        assert "expect_form" not in parse_checks({"checks": [{"name": "f", "path": "/", "expect_form": bad}]})[0]
    assert "expect_form" not in parse_checks({"checks": [{"name": "f", "path": "/"}]})[0]


def test_the_form_check_decides_first():
    checks, decide = contract_checks([LIST, {"method": "POST", "path": "/add", "fields": ["item"], "shows": ""}], "1")
    assert decide == 3 and checks[0]["expect_form"] == {"action": "/add", "fields": ["item"]}
    assert [c["method"] for c in checks] == ["GET", "POST", "GET"]


def test_fields_are_classified_by_name_parts():  # run 24: new_item
    def tower(fields):
        return contract_checks([LIST, {"method": "POST", "path": "/add", "fields": fields, "shows": ""}], "1")[1]
    assert tower(["new_item"]) == tower(["user_name", "messageText"]) == 3
    assert tower(["item_count"]) == tower(["dueDate"]) == tower(["todo_id"]) == 0


def _with(page_html):
    return ECHO_APP.replace('self.wfile.write(("<ul>"', f"self.wfile.write(('{page_html}' + \"<ul>\"")


def test_a_relative_or_slashed_action_counts(tmp_path):  # 6w review r1 #2, #6
    for action in ("add", "./add", "/add/", "http://127.0.0.1/add?x=1"):
        assert _form_check(tmp_path, _with(FORM.replace('action="/add"', f'action="{action}"')))["pass"] is True, action


def test_inputs_after_the_form_closed_do_not_count(tmp_path):  # 6w review r1 #4
    page = '<form method="post" action="/add"><button>Add</button></form><input name="item">'
    assert _form_check(tmp_path, _with(page))["pass"] is False


def test_broken_html_fails_the_check_not_the_run(tmp_path):  # 6w review r1 #5
    page = '<![if !IE]><form method="post" action="/add"><input name="item"></form>'
    result = _form_check(tmp_path, _with(page))
    assert result["results"][0]["name"] == "form"  # the run printed its result line


def test_the_form_check_runs_on_the_form_page_when_there_is_one():  # 6w review r1 #1
    routes = [LIST, {"method": "GET", "path": "/new", "fields": [], "shows": "a form to add an item"},
              {"method": "POST", "path": "/add", "fields": ["item"], "shows": ""}]
    checks, decide = contract_checks(routes, "1")
    assert checks[0]["path"] == "/new" and checks[2]["path"] == "/"


def test_compound_typed_fields_are_not_text():  # 6w review r1 #3
    def tower(fields):
        return contract_checks([LIST, {"method": "POST", "path": "/add", "fields": fields, "shows": ""}], "1")[1]
    assert tower(["item_name", "item_cost"]) == tower(["task_deadline"]) == tower(["note_color"]) == 0
    assert tower(["new_item"]) == tower(["user_name"]) == tower(["first_name", "message"]) == 3


def test_the_form_page_belongs_to_the_add_route():  # 6w review r2 #1, #2
    edit = {"method": "GET", "path": "/edit", "fields": [], "shows": "shows the edit form"}
    search = {"method": "GET", "path": "/search", "fields": [], "shows": "a search form"}
    add = {"method": "POST", "path": "/add", "fields": ["item"], "shows": ""}
    assert contract_checks([LIST, edit, search, add], "1")[0][0]["path"] == "/"
    new = {"method": "GET", "path": "/new", "fields": ["item"], "shows": "form to add an item"}
    assert contract_checks([LIST, edit, new, add], "1")[0][0]["path"] == "/new"
    same = {"method": "GET", "path": "/add", "fields": [], "shows": "the add page"}
    assert contract_checks([LIST, new, same, add], "1")[0][0]["path"] == "/add"


REDIRECT_APP = """
import os
from http.server import BaseHTTPRequestHandler, HTTPServer
class H(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/":
            self.send_response(302); self.send_header("Location", "/g/"); self.end_headers(); return
        self.send_response(200); self.end_headers()
        self.wfile.write(b'<form method="post" action="add"><input name="item"></form>')
    def log_message(self, *a):
        pass
HTTPServer(("127.0.0.1", int(os.environ["PORT"])), H).serve_forever()
"""


def test_relative_actions_resolve_against_the_page_reached(tmp_path):  # 6w review r2 #3
    def run(action):
        checks = parse_checks({"checks": [{"name": "form", "path": "/", "expect_text": "",
                                           "expect_form": {"action": action, "fields": ["item"]}}]})
        return _live(tmp_path, REDIRECT_APP, checks).checks_run[-1]["pass"]
    assert run("/g/add") is True and run("/add") is False


def test_a_query_in_the_contract_action_is_ignored(tmp_path):  # 6w review r2 #5
    checks = parse_checks({"checks": [{"name": "form", "path": "/", "expect_text": "",
                                       "expect_form": {"action": "/add?list=1", "fields": ["item"]}}]})
    assert _live(tmp_path, _with(FORM), checks).checks_run[-1]["pass"] is True


def test_a_nested_form_tag_is_ignored_like_a_browser(tmp_path):  # 6w review r2 #4
    page = '<form method="get" action="/search"><form method="post" action="/add"><input name="item"></form>'
    assert _form_check(tmp_path, _with(page))["pass"] is False
