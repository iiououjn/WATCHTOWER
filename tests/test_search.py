import pytest

from watchtower.engine.beacon.search import Search, SearchUnavailable


def test_maps_provider_results():
    s = Search(provider=lambda q, n: [{"title": "T", "href": "https://a.example", "body": "b"}, {"title": "no url"}])
    results = s.query("fresnel lens")
    assert [(r.title, r.url, r.snippet) for r in results] == [("T", "https://a.example", "b")]


def test_provider_failure_is_unavailable():
    def boom(q, n):
        raise ConnectionError("rate limited")

    with pytest.raises(SearchUnavailable, match="resume"):
        Search(provider=boom).query("x")


def test_no_results_is_empty_not_error():
    def none(q, n):
        raise RuntimeError("No results found.")

    assert Search(provider=none).query("x") == []


def test_blank_query():
    assert Search(provider=lambda q, n: 1 / 0).query("   ") == []


def test_query_is_trimmed_and_capped():
    seen = []
    Search(provider=lambda q, n: seen.append((q, n)) or []).query("  " + "x" * 500, max_results=3)
    assert seen == [("x" * 300, 3)]
