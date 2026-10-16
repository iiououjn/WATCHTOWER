from __future__ import annotations

import builtins
import re
import sqlite3
from collections import Counter
from typing import Callable

import yaml

from watchtower.beacon.glass import SECRET, Glass, load_glass_rules, normalize
from watchtower.beacon.search import SearchUnavailable
from watchtower.engine.advisory import ADVISORY_ERRORS
from watchtower.engine.knowledge import Knowledge
from watchtower.floors.framework import untrusted

MAX_PER_FLOOR, QUERY_CHARS, ANSWER_CHARS = 2, 120, 500
_PATHISH = re.compile(r"\S*[/\\]\S*|\S+\.(py|html|css|js|json|md|txt|sql|db)\b\S*", re.IGNORECASE)
_ERROR = re.compile(r"^\s*([A-Za-z_][\w.]*(Error|Exception)\b.*)$", re.MULTILINE)
_WARNING = re.compile(r"^\s*([A-Za-z_][\w.]*Warning\b.*)$", re.MULTILINE)
# phrases that describe an error without carrying the app's data: the only words of a message that may leave
STDLIB_ERRORS = {"JSONDecodeError", "URLError", "HTTPError", "OperationalError", "IntegrityError",
                 "ProgrammingError", "UnpicklingError", "ParseError", "Error"}
SAFE_PHRASES = ("No module named", "Address already in use", "is not defined", "has no attribute",
                "object is not callable", "object is not subscriptable", "unexpected keyword argument",
                "missing 1 required positional argument", "invalid literal for int", "list index out of range",
                "unsupported operand type", "can only concatenate", "not JSON serializable", "Connection refused",
                "Permission denied", "No such file or directory", "invalid syntax", "unexpected indent")


def scrub_query(text: str) -> str:
    """What may leave the Mac as a search query: no secrets, paths, file names or quotes (spec §5 privacy)."""
    text = SECRET.sub(" ", normalize(str(text)))
    text = _PATHISH.sub(" ", text)
    text = re.sub(r"[\"'`<>{}\[\]\x00-\x1f\x7f]", " ", text)
    return " ".join(text.split())[:QUERY_CHARS]


def error_line(log: str) -> str:
    """The last exception line of an app's output ('KeyError: ...'), or ''."""
    found = _ERROR.findall(str(log)) or _WARNING.findall(str(log))  # the crash, not a shutdown warning
    return found[-1][0].strip() if found else ""


def crash_query(log: str) -> str:
    """F3's search: the exception class plus at most one known phrase. Never the message itself: it can
    carry the app's data (emails, tokens, names) and that must not reach a search engine."""
    line = error_line(log)
    if not line:
        return ""
    kind = re.match(r"[A-Za-z_][\w.]*", line).group(0).rsplit(".", 1)[-1]
    if not (isinstance(getattr(builtins, kind, None), type) or kind in STDLIB_ERRORS):
        kind = "exception"  # a class the app's own code named can carry its data
    phrase = next((p for p in SAFE_PHRASES if p in line), "")
    return " ".join(f"{kind} {phrase} python".split())


class Lookout:
    """A floor asks the Beacon through its own glass: search → that glass → Knowledge, then only pages that
    glass allows come back, wrapped as untrusted. Bounded per floor, and advisory: no answer = carry on."""

    def __init__(self, beacon_factory: Callable | None, knowledge: Knowledge):
        self._factory, self._knowledge, self._used = beacon_factory, knowledge, Counter()

    def state(self) -> dict[str, int]:  # 8b review r3: kept in the dev floor's checkpoint, so the cap survives a resume
        return dict(self._used)

    def restore(self, used: dict[str, int]) -> None:
        self._used = Counter({str(f): int(n) for f, n in used.items()})

    def ask(self, floor: str, query: str, job_id: str | None, ask_glass: Callable[[str], dict],
            max_hits: int = 2, max_chars: int = ANSWER_CHARS + 200) -> str:
        q = scrub_query(query)
        if self._factory is None or self._used[floor] >= MAX_PER_FLOOR or len(q) < 3:
            return ""
        self._used[floor] += 1
        try:  # advisory end to end: a bad owner glass file or a busy database costs the lookup, not the job
            glass = Glass(load_glass_rules(floor))
            accepted = set(self._factory(ask_glass, floor).research(q, job_id) or [])
            hits = [h for h in self._knowledge.search(q, limit=8, distinct=True, doc_ids=accepted)
                    if h.source.startswith("https://") and glass.domain_allowed(h.source) and glass.credibility(h.source)]
        except (SearchUnavailable, OSError, yaml.YAMLError, ValueError, TypeError, sqlite3.Error, *ADVISORY_ERRORS):
            return ""
        out, used = [], 0
        for h in hits[:max_hits]:
            body = h.text
            while body and len(untrusted(h.source, body)) > max_chars - used:  # bounded after escaping
                body = body[:int(len(body) * 0.8)]
            if len(body) < 80:
                break
            out.append(untrusted(h.source, body))
            used += len(out[-1]) + 1
        return "\n".join(out)
