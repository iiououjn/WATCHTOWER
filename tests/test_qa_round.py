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


def test_hr_cannot_drop_every_text_check():
    status_only = {**ADD, "name": "post", "expect_text": ""}
    qa, _ = office([{"pass": False, "drop": ["home", "title"]}])
    assert {c["name"] for c in qa.review(SPEC, [], [HOME, TITLE, status_only])} == {"home", "title", "post"}


def test_a_suite_without_page_text_counts_as_empty_and_the_guarded_writer_runs():
    status_only = {**ADD, "name": "post", "expect_text": ""}

    class Writer:
        calls = 0

        def write_checks(self, spec, code):
            Writer.calls += 1
            return [HOME]
    qa, _ = office([{"pass": True, "drop": []}])
    rnd = QARound(qa, Writer(), SPEC)
    rnd.reset([status_only])
    assert rnd.checks == [] and rnd.ensure([], "code") == [HOME] and Writer.calls == 1


def test_fallback_checks_are_rewritten_from_the_current_code_each_attempt():
    class Writer:
        def __init__(self):
            self.codes = []

        def write_checks(self, spec, code):
            self.codes.append(code)
            return [HOME]
    qa, _ = office([{"pass": True, "drop": []}])
    w = Writer()
    rnd = QARound(qa, w, SPEC)
    rnd.reset([])
    rnd.ensure([], "v1")
    rnd.ensure([], "v2")
    assert w.codes == ["v1", "v2"]
    rnd.reset([HOME])  # test-first checks are kept as they are
    rnd.ensure([], "v3")
    assert w.codes == ["v1", "v2"]
