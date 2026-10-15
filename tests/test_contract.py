"""Phase 6u: the deciding F4 checks come from the routes contract, not the small model (runs 18-21)."""
from watchtower.floors.f4_qa_deploy.contract import contract_checks
from runner_kit import app_tower  # noqa: F401 — pipeline fixture

TODO = [{"method": "GET", "path": "/", "fields": [], "shows": "List of all todo items."},
        {"method": "POST", "path": "/add", "fields": ["item"], "shows": "Confirmation message."}]
GUEST = [{"method": "GET", "path": "/", "fields": [], "shows": "Guestbook form and all submitted messages."},
         {"method": "POST", "path": "/submit", "fields": ["name", "message"], "shows": "Confirmation."}]


def test_add_then_list_for_each_field():
    checks, decide = contract_checks(GUEST, "k3f9a2")
    assert [(c["method"], c["path"]) for c in checks] == [("POST", "/submit"), ("GET", "/"), ("GET", "/")]
    assert checks[0]["form"] == {"name": "name k3f9a2", "message": "message k3f9a2"}
    assert [c["expect_text"] for c in checks[1:]] == ["name k3f9a2", "message k3f9a2"]
    assert all(c["name"].startswith("[tower] ") and c["expect_status"] == 200 for c in checks)
    assert decide == 2  # the POST and one shown value decide; other fields are advisory (6u review r1 C1)


def test_values_carry_a_space_so_hand_split_forms_fail():  # runs 19-20: split('=')[1]
    assert " " in contract_checks(TODO, "abc123")[0][0]["form"]["item"]


def test_destructive_routes_are_skipped():
    routes = [{"method": "POST", "path": "/delete", "fields": ["item"], "shows": ""},
              {"method": "POST", "path": "/toggle", "fields": ["todo"], "shows": ""},
              {"method": "POST", "path": "/save", "fields": ["id"], "shows": ""},
              {"method": "POST", "path": "/edit", "fields": ["todo_id", "text"], "shows": ""},
              {"method": "POST", "path": "/ping", "fields": [], "shows": ""}]
    assert contract_checks(routes, "k3f9a2") == ([], 0)


def test_the_list_page_is_the_first_get_route_without_fields():
    routes = [{"method": "GET", "path": "/todos", "fields": [], "shows": ""}] + TODO[1:]
    assert contract_checks(routes, "k3f9a2")[0][1]["path"] == "/todos"


def test_one_add_route_only():
    routes = [{"method": "POST", "path": f"/add{i}", "fields": ["item"], "shows": ""} for i in range(4)]
    assert len(contract_checks(routes, "k3f9a2")[0]) == 2


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
    runner, model, sandbox, job = app_tower({"f2.architect": [arch]}, qa_fn=lambda checks: [
        {"name": c["name"], "pass": c["name"].startswith("[tower]"), "status": 200, "detail": ""} for c in checks])
    out = runner.start(job.id, extra={"auto_approve": True})
    assert out.status == "done"
    coder = [p for c, p in zip(model.calls, model.prompts) if c == "f2.coder"]
    assert any("[tower] POST /add adds" in p for p in coder)
    gate = [p for c, p in zip(model.calls, model.prompts) if c == "f5.dev_gate"]
    assert gate and "small-model QA checks failed (advisory)" in gate[0]
    runner.close()


def test_typed_fields_get_plausible_values_and_never_decide():  # 6u review r1 C1
    routes = [{"method": "POST", "path": "/add", "fields": ["amount", "description", "due_date", "email", "done"],
               "shows": ""}]
    checks, decide = contract_checks(routes, "k3f9a2")
    assert checks[0]["form"] == {"amount": "3", "description": "description k3f9a2", "due_date": "2026-01-02",
                                 "email": "k3f9a2@example.com", "done": "on"}
    assert decide == 2 and checks[1]["expect_text"] == "description k3f9a2"


def test_only_adding_routes_count():  # 6u review r1 I1
    routes = [{"method": "POST", "path": "/login", "fields": ["username", "password"], "shows": ""},
              {"method": "POST", "path": "/search", "fields": ["q"], "shows": ""},
              {"method": "POST", "path": "/vote", "fields": ["choice"], "shows": ""}]
    assert contract_checks(routes, "k3f9a2") == ([], 0)


def test_a_route_with_only_typed_fields_does_not_decide():
    assert contract_checks([{"method": "POST", "path": "/add", "fields": ["amount"], "shows": ""}], "t") == ([], 0)
    assert contract_checks([{"method": "POST", "path": "/add", "fields": ["message"], "shows": ""}], "t")[1] == 2


def test_the_list_page_is_the_get_that_shows_the_list():  # 6u review r1 I2
    routes = [{"method": "GET", "path": "/", "fields": [], "shows": "A form to sign the guestbook"},
              {"method": "GET", "path": "/entries", "fields": [], "shows": "All messages"},
              {"method": "POST", "path": "/sign", "fields": ["message"], "shows": ""}]
    assert contract_checks(routes, "k3f9a2")[0][1]["path"] == "/entries"


def test_long_names_are_cut_not_replaced_by_the_path():  # 6u review r1 M3
    routes = [{"method": "POST", "path": "/add/" + "x" * 60, "fields": ["item"], "shows": ""}]
    assert all(c["name"].startswith("[tower] ") for c in contract_checks(routes, "k3f9a2")[0])


def test_f4_runs_a_fresh_token_the_coder_never_saw(app_tower):  # 6u review r1 I3
    import json
    from conftest import APP_REPLIES
    arch = dict(APP_REPLIES["f2.architect"][0])
    arch["routes"] = arch["routes"] + [{"method": "POST", "path": "/add", "fields": ["item"], "shows": "added"}]
    runner, model, sandbox, job = app_tower({"f2.architect": [arch]})
    runner.start(job.id, extra={"auto_approve": True})
    coder = [p for c, p in zip(model.calls, model.prompts) if c == "f2.coder"]
    shown = json.loads(next(c[4] for c in sandbox.calls if "WATCHTOWER_QA" in c[2]))[0]["form"]["item"]
    assert any(f"item {job.id[:6]}" in p for p in coder) and job.id[:6] not in shown and shown.startswith("item ")
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
    runner, model, sandbox, job = app_tower({"f2.architect": [arch], "f4.qa": [{"checks": []}]})
    assert runner.start(job.id, extra={"auto_approve": True}).status == "done"
    runner.close()
