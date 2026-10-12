import pytest

from watchtower.beacon.beacon import Beacon
from watchtower.beacon.fetcher import FetchError, Page
from watchtower.beacon.glass import Glass, GlassRules
from watchtower.beacon.netguard import BlockedURL
from watchtower.beacon.search import Search, SearchUnavailable
from watchtower.engine.governor.audit import AuditLog
from watchtower.engine.knowledge import Knowledge

TEXT = "\n".join(f"Fresnel lens fact {i}: lighthouse optics focus light over long distances." for i in range(6))


class FakeFetcher:
    def __init__(self, pages):
        self.pages = pages

    def fetch(self, url):
        result = self.pages[url]
        if isinstance(result, Exception):
            raise result
        return result


def page(url, text=TEXT, final=None):
    return Page(url, final or url, f"title {url}", text, "t", "h")


def make(conn, urls, pages, max_pages=3, rules=None):
    search = Search(provider=lambda q, n: [{"title": u, "href": u, "body": ""} for u in urls])
    audit = AuditLog(conn)
    glass = Glass(rules or GlassRules("f1", deny_domains=("spam.example",), allow_domains=()))
    return Beacon(search, FakeFetcher(pages), glass, Knowledge(conn), audit, max_pages=max_pages), audit


def actions(audit):
    return [e.action for e in audit.entries(job_id="j")]


def test_accepted_pages_stored_untrusted_with_final_url(conn):
    beacon, audit = make(conn, ["https://a.example/x"], {"https://a.example/x": page("https://a.example/x",
                                                                                     final="https://a.example/y")})
    docs = beacon.research("fresnel lens", "j")
    hit = Knowledge(conn).search("fresnel lens")[0]
    assert docs == [hit.doc_id] and hit.source == "https://a.example/y" and hit.trusted is False
    assert actions(audit) == ["beacon_search", "glass_pass"]


def test_blocked_and_failed_fetches_are_skipped_and_audited(conn):
    beacon, audit = make(conn, ["https://a.example/1", "https://a.example/2", "https://a.example/3"], {
        "https://a.example/1": BlockedURL("resolves to 10.0.0.1"),
        "https://a.example/2": FetchError("robots.txt disallows"),
        "https://a.example/3": page("https://a.example/3"),
    })
    assert len(beacon.research("fresnel", "j")) == 1
    assert actions(audit) == ["beacon_search", "beacon_skip", "beacon_skip", "glass_pass"]


def test_glass_rejections_are_audited_not_stored(conn):
    beacon, audit = make(conn, ["https://spam.example/x"], {"https://spam.example/x": page("https://spam.example/x")})
    assert beacon.research("fresnel", "j") == []
    assert Knowledge(conn).count() == 0
    assert actions(audit) == ["beacon_search", "glass_reject"]


def test_stops_after_max_pages(conn):
    urls = [f"https://a.example/{i}" for i in range(6)]
    beacon, _ = make(conn, urls, {u: page(u, text=TEXT + u) for u in urls}, max_pages=2)
    assert len(beacon.research("fresnel", "j")) == 2


def test_search_unavailable_propagates(conn):
    def down(q, n):
        raise ConnectionError("x")

    beacon = Beacon(Search(provider=down), FakeFetcher({}), Glass(GlassRules("f1", (), ())), Knowledge(conn),
                    AuditLog(conn))
    with pytest.raises(SearchUnavailable):
        beacon.research("fresnel", "j")


def test_known_pages_are_reused_without_refetching(conn):
    Knowledge(conn).add(TEXT, "https://a.example/x")

    class Exploding:
        def fetch(self, url):
            raise AssertionError("should not refetch a page already in knowledge")

    search = Search(provider=lambda q, n: [{"title": "t", "href": "https://a.example/x", "body": ""}])
    audit = AuditLog(conn)
    beacon = Beacon(search, Exploding(), Glass(GlassRules("f1", (), ())), Knowledge(conn), audit)
    assert len(beacon.research("fresnel", "j")) == 1
    assert actions(audit) == ["beacon_search", "beacon_cached"]


def test_cached_page_is_not_reused_through_a_glass_that_would_refuse_it(conn):
    Knowledge(conn).add(TEXT, "https://blog.example/x")  # accepted earlier through open Glass 1

    class Exploding:
        def fetch(self, url):
            raise AssertionError("should not fetch either")

    search = Search(provider=lambda q, n: [{"title": "t", "href": "https://blog.example/x", "body": ""}])
    audit = AuditLog(conn)
    glass2 = Glass(GlassRules("f2", deny_domains=(), allow_domains=("docs.python.org",)))
    assert Beacon(search, Exploding(), glass2, Knowledge(conn), audit).research("x", "j") == []
    assert "beacon_skip" in actions(audit)


def _ask(conflict):
    calls = []

    def ask(prompt):
        calls.append(prompt)
        if "contradict" in prompt:
            if conflict == "garbage":
                from watchtower.engine.model_socket import BadModelOutput
                raise BadModelOutput("x")
            return {"contradiction": conflict, "point": "focal length of first-order lenses"}
        return {"relevant": True}
    return ask, calls


def test_contradiction_with_another_site_becomes_a_note_not_a_reject(conn):
    Knowledge(conn).add(TEXT.replace("long", "short"), "https://other.example/older")
    ask, calls = _ask(True)
    search = Search(provider=lambda q, n: [{"title": "t", "href": "https://a.example/x", "body": ""}])
    beacon = Beacon(search, FakeFetcher({"https://a.example/x": page("https://a.example/x")}),
                    Glass(GlassRules("f1", (), ()), ask), Knowledge(conn), AuditLog(conn))
    assert len(beacon.research("fresnel lens lighthouse optics", "j")) == 1
    assert sum("contradict" in c for c in calls) == 1
    assert beacon.conflicts and "focal length" in beacon.conflicts[0] and "other.example" in beacon.conflicts[0]


def test_no_other_site_on_the_task_means_no_consistency_call(conn):
    ask, calls = _ask(True)
    search = Search(provider=lambda q, n: [{"title": "t", "href": "https://a.example/x", "body": ""}])
    beacon = Beacon(search, FakeFetcher({"https://a.example/x": page("https://a.example/x")}),
                    Glass(GlassRules("f1", (), ()), ask), Knowledge(conn), AuditLog(conn))
    beacon.research("fresnel lens lighthouse optics", "j")
    assert not any("contradict" in c for c in calls) and beacon.conflicts == []


@pytest.mark.parametrize("answer", [False, "garbage"])
def test_agreement_or_garbage_leaves_no_note(conn, answer):
    Knowledge(conn).add(TEXT, "https://other.example/older")
    ask, calls = _ask(answer)
    search = Search(provider=lambda q, n: [{"title": "t", "href": "https://a.example/x", "body": ""}])
    beacon = Beacon(search, FakeFetcher({"https://a.example/x": page("https://a.example/x")}),
                    Glass(GlassRules("f1", (), ()), ask), Knowledge(conn), AuditLog(conn))
    assert len(beacon.research("fresnel lens lighthouse optics", "j")) == 1 and beacon.conflicts == []


def test_consistency_check_can_be_switched_off_for_lookups(conn):
    Knowledge(conn).add(TEXT.replace("long", "short"), "https://other.example/older")
    ask, calls = _ask(True)
    search = Search(provider=lambda q, n: [{"title": "t", "href": "https://a.example/x", "body": ""}])
    beacon = Beacon(search, FakeFetcher({"https://a.example/x": page("https://a.example/x")}),
                    Glass(GlassRules("f1", (), ()), ask), Knowledge(conn), AuditLog(conn), consistency=False)
    beacon.research("fresnel lens lighthouse optics", "j")
    assert not any("contradict" in c for c in calls) and beacon.conflicts == []


def test_runner_builds_lookup_beacons_without_consistency(conn, settings):
    from dataclasses import replace
    from watchtower.engine.runner import JobRunner
    runner = JobRunner(replace(settings, online=True), conn, None, None, None)
    factory = runner._tower._beacon_factory
    assert factory(lambda p: {}, "f1")._consistency is True and factory(lambda p: {}, "f2")._consistency is False
    runner.close()


def test_consistency_never_quotes_a_site_this_glass_refuses(conn):
    Knowledge(conn).add(TEXT.replace("long", "short"), "https://denied.example/older")
    ask, calls = _ask(True)
    search = Search(provider=lambda q, n: [{"title": "t", "href": "https://a.example/x", "body": ""}])
    beacon = Beacon(search, FakeFetcher({"https://a.example/x": page("https://a.example/x")}),
                    Glass(GlassRules("f1", deny_domains=("denied.example",), allow_domains=()), ask),
                    Knowledge(conn), AuditLog(conn))
    beacon.research("fresnel lens lighthouse optics", "j")
    assert not any("contradict" in c for c in calls) and beacon.conflicts == []
