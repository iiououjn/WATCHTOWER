from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

MAX_QUERY = 300
Provider = Callable[[str, int], list[dict]]


class SearchUnavailable(Exception):
    pass


@dataclass(frozen=True)
class SearchResult:
    title: str
    url: str
    snippet: str


def ddg_provider(query: str, n: int) -> list[dict]:
    from ddgs import DDGS

    return DDGS().text(query, max_results=n)


class Search:
    """Web search for the Beacon (DuckDuckGo by default: free, no key)."""

    def __init__(self, provider: Provider = ddg_provider):
        self._provider = provider

    def query(self, q: str, max_results: int = 5) -> list[SearchResult]:
        q = q.strip()[:MAX_QUERY]
        if not q:
            return []
        try:
            raw = self._provider(q, max_results)
        except Exception as e:
            if "no results" in str(e).lower():
                return []
            raise SearchUnavailable(
                f"web search failed ({type(e).__name__}); check your internet connection, then resume"
            ) from e
        results = [SearchResult(str(r.get("title") or ""), str(r["href"]), str(r.get("body") or ""))
                   for r in raw or [] if r.get("href")]
        return results[:max_results]
