import pytest

from watchtower.engine.beacon.beacon import Beacon
from watchtower.engine.beacon.fetcher import FetchError, Page
from watchtower.engine.beacon.glass import Glass, GlassRules
from watchtower.engine.beacon.netguard import BlockedURL
from watchtower.engine.beacon.search import Search, SearchUnavailable
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
