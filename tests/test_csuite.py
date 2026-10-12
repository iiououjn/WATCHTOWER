from watchtower.csuite.ceo import CEO
from watchtower.csuite.cto import CTO
from watchtower.engine.model_socket import BadModelOutput
from watchtower.roles import Role

SPEC = {"title": "Todo", "goal": "todo app", "acceptance": ["add a todo"], "out_of_scope": []}
PLAN = {"files": [{"path": "app.py", "purpose": "<b>server"}], "entry": "app.py", "routes": []}


def ask_with(reply, prompts):
    def ask(role, prompt):
        prompts.append(prompt)
        if reply == "bad":
            raise BadModelOutput("x")
        return reply
    return ask


def test_cto_approves_or_lists_changes():
    prompts = []
    cto = CTO(Role("cto", "CTO", "csuite", "small", (), "c"),
              ask_with({"approve": False, "changes": ["add a test file", "x" * 300]}, prompts))
    approved, changes = cto.review(SPEC, PLAN, ("Use only the standard library.",))
    assert approved is False and changes[0] == "add a test file" and len(changes[1]) <= 200
    assert "Use only the standard library." in prompts[0] and '<untrusted source="f2.architect">' in prompts[0]


def test_cto_garbage_or_no_verdict_approves():
    role = Role("cto", "CTO", "csuite", "small", (), "c")
    assert CTO(role, ask_with("bad", [])).review(SPEC, PLAN, ()) == (True, [])
    assert CTO(role, ask_with({"changes": ["x"]}, [])).review(SPEC, PLAN, ()) == (True, [])


def test_ceo_recommends_with_a_note():
    prompts = []
    ceo = CEO(Role("ceo", "CEO", "csuite", "small", (), "e"), ask_with({"approve": False, "note": "no delete"}, prompts))
    assert ceo.recommend(SPEC, "- unit tests: pass", "- add: OK") == (False, "no delete")
    assert '<untrusted source="evidence">' in prompts[0]
    assert CEO(Role("ceo", "CEO", "csuite", "small", (), "e"), ask_with("bad", [])).recommend(SPEC, "", "") == (None, "")
