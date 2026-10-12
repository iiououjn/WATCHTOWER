from __future__ import annotations

from watchtower.beacon.fetcher import FetchError
from watchtower.beacon.glass import Glass
from watchtower.beacon.netguard import BlockedURL
from watchtower.beacon.search import Search
from watchtower.engine.governor.audit import AuditLog
from watchtower.engine.knowledge import Knowledge


class Beacon:
    """Scans the web for one task: search → guarded fetch → glass → knowledge (untrusted).
    Every step is audited; nothing that fails the glass is stored."""

    def __init__(self, search: Search, fetcher, glass: Glass, knowledge: Knowledge, audit: AuditLog,
                 max_pages: int = 3):
        self._search = search
        self._fetcher = fetcher
        self._glass = glass
        self._knowledge = knowledge
        self._audit = audit
        self._max_pages = max_pages

    def research(self, task: str, job_id: str | None) -> list[int]:
        self._audit.append("beacon", "beacon_search", {"query": task[:200]}, job_id)
        accepted: list[int] = []
        for result in self._search.query(task, self._max_pages * 2):
            if len(accepted) >= self._max_pages:
                break
            known = self._knowledge.has_source(result.url)
            if known is not None:  # already passed the glass earlier: reuse, don't refetch or re-judge
                self._audit.append("beacon", "beacon_cached", {"url": result.url, "doc_id": known}, job_id)
                accepted.append(known)
                continue
            try:
                page = self._fetcher.fetch(result.url)
            except (BlockedURL, FetchError) as e:
                self._audit.append("beacon", "beacon_skip", {"url": result.url, "reason": str(e)[:200]}, job_id)
                continue
            verdict = self._glass.inspect(page.final_url, page.text, task)
            if not verdict.passed:
                self._audit.append("beacon", "glass_reject", {"url": page.final_url, "reasons": verdict.reasons},
                                   job_id)
                continue
            doc_id = self._knowledge.add(verdict.text, page.final_url, page.title, trusted=False)
            self._audit.append("beacon", "glass_pass", {"url": page.final_url, "doc_id": doc_id,
                                                        "notes": verdict.reasons}, job_id)
            accepted.append(doc_id)
        return accepted
