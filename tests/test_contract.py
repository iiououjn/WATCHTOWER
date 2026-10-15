"""Phase 6u: the deciding F4 checks come from the routes contract, not the small model (runs 18-21)."""
from watchtower.floors.f4_qa_deploy.contract import contract_checks
from runner_kit import app_tower  # noqa: F401 — pipeline fixture

TODO = [{"method": "GET", "path": "/", "fields": [], "shows": "List of all todo items."},
        {"method": "POST", "path": "/add", "fields": ["item"], "shows": "Confirmation message."}]
GUEST = [{"method": "GET", "path": "/", "fields": [], "shows": "Guestbook form and all submitted messages."},
         {"method": "POST", "path": "/submit", "fields": ["name", "message"], "shows": "Confirmation."}]


def test_add_then_list_for_each_field():
    checks = contract_checks(GUEST, "k3f9a2")
    assert [(c["method"], c["path"]) for c in checks] == [("POST", "/submit"), ("GET", "/"), ("GET", "/")]
    assert checks[0]["form"] == {"name": "name k3f9a2", "message": "message k3f9a2"}
    assert [c["expect_text"] for c in checks[1:]] == ["name k3f9a2", "message k3f9a2"]
    assert all(c["name"].startswith("[tower] ") and c["expect_status"] == 200 for c in checks)


def test_values_carry_a_space_so_hand_split_forms_fail():  # runs 19-20: split('=')[1]
    assert " " in contract_checks(TODO, "abc123")[0]["form"]["item"]


def test_destructive_routes_are_skipped():
    routes = [{"method": "POST", "path": "/delete", "fields": ["item"], "shows": ""},
              {"method": "POST", "path": "/toggle", "fields": ["todo"], "shows": ""},
              {"method": "POST", "path": "/save", "fields": ["id"], "shows": ""},
              {"method": "POST", "path": "/edit", "fields": ["todo_id", "text"], "shows": ""},
              {"method": "POST", "path": "/ping", "fields": [], "shows": ""}]
    assert contract_checks(routes, "k3f9a2") == []


def test_the_list_page_is_the_first_get_route_without_fields():
    routes = [{"method": "GET", "path": "/todos", "fields": [], "shows": ""}] + TODO[1:]
    assert contract_checks(routes, "k3f9a2")[1]["path"] == "/todos"


def test_at_most_two_add_routes():
    routes = [{"method": "POST", "path": f"/add{i}", "fields": ["item"], "shows": ""} for i in range(4)]
    assert len(contract_checks(routes, "k3f9a2")) == 4


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
