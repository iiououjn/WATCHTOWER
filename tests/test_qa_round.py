from watchtower.floors.f4_qa_deploy.office import QAOffice, QARound
from watchtower.roles import Role

SPEC = {"title": "Todo", "goal": "todo app", "acceptance": ["users can add a todo"]}
ROLE = lambda i: Role(i, i, "f4", "small", "x")  # noqa: E731
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


class Writer:
    def __init__(self, outs):
        self.outs, self.codes = list(outs), []

    def write_checks(self, spec, code):
        self.codes.append(code)
        out = self.outs.pop(0) if len(self.outs) > 1 else self.outs[0]
        if isinstance(out, Exception):
            raise out
        return out


def test_fallback_checks_run_unreviewed_like_main(tmp_path=None):
    qa, calls = office([{"pass": False, "drop": ["add", "list"]}])
    listed = {**HOME, "name": "list", "expect_text": "milk"}
    rnd = QARound(qa, Writer([[HOME, ADD, listed]]), SPEC)
    rnd.reset([])
    assert [c["name"] for c in rnd.ensure([], "code")] == ["home", "add", "list"] and calls == []


def test_a_suite_without_meaningful_page_text_counts_as_empty():
    qa, _ = office([{"pass": True, "drop": []}])
    for weak in ({**ADD, "name": "post", "expect_text": ""}, {**HOME, "expect_text": "<"},
                 {**HOME, "expect_text": "Todo"}):  # status-only, a symbol, the spec title alone
        rnd = QARound(qa, Writer([[TITLE]]), SPEC)
        rnd.reset([weak])
        assert rnd.coder_checks == [] and rnd.ensure([], "code") == [TITLE]


def test_fallback_checks_are_rewritten_from_the_current_code_each_attempt():
    qa, _ = office([{"pass": True, "drop": []}])
    w = Writer([[HOME]])
    rnd = QARound(qa, w, SPEC)
    rnd.reset([])
    rnd.ensure([], "v1")
    rnd.ensure([], "v2")
    assert w.codes == ["v1", "v2"] and rnd.coder_checks == []  # the coder is never handed stale fallback checks
    rnd.reset([HOME])
    rnd.ensure([], "v3")
    assert w.codes == ["v1", "v2"] and rnd.coder_checks == [HOME]


def test_a_writer_failure_later_reuses_the_last_checks():
    from watchtower.engine.model_socket import BadModelOutput
    qa, _ = office([{"pass": True, "drop": []}])
    rnd = QARound(qa, Writer([[TITLE], BadModelOutput("x")]), SPEC)
    rnd.reset([])
    assert rnd.ensure([], "v1") == [TITLE] and rnd.ensure([], "v2") == [TITLE]
    fresh = QARound(qa, Writer([BadModelOutput("x")]), SPEC)
    fresh.reset([])
    try:
        fresh.ensure([], "v1")
        raise AssertionError("must raise when there is nothing to reuse")
    except BadModelOutput:
        pass


def test_test_first_checks_are_never_stripped():
    out = {"checks": [{"name": "empty", "path": "/", "expect_text": "The list is empty"},
                      {"name": "nf", "path": "/x", "expect_text": "The page you requested was not found"}]}
    qa, _ = office([{"areas": ["home"]}, out, {"pass": True, "drop": []}])
    routes = [{"method": "GET", "path": "/", "fields": [], "shows": ""},
              {"method": "GET", "path": "/x", "fields": [], "shows": ""}]
    texts = [c["expect_text"] for c in qa.plan_checks(SPEC, routes)]
    assert "The list is empty" in texts and "The page you requested was not found" in texts
