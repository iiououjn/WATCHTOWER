from __future__ import annotations

import re
from collections import Counter
from typing import Callable

from watchtower.beacon.glass import SECRET, Glass, load_glass_rules, normalize
from watchtower.beacon.search import SearchUnavailable
from watchtower.engine.advisory import ADVISORY_ERRORS
from watchtower.engine.knowledge import Knowledge
from watchtower.floors.framework import untrusted

MAX_PER_FLOOR, QUERY_CHARS, ANSWER_CHARS = 2, 120, 500
_PATHISH = re.compile(r"\S*[/\\]\S*|\S+\.(py|html|css|js|json|md|txt|sql|db)\b\S*", re.IGNORECASE)
_ERROR = re.compile(r"^\s*([A-Za-z_][\w.]*(Error|Exception|Warning)\b.*)$", re.MULTILINE)


def scrub_query(text: str) -> str:
    """What may leave the Mac as a search query: no secrets, paths, file names or quotes (spec §5 privacy)."""
    text = SECRET.sub(" ", normalize(str(text)))
    text = _PATHISH.sub(" ", text)
    text = re.sub(r"[\"'`<>{}\[\]\x00-\x1f\x7f]", " ", text)
    return " ".join(text.split())[:QUERY_CHARS]


def error_line(log: str) -> str:
    """The last exception line of an app's output ('KeyError: ...'), or ''."""
    found = _ERROR.findall(str(log))
    return found[-1][0].strip() if found else ""


class Lookout:
    """A floor asks the Beacon through its own glass: search → that glass → Knowledge, then only pages that
    glass allows come back, wrapped as untrusted. Bounded per floor, and advisory: no answer = carry on."""

    def __init__(self, beacon_factory: Callable | None, knowledge: Knowledge):
        self._factory, self._knowledge, self._used = beacon_factory, knowledge, Counter()

    def ask(self, floor: str, query: str, job_id: str | None, ask_glass: Callable[[str], dict]) -> str:
        q = scrub_query(query)
        if self._factory is None or self._used[floor] >= MAX_PER_FLOOR or len(q) < 3:
            return ""
        self._used[floor] += 1
        glass = Glass(load_glass_rules(floor))
        try:
            self._factory(ask_glass, floor).research(q, job_id)
        except (SearchUnavailable, OSError, *ADVISORY_ERRORS):
            return ""
        hits = [h for h in self._knowledge.search(q, limit=8, distinct=False)
                if h.source.startswith("https://") and glass.domain_allowed(h.source) and glass.credibility(h.source)]
        out, used = [], 0
        for h in hits[:2]:
            body = h.text[:ANSWER_CHARS - used]
            if len(body) < 80:
                break
            out.append(untrusted(h.source, body))
            used += len(body)
        return "\n".join(out)
