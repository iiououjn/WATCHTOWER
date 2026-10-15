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
