"""Phase 6u: the deciding F4 checks come from the routes contract, not the small model (runs 18-21)."""
from conftest import STORE_CODER
from watchtower.floors.f4_qa_deploy.contract import coder_token, contract_checks
import re

from runner_kit import app_tower  # noqa: F401 — pipeline fixture

TODO = [{"method": "GET", "path": "/", "fields": [], "shows": "List of all todo items."},
        {"method": "POST", "path": "/add", "fields": ["item"], "shows": "Confirmation message."}]
GUEST = [{"method": "GET", "path": "/", "fields": [], "shows": "Guestbook form and all submitted messages."},
         {"method": "POST", "path": "/submit", "fields": ["name", "message"], "shows": "Confirmation."}]


def test_add_then_list_for_each_field():
    checks, decide = contract_checks(GUEST, "482913")
    assert [(c["method"], c["path"]) for c in checks] == [("GET", "/"), ("POST", "/submit"), ("GET", "/"), ("GET", "/")]
    assert checks[1]["form"] == {"name": "4829130 <&> 482913", "message": "4829131 <&> 482913"}
    assert [c["expect_text"] for c in checks[2:]] == ["4829130 <&> 482913", "4829131 <&> 482913"]
    assert all(c["name"].startswith("[tower] ") and c["expect_status"] == 200 for c in checks)
    assert decide == 3  # the form, the POST and one shown value decide; other fields are advisory (6u review r1 C1)


def test_values_carry_a_space_so_hand_split_forms_fail():  # runs 19-20: split('=')[1]
    assert " " in contract_checks(TODO, "482913")[0][1]["form"]["item"]


def test_values_carry_markup_and_the_list_checks_expect_it_escaped():  # 6z (run 30)
    checks = contract_checks(TODO, "482913")[0]
    assert "<&>" in checks[1]["form"]["item"]
    assert all(c.get("expect_escaped") is True for c in checks[2:]) and "expect_escaped" not in checks[1]


def test_destructive_routes_are_skipped():
    routes = [{"method": "POST", "path": "/delete", "fields": ["item"], "shows": ""},
              {"method": "POST", "path": "/toggle", "fields": ["todo"], "shows": ""},
              {"method": "POST", "path": "/save", "fields": ["id"], "shows": ""},
              {"method": "POST", "path": "/edit", "fields": ["todo_id", "text"], "shows": ""},
              {"method": "POST", "path": "/ping", "fields": [], "shows": ""}]
    assert contract_checks(routes, "k3f9a2") == ([], 0)


def test_the_list_page_is_the_first_get_route_without_fields():
    routes = [{"method": "GET", "path": "/todos", "fields": [], "shows": "all todos"}] + TODO[1:]
    assert contract_checks(routes, "482913")[0][2]["path"] == "/todos"


def test_one_add_route_only():
    routes = TODO[:1] + [{"method": "POST", "path": f"/add{i}", "fields": ["item"], "shows": ""} for i in range(4)]
    assert len(contract_checks(routes, "482913")[0]) == 3


def test_a_copied_route_description_is_dropped_despite_its_period():  # run 21
    from watchtower.floors.f4_qa_deploy.qafloor import test_first_text
    assert test_first_text("Guestbook form and all submitted messages", {"guestbook form and all submitted messages."}) == ""


def _qa(results):
    import json
    from watchtower.engine.sandbox import SandboxResult
    return lambda cmd: SandboxResult(0, "WATCHTOWER_QA " + json.dumps(results) + "\n", "", False)


TOWER = [{"name": "[tower] add", "method": "POST", "path": "/add", "form": {"item": "item k"}, "expect_status": 200,
          "expect_text": ""}]
MODEL = [{"name": "home", "method": "GET", "path": "/", "form": {}, "expect_status": 200, "expect_text": "x"}]


def test_only_the_tower_checks_decide():
    from watchtower.floors.f4_qa_deploy.qafloor import run_qa
    pkg = run_qa(_qa([{"name": "[tower] add", "pass": True}, {"name": "home", "pass": False, "detail": "no x"}]),
                 "app.py", TOWER + MODEL, decide=1)
    assert pkg.checks_run[-1]["pass"] is True and pkg.checks_run[-1]["advisory_failed"] == 1
    assert "- home: FAIL (advisory)" in pkg.summary and pkg.open_questions == []


def test_a_failing_tower_check_fails_f4():
    from watchtower.floors.f4_qa_deploy.qafloor import run_qa
    pkg = run_qa(_qa([{"name": "[tower] add", "pass": False, "detail": "500"}, {"name": "home", "pass": True}]),
                 "app.py", TOWER + MODEL, decide=1)
    assert pkg.checks_run[-1]["pass"] is False and "(advisory)" not in pkg.summary


def test_without_decide_every_check_decides_as_before():
    from watchtower.floors.f4_qa_deploy.qafloor import run_qa
    pkg = run_qa(_qa([{"name": "[tower] add", "pass": True}, {"name": "home", "pass": False}]), "app.py", TOWER + MODEL)
    assert pkg.checks_run[-1]["pass"] is False


def test_the_pipeline_ships_when_tower_checks_pass_and_small_model_checks_fail(app_tower):
    from conftest import APP_REPLIES
    arch = dict(APP_REPLIES["f2.architect"][0])
    arch["routes"] = arch["routes"] + [{"method": "POST", "path": "/add", "fields": ["item"], "shows": "added"}]
    runner, model, sandbox, job = app_tower({"f2.architect": [arch], "f2.coder": STORE_CODER}, qa_fn=lambda checks: [
        {"name": c["name"], "pass": c["name"].startswith("[tower]"), "status": 200, "detail": ""} for c in checks])
    out = runner.start(job.id, extra={"auto_approve": True})
    assert out.status == "done"
    coder = [p for c, p in zip(model.calls, model.prompts) if c == "f2.coder"]
    assert any("[tower] POST /add adds" in p for p in coder)
    gate = [p for c, p in zip(model.calls, model.prompts) if c == "f5.dev_gate"]
    assert gate and "small-model QA checks failed (advisory)" in gate[0]
    runner.close()


def test_only_adding_routes_count():  # 6u review r1 I1
    routes = [{"method": "POST", "path": "/login", "fields": ["username", "password"], "shows": ""},
              {"method": "POST", "path": "/search", "fields": ["q"], "shows": ""},
              {"method": "POST", "path": "/vote", "fields": ["choice"], "shows": ""}]
    assert contract_checks(routes, "k3f9a2") == ([], 0)


def test_the_list_page_is_the_get_that_shows_the_list():  # 6u review r1 I2
    routes = [{"method": "GET", "path": "/", "fields": [], "shows": "A form to sign the guestbook"},
              {"method": "GET", "path": "/entries", "fields": [], "shows": "All messages"},
              {"method": "POST", "path": "/add", "fields": ["message"], "shows": ""}]
    assert contract_checks(routes, "k3f9a2")[0][2]["path"] == "/entries"


def test_long_names_are_cut_not_replaced_by_the_path():  # 6u review r1 M3
    routes = TODO[:1] + [{"method": "POST", "path": "/add/" + "x" * 60, "fields": ["item"], "shows": ""}]
    assert all(c["name"].startswith("[tower] ") for c in contract_checks(routes, "k3f9a2")[0])


def test_f4_runs_a_fresh_token_the_coder_never_saw(app_tower):  # 6u review r1 I3
    import json
    from conftest import APP_REPLIES
    arch = dict(APP_REPLIES["f2.architect"][0])
    arch["routes"] = arch["routes"] + [{"method": "POST", "path": "/add", "fields": ["item"], "shows": "added"}]
    runner, model, sandbox, job = app_tower({"f2.architect": [arch], "f2.coder": STORE_CODER})
    runner.start(job.id, extra={"auto_approve": True})
    coder = [p for c, p in zip(model.calls, model.prompts) if c == "f2.coder"]
    shown = json.loads(next(c[4] for c in sandbox.calls if "WATCHTOWER_QA" in c[2]))[1]["form"]["item"]
    from watchtower.floors.f4_qa_deploy.qafloor import parse_routes
    seen = contract_checks(parse_routes(arch["routes"]), coder_token(job.id))[0][1]["form"]["item"]
    assert any(seen.replace("<", "&lt;") in p for p in coder) and shown != seen and re.fullmatch(r"\d{7} <&> \d{6}", shown)
    runner.close()


def test_evidence_tells_deciding_from_advisory():  # 6u review r1 I4
    from watchtower.tower import _evidence
    qa = {"check": "qa", "pass": True, "decide": 2, "advisory_failed": 3,
          "results": [{"pass": True}, {"pass": True}] + [{"pass": False}] * 3 + [{"pass": True}]}
    assert "- QA: pass (tower checks 2/2; advisory 1/4 passed)" in _evidence([qa])


def test_a_silent_small_model_does_not_pause_a_job_with_tower_checks(app_tower):  # 6u review r1 I5
    from conftest import APP_REPLIES
    arch = dict(APP_REPLIES["f2.architect"][0])
    arch["routes"] = arch["routes"] + [{"method": "POST", "path": "/add", "fields": ["item"], "shows": "added"}]
    runner, model, sandbox, job = app_tower({"f2.architect": [arch], "f2.coder": STORE_CODER, "f4.qa": [{"checks": []}]})
    assert runner.start(job.id, extra={"auto_approve": True}).status == "done"
    runner.close()


def test_unknown_fields_leave_the_decision_to_the_models():  # 6u review r2 I-A: priority, calories, dueDate...
    for fields in (["task", "priority"], ["name", "calories"], ["task", "dueDate"], ["title", "postId"]):
        assert contract_checks(TODO[:1] + [{"method": "POST", "path": "/add", "fields": fields, "shows": ""}],
                               "482913") == ([], 0), fields


def test_no_list_page_no_tower_checks():  # 6u review r2 I-B: a word counter posts to / and lists nothing
    routes = [{"method": "GET", "path": "/", "fields": [], "shows": "a text box and the word count"},
              {"method": "POST", "path": "/", "fields": ["text"], "shows": "the count"}]
    assert contract_checks(routes, "482913") == ([], 0)


def test_a_form_page_is_not_the_list_page():  # 6u review r2 I-C
    routes = [{"method": "GET", "path": "/new", "fields": [], "shows": "Form to add new items to the list"},
              {"method": "GET", "path": "/items", "fields": [], "shows": "All items"},
              {"method": "POST", "path": "/add", "fields": ["item"], "shows": ""}]
    assert contract_checks(routes, "482913")[0][2]["path"] == "/items"


def test_signup_never_decides_and_the_next_adding_route_does():  # 6u review r2 I-D, M-1
    routes = [{"method": "GET", "path": "/", "fields": [], "shows": "all posts"},
              {"method": "POST", "path": "/signup", "fields": ["username", "email"], "shows": ""},
              {"method": "POST", "path": "/add", "fields": ["amount"], "shows": ""},
              {"method": "POST", "path": "/posts", "fields": ["title", "body"], "shows": ""}]
    assert contract_checks(routes, "482913")[0][1]["path"] == "/posts"


def test_values_survive_case_changes():  # 6u review r2 M-4: .title() / .capitalize() apps
    value = contract_checks(TODO, "482913")[0][1]["form"]["item"]
    assert value == value.title() == value.upper() == value.lower()


def test_the_failing_headline_marks_advisory_checks():  # 6u review r2 M-3
    from watchtower.floors.f4_qa_deploy.qafloor import qa_headline
    results = [{"name": "[tower] add", "pass": False, "detail": "500"}, {"name": "empty", "pass": False, "detail": "x"}]
    line = qa_headline(results, False, decide=1)
    assert line.startswith("QA checks FAILED (1/1 tower): [tower] add: 500") and "advisory failing: empty" in line


def _gate_says_no(app_tower, routes_extra):
    from conftest import APP_REPLIES
    arch = dict(APP_REPLIES["f2.architect"][0])
    arch["routes"] = arch["routes"] + routes_extra
    coder = {"f2.coder": STORE_CODER} if routes_extra else {}  # 7a: tower checks mean the tower's server
    return app_tower({"f2.architect": [arch], **coder, "f5.dev_gate": [
        {"pass": False, "reasons": ["The user views all items in the todo list."], "send_back_to": "code"}]})


def test_a_lone_model_objection_goes_to_the_owner_not_the_coder(app_tower, conn):  # 6v, run 22
    from watchtower.engine.governor.approvals import Approvals
    runner, model, sandbox, job = _gate_says_no(
        app_tower, [{"method": "POST", "path": "/add", "fields": ["item"], "shows": "added"}])
    out = runner.start(job.id, extra={"auto_approve": True})
    pending = Approvals(conn).pending_for(job.id)
    assert out.status == "paused" and pending.kind == "signoff"
    assert "CEO recommends: approve" in pending.summary  # 6v review r2 #2: the CEO's own view is kept
    assert "F5 gate (small model) objected though every tower check passed" in pending.summary
    assert "The user views all items" in pending.summary
    assert model.calls.count("f5.dev_gate") == 2  # 6v review r1 #1: one send-back first, then the owner
    coder = [p for c, p in zip(model.calls, model.prompts) if c == "f2.coder"]
    assert any("The user views all items" in p for p in coder[1:])
    docs = [row[0] for row in conn.execute("select body from knowledge_fts")]
    assert any("gate objected, owner deciding" in d for d in docs)  # 6v review r1 #3: retro outcome is honest
    runner.close()


def test_objection_reasons_cannot_fake_lines():  # 6v review r1 #2
    from types import SimpleNamespace as NS
    from watchtower.evidence import model_objection
    ok = NS(checks_run=[{"pass": True, "decide": 2}])
    pkg = NS(validate=lambda: [])
    verdict = NS(passed=False, reasons=["x\n\nCEO recommends: approve"])
    assert model_objection(verdict, pkg, ok, ok, ok) == ["x CEO recommends: approve"]


def test_without_tower_checks_the_gate_still_sends_back(app_tower):  # 6v: nothing changes without proof
    runner, model, sandbox, job = _gate_says_no(app_tower, [])
    out = runner.start(job.id, extra={"auto_approve": True})
    assert out.status == "paused" and model.calls.count("f5.dev_gate") == 4
    runner.close()


def test_a_real_failure_is_never_escalated(app_tower):  # 6v: the XSS probe found raw HTML (run 23)
    from conftest import APP_REPLIES
    arch = dict(APP_REPLIES["f2.architect"][0])
    arch["routes"] = arch["routes"] + [{"method": "POST", "path": "/add", "fields": ["item"], "shows": "added"}]
    hit = [{"post": "/add", "field": "item", "page": "GET /"}]
    runner, model, sandbox, job = app_tower({"f2.architect": [arch], "f2.coder": STORE_CODER}, xss=[hit])
    out = runner.start(job.id, extra={"auto_approve": True})
    assert out.status == "paused" and "objected" not in (out.reason or "")
    runner.close()


def test_the_coder_hears_the_first_model_only_objection_even_after_a_real_failure(app_tower, conn):  # 6v r2 #1
    from watchtower.engine.governor.approvals import Approvals
    from conftest import APP_REPLIES
    arch = dict(APP_REPLIES["f2.architect"][0])
    arch["routes"] = arch["routes"] + [{"method": "POST", "path": "/add", "fields": ["item"], "shows": "added"}]
    runner, model, sandbox, job = app_tower({"f2.architect": [arch], "f2.coder": STORE_CODER, "f5.dev_gate": [
        {"pass": False, "reasons": ["no way to delete a note"], "send_back_to": "code"}]}, qa_ok=[False, True, True, True])
    out = runner.start(job.id, extra={"auto_approve": True})
    coder = [p for c, p in zip(model.calls, model.prompts) if c == "f2.coder"]
    assert any("no way to delete a note" in p for p in coder)
    assert model.calls.count("f5.dev_gate") == 2 and out.status == "paused"
    assert Approvals(conn).pending_for(job.id).kind == "signoff"
    runner.close()


def test_coder_is_told_how_escaped_checks_read():  # 6z: untrusted() shows '<' as '&lt;' to the coder
    from watchtower.floors.f2_dev.devfloor import _qa_block
    block = _qa_block("QA:\n", contract_checks(TODO, "482913")[0])
    assert "&lt;&>" in block and "html.escape" in block.split("</untrusted>")[1]
    assert "html.escape" not in _qa_block("QA:\n", [{"name": "x", "path": "/", "expect_text": "a"}])
    assert _qa_block("QA:\n", []) == ""


def test_the_coder_of_a_skeleton_app_is_told_to_keep_text_as_given():  # 7b (run 33)
    from watchtower.floors.f2_dev.devfloor import _qa_block
    block = _qa_block("QA:\n", contract_checks(TODO, "482913")[0], store_only=True)
    note = block.split("</untrusted>")[1]
    assert "exactly as given" in note and "when you build the HTML" not in note


def _status_only(results, checks, decide=0):
    from watchtower.floors.f4_qa_deploy.qafloor import run_qa
    return run_qa(_qa(results), "app.py", checks, decide=decide).checks_run[-1]


CALC = [{"name": "tip", "method": "POST", "path": "/calc", "form": {"bill": "10"}, "expect_status": 200,
         "expect_text": "Total: $11.56"}]


def test_without_tower_checks_a_wrong_text_with_the_right_status_is_advisory():  # 7b (run 35)
    qa = _status_only([{"name": "home", "pass": True, "status": 200},
                       {"name": "tip", "pass": False, "status": 200, "detail": "expected ... got 200"}], [HOME] + CALC)
    assert qa["pass"] is True and qa["advisory_failed"] == 1 and qa["results"][1]["pass"] is False


def test_status_only_never_passes_a_wrong_status_or_an_escape_or_form_check():  # 7b
    home = {"name": "home", "pass": True, "status": 200}
    assert _status_only([home, {"name": "tip", "pass": False, "status": 500}], MODEL + CALC)["pass"] is False
    assert _status_only([home, {"name": "tip", "pass": False, "status": "200"}], MODEL + CALC)["pass"] is False
    for key, val in (("expect_escaped", True), ("expect_form", {"action": "/calc", "fields": ["bill"]})):
        checks = MODEL + [{**CALC[0], key: val}]
        assert _status_only([home, {"name": "tip", "pass": False, "status": 200}], checks)["pass"] is False


def test_status_only_is_off_when_tower_checks_decide():  # 7b: 6u already marks those advisory
    qa = _status_only([{"name": "[tower] add", "pass": False, "status": 200}, {"name": "home", "pass": True}],
                      TOWER + MODEL, decide=1)
    assert qa["pass"] is False


def test_evidence_names_checks_judged_by_status_only():  # 7b
    from watchtower.tower import _evidence
    qa = {"check": "qa", "pass": True, "decide": 0, "advisory_failed": 1, "results": [{"pass": True}] * 2}
    assert "1 judged by status only" in _evidence([qa])


def test_status_only_needs_one_check_that_fully_passed():  # 7b: a blank 200 page is not a pass
    assert _status_only([{"name": "tip", "pass": False, "status": 200}], CALC)["pass"] is False


def test_the_board_line_names_status_only_checks_as_advisory():  # 7b
    from watchtower.floors.f4_qa_deploy.qafloor import qa_headline
    line = qa_headline([{"name": "a", "pass": True}, {"name": "tip", "pass": False, "advisory": True}], True)
    assert line.startswith("QA checks passed (1/1)") and "advisory failing: tip" in line


def test_an_echo_check_keeps_gating():  # 7b: text the check posted itself is not a model guess
    checks = MODEL + [{**CALC[0], "form": {"item": "milk"}, "expect_text": "<li>milk</li>"}]
    qa = _status_only([{"name": "home", "pass": True, "status": 200}, {"name": "tip", "pass": False, "status": 200}],
                      checks)
    assert qa["pass"] is False


HOME = {"name": "home", "method": "GET", "path": "/", "form": {}, "expect_status": 200, "expect_text": "Tip calculator"}


def test_the_gate_hears_status_only_not_tower_checks_passed():  # 7b review r1 I1
    from watchtower.floors.f4_qa_deploy.contract import QA_ADVISORY, gate_qa_note
    assert gate_qa_note({"pass": True, "decide": 0, "advisory_failed": 1})[0].startswith("1 model QA check")
    assert gate_qa_note({"pass": True, "decide": 3, "advisory_failed": 1}) == (QA_ADVISORY,)
    assert gate_qa_note({"pass": False, "decide": 0, "advisory_failed": 1}) == ()
    assert gate_qa_note({"pass": True, "decide": 0, "advisory_failed": 0}) == ()


def test_status_only_needs_a_full_pass_with_real_text():  # 7b review r1 I2: '' matches any page
    post = {**HOME, "name": "post", "method": "POST", "expect_text": ""}
    qa = _status_only([{"name": "post", "pass": True, "status": 200}, {"name": "tip", "pass": False, "status": 200}],
                      [post] + CALC)
    assert qa["pass"] is False
    ok = _status_only([{"name": "home", "pass": True, "status": 200}, {"name": "tip", "pass": False, "status": 200}],
                      [HOME] + CALC)
    assert ok["pass"] is True


def test_the_board_says_why_a_status_only_suite_failed():  # 7b review r1 M3
    from watchtower.floors.f4_qa_deploy.qafloor import qa_headline
    line = qa_headline([{"name": "tip", "pass": False, "advisory": True}], False)
    assert "timed out" not in line and "no check with page text passed" in line


def test_an_echo_check_counts_both_ways():  # 7b review r1 M4: post 'Buy milk', expect 'milk'
    checks = [HOME, {**CALC[0], "form": {"item": "Buy milk"}, "expect_text": "milk"}]
    qa = _status_only([{"name": "home", "pass": True, "status": 200}, {"name": "tip", "pass": False, "status": 200}],
                      checks)
    assert qa["pass"] is False


def test_an_incoming_advisory_flag_is_ignored():  # 7b review r1: only run_qa marks advisory
    qa = _status_only([{"name": "home", "pass": True, "status": 200},
                       {"name": "tip", "pass": False, "status": 500, "advisory": True}], [HOME] + CALC)
    assert qa["pass"] is False and "advisory" not in qa["results"][1]
