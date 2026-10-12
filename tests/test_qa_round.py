from watchtower.floors.f4_qa_deploy.office import QAOffice, QARound
from watchtower.roles import Role

SPEC = {"title": "Todo", "goal": "todo app", "acceptance": ["users can add a todo"]}
ROLE = lambda i: Role(i, i, "f4", "small", (), "x")  # noqa: E731
HOME = {"name": "home", "method": "GET", "path": "/", "form": {}, "expect_status": 200, "expect_text": "Todo List"}
ADD = {"name": "add", "method": "POST", "path": "/add", "form": {"item": "milk"}, "expect_status": 200,
       "expect_text": "milk"}
TITLE = {"name": "title", "method": "GET", "path": "/", "form": {}, "expect_status": 200, "expect_text": "My Todos"}


def office(hr_replies, calls=None):
    calls = calls if calls is not None else []

    def ask(role, prompt):
        calls.append((role.id, prompt))
        r = hr_replies.pop(0) if len(hr_replies) > 1 else hr_replies[0]
        if isinstance(r, Exception):
            raise r
        return r
    return QAOffice(ROLE("f4.lead"), ROLE("f4.qa"), ROLE("f4.hr"), ask), calls


def fail(*names, status=200):
    return [{"name": n, "pass": False, "status": status, "detail": "text not found"} for n in names]


def test_hr_cannot_drop_every_check():
    qa, _ = office([{"pass": False, "drop": ["home", "add"]}])
    assert [c["name"] for c in qa.review(SPEC, [], [HOME, ADD])] == ["home", "add"]


def test_a_check_is_relaxed_only_after_two_consecutive_f4_failures():
    qa, calls = office([{"check_wrong": True}])
    rnd = QARound(qa, None, SPEC)
    rnd.reset([HOME, TITLE])
    assert rnd.after_fail(fail("title"), replanning=False) == []
    rnd.no_f4()  # F3 failed in between: not consecutive
    assert rnd.after_fail(fail("title"), replanning=False) == []
    notes = rnd.after_fail(fail("title"), replanning=False)
    assert notes and "title" in notes[0] and next(c for c in rnd.checks if c["name"] == "title")["expect_text"] == ""
    assert sum(r == "f4.hr" for r, _ in calls) == 1


def test_persistence_checks_and_the_last_text_check_are_never_relaxed():
    qa, calls = office([{"check_wrong": True}])
    rnd = QARound(qa, None, SPEC)
    rnd.reset([HOME, ADD])
    for _ in range(3):
        rnd.after_fail(fail("add"), replanning=False)
    assert next(c for c in rnd.checks if c["name"] == "add")["expect_text"] == "milk" and calls == []
    rnd.reset([HOME])
    for _ in range(3):
        rnd.after_fail(fail("home"), replanning=False)
    assert rnd.checks[0]["expect_text"] == "Todo List" and calls == []


def test_wrong_status_or_garbage_or_replanning_keeps_the_check():
    for replies, results, replanning in (([{"check_wrong": True}], fail("title", status=500), False),
                                         ([ValueError("x")], fail("title"), False),
                                         ([{"check_wrong": "true"}], fail("title"), False),
                                         ([{"check_wrong": True}], fail("title"), True)):
        from watchtower.engine.model_socket import BadModelOutput
        replies = [BadModelOutput("x") if isinstance(r, ValueError) else r for r in replies]
        qa, _ = office(replies)
        rnd = QARound(qa, None, SPEC)
        rnd.reset([HOME, TITLE])
        rnd.after_fail(results, replanning=replanning)
        rnd.after_fail(results, replanning=replanning)
        assert next(c for c in rnd.checks if c["name"] == "title")["expect_text"] == "My Todos"


def test_reset_forgets_failures_of_the_old_plan():
    qa, calls = office([{"check_wrong": True}])
    rnd = QARound(qa, None, SPEC)
    rnd.reset([HOME, TITLE])
    rnd.after_fail(fail("title"), replanning=False)
    rnd.reset([HOME, TITLE])
    assert rnd.after_fail(fail("title"), replanning=False) == [] and calls == []
