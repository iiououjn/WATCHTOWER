"""Phase 6t: QA text glued from several page pieces (runs 18-19) and a board line that names the failures."""
from watchtower.floors.f4_qa_deploy.qafloor import parse_checks
from test_qafloor import ECHO_APP, _live

ADD = [{"name": "add milk", "method": "POST", "path": "/add", "form": {"item": "milk"}, "expect_text": ""},
       {"name": "add eggs", "method": "POST", "path": "/add", "form": {"item": "eggs"}, "expect_text": ""}]


def _list(tmp_path, want, app=ECHO_APP):
    checks = parse_checks({"checks": ADD + [{"name": "list", "path": "/", "expect_text": want}]})
    return _live(tmp_path, app, checks).checks_run[-1]


def test_pieces_glued_with_markup_pass_when_each_is_on_the_page(tmp_path):  # run 18: whole-page HTML
    assert _list(tmp_path, "<ul>\n  <li>milk</li>\n  <li>eggs</li>\n</ul>")["pass"] is True


def test_pieces_glued_with_newlines_pass_when_each_is_on_the_page(tmp_path):  # run 19: 'Bob: Hi\nCharlie: ...'
    assert _list(tmp_path, "milk\neggs")["pass"] is True


def test_a_missing_piece_still_fails(tmp_path):
    assert _list(tmp_path, "milk\nbread")["pass"] is False


def test_a_page_that_escapes_its_own_tags_still_fails_a_markup_check(tmp_path):
    app = ECHO_APP.replace('self.wfile.write(("<ul>"', 'self.wfile.write(html.escape("<ul>"')
    assert _list(tmp_path, "<li>milk</li><li>eggs</li>", app)["pass"] is False


def test_the_board_line_names_the_failing_checks():  # runs 17-19: the board said only 'QA checks FAILED:'
    from watchtower.floors.f4_qa_deploy.qafloor import qa_headline
    results = [{"name": "home", "pass": True, "detail": ""},
               {"name": "add", "pass": False, "detail": "RemoteDisconnected: Remote end closed connection" + "x" * 300},
               {"name": "list", "pass": False, "detail": "expected 200 with 'Bob', got 200: <ul></ul>"}]
    line = qa_headline(results)
    assert line.startswith("QA checks FAILED (2/3): add: RemoteDisconnected") and "list: expected 200" in line
    assert len(line) <= 300 and qa_headline([{"name": "a", "pass": True}]) == "QA checks passed (1/1)"


def test_pieces_must_be_visible_text_not_attributes_or_title(tmp_path):  # 6t review r1 #1
    app = ECHO_APP.replace('self.wfile.write(("<ul>" + "".join(f"<li>{i}</li>" for i in ITEMS) + "</ul>").encode())',
                           'self.wfile.write(("<title>" + " ".join(ITEMS) + "</title><h1>Todo</h1>"\n'
                           '                          "<input name=item value=" + " ".join(ITEMS) + "><ul></ul>").encode())')
    assert app != ECHO_APP
    assert _list(tmp_path, "<h1>Todo</h1><ul><li>milk</li></ul>", app)["pass"] is False


def test_a_page_escaping_only_its_brackets_fails_a_markup_check(tmp_path):  # 6t review r1 #2
    app = ECHO_APP.replace('self.wfile.write(("<ul>" + "".join(f"<li>{i}</li>" for i in ITEMS) + "</ul>").encode())',
                           'self.wfile.write("".join(f"&lt;li>{i}&lt;/li>" for i in ITEMS).encode())')
    assert app != ECHO_APP
    assert _list(tmp_path, "<li>milk</li><li>eggs</li>", app)["pass"] is False


PAGE = 'self.wfile.write(("<ul>" + "".join(f"<li>{i}</li>" for i in ITEMS) + "</ul>").encode())'


def _page(html_expr):
    return ECHO_APP.replace(PAGE, f"self.wfile.write(({html_expr}).encode())")


def test_a_piece_must_be_a_whole_text_node(tmp_path):  # 6t review r2 A: '1' found in '+1', 'eggs' in 'Added eggs'
    count = _list(tmp_path, "<p>Count: <span>2</span></p>",  # computed text: advisory since 7b, the row still fails
                  _page('"<p>Count: <span>0</span></p><button>+2</button>"'))
    assert count["results"][-1]["pass"] is False and count["results"][-1].get("advisory") is True
    assert _list(tmp_path, "<li>milk</li><li>eggs</li>",
                 _page('"<ul><li>milk</li></ul><p>Added eggs</p>"'))["pass"] is False


def test_commented_out_markup_is_not_shown(tmp_path):  # 6t review r2 C
    assert _list(tmp_path, "<li>milk</li><li>eggs</li>",
                 _page('"<!-- <li>milk</li><li>eggs</li> --><ul></ul>"'))["pass"] is False


def test_a_double_escaped_page_fails(tmp_path):  # 6t review r2 B
    assert _list(tmp_path, "<li>milk</li><li>eggs</li>",
                 _page('html.escape(html.escape("<ul>" + "".join(f"<li>{i}</li>" for i in ITEMS) + "</ul>"))'))[
        "pass"] is False


def test_the_board_line_says_when_the_run_itself_failed():  # 6t review r2 D: timed out after all checks passed
    from watchtower.floors.f4_qa_deploy.qafloor import qa_headline
    assert qa_headline([{"name": "a", "pass": True}], passed=False).startswith("QA checks FAILED (0/1): the QA run")
