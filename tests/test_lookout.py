import pytest

from watchtower.beacon.lookout import Lookout, crash_query, error_line, scrub_query
from watchtower.beacon.search import SearchUnavailable
from watchtower.engine.knowledge import Knowledge
from watchtower.engine.model_socket import LowMemory

DOC = "http.server handles GET requests; send_response sets the status code. " * 6


class Factory:
    def __init__(self, conn, fail=None, accept=True):
        self.conn, self.fail, self.calls, self.accept = conn, fail, [], accept

    def __call__(self, ask, floor):
        factory = self

        class B:
            def research(self, query, job_id):
                factory.calls.append((floor, query))
                if factory.fail:
                    raise factory.fail
                kb = Knowledge(factory.conn)
                if factory.accept is False:
                    return []
                return [kb.add(DOC, "https://docs.python.org/3/library/http.server.html"),
                        kb.add(DOC + " blog", "https://blog.example/post")]
        return B()


def test_lookout_returns_only_what_the_floor_glass_allows(conn):
    factory = Factory(conn)
    text = Lookout(factory, Knowledge(conn)).ask("f2", "python http.server GET", "j", lambda p: {})
    assert factory.calls == [("f2", "python http.server GET")]
    assert "docs.python.org" in text and "blog.example" not in text and '<untrusted source="https://docs' in text


def test_lookout_is_bounded_per_floor(conn):
    factory, look = Factory(conn), None
    look = Lookout(factory, Knowledge(conn))
    for _ in range(4):
        look.ask("f3", "KeyError http.server", "j", lambda p: {})
    look.ask("f5", "bandit B602", "j", lambda p: {})
    assert [c[0] for c in factory.calls] == ["f3", "f3", "f5"]


@pytest.mark.parametrize("error", [SearchUnavailable("down"), LowMemory("9%"), OSError("net")])
def test_lookout_failures_are_advisory(conn, error):
    assert Lookout(Factory(conn, fail=error), Knowledge(conn)).ask("f2", "python x", "j", lambda p: {}) == ""


def test_no_factory_means_no_lookup(conn):
    assert Lookout(None, Knowledge(conn)).ask("f2", "python x", "j", lambda p: {}) == ""


def test_queries_never_carry_secrets_paths_or_file_names():
    q = scrub_query('KeyError: "sk-' + "a" * 30 + '" in /Users/rishi/secret/app.py line 3, store.py ' + "x" * 300)
    assert "sk-" not in q and "/Users" not in q and "app.py" not in q and "store.py" not in q
    assert "KeyError" in q and len(q) <= 120 and '"' not in q


def test_error_line_finds_the_exception():
    log = "Serving\nTraceback (most recent call last):\n  File \"/work/app.py\", line 3\nKeyError: 'items'\n"
    assert error_line(log) == "KeyError: 'items'" and error_line("all fine") == ""


def test_f4_and_f5_queries_are_built_from_codes_not_app_text():
    from watchtower.tower import _finding_query, _status_query
    qa = {"results": [{"pass": True, "status": 200}, {"pass": False, "status": 405, "detail": "sk-secret body"}]}
    assert _status_query(qa) == "HTTP 405 Method Not Allowed python http.server"
    assert _status_query({"results": [{"pass": False, "status": None}]}) == ""
    sec = {"findings": [{"tool": "secrets", "id": "SECRET", "severity": "HIGH", "confidence": "HIGH"},
                        {"tool": "bandit", "id": "B602", "severity": "HIGH", "confidence": "HIGH"}]}
    assert _finding_query(sec, ("HIGH",)) == "bandit B602 python"
    assert _finding_query({"findings": [{"tool": "bandit", "id": "B602; rm", "severity": "HIGH",
                                         "confidence": "HIGH"}]}, ("HIGH",)) == ""


def test_lookout_returns_only_pages_this_lookup_accepted(conn):
    Knowledge(conn).add(DOC, "https://docs.python.org/3/library/old.html")  # stale, from another floor's lookup
    assert Lookout(Factory(conn, accept=False), Knowledge(conn)).ask("f2", "python http.server GET", "j",
                                                                     lambda p: {}) == ""


def test_lookout_answer_is_bounded_after_wrapping(conn):
    class F:
        def __call__(self, ask, floor):
            class B:
                def research(self, q, job_id):
                    return [Knowledge(conn).add("<p>http.server GET handler " * 60, "https://docs.python.org/3/x")]
            return B()
    text = Lookout(F(), Knowledge(conn)).ask("f4", "python http.server GET", "j", lambda p: {}, max_hits=1)
    assert 0 < len(text) <= 700 and text.count("<untrusted") == 1 and text.endswith("</untrusted>")


@pytest.mark.parametrize("log,expected", [
    ("Traceback\nKeyError: 'alice@example.com'\n", "KeyError python"),
    ("ValueError: invalid literal for int() with base 10: 'hunter2-password'", "ValueError invalid literal for int python"),
    ("RuntimeError: token=glpat-ABCDEFGHIJKLMNOP password=Sup3rS3cret", "RuntimeError python"),
    ("ModuleNotFoundError: No module named 'flask'", "ModuleNotFoundError No module named python"),
    ("OSError: [Errno 98] Address already in use", "OSError Address already in use python"),
    ("all fine", "")])
def test_crash_query_sends_only_the_error_kind(log, expected):
    assert crash_query(log) == expected


def test_error_line_prefers_the_crash_over_a_later_warning():
    log = "TypeError: bad operand\nDeprecationWarning: old api\nResourceWarning: unclosed socket"
    assert error_line(log) == "TypeError: bad operand"
