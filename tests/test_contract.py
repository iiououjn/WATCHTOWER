"""Phase 6u: the deciding F4 checks come from the routes contract, not the small model (runs 18-21)."""
from watchtower.floors.f4_qa_deploy.contract import contract_checks

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
