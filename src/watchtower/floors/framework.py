from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from urllib.parse import urlsplit



def untrusted(source: str, text: str) -> str:
    """Wrap outside or derived text as data. '<' is escaped so the text cannot close the tag,
    and the source is reduced to URL-safe characters so it cannot break the attribute."""
    safe_source = re.sub(r"[^A-Za-z0-9:/._%#?=&@+~-]", "", source)[:200]
    return f'<untrusted source="{safe_source}">\n{text.replace("<", "&lt;")}\n</untrusted>'


_TAG = re.compile(r"<(/?untrusted)", re.IGNORECASE)


def untrusted_code(source: str, text: str) -> str:
    """Like untrusted(), for code an agent must edit: only tag-like '<untrusted' / '</untrusted' are escaped,
    so '<h1>' stays '<h1>' (escaping every '<' made the coder copy '&lt;' back into its own files)."""
    safe_source = re.sub(r"[^A-Za-z0-9:/._%#?=&@+~-]", "", source)[:200]
    return f'<untrusted source="{safe_source}">\n{_TAG.sub(r"&lt;\1", text)}\n</untrusted>'


SOURCE_ATTR = re.compile(r'<untrusted source="([^"]*)">')
REALITY_FLOORS = {"f2", "f3", "f4", "f5", "dev"}
SECOND_LEVEL = {"co", "com", "org", "net", "gov", "ac", "edu"}


def registrable_domain(url: str) -> str | None:
    """Approximate registrable domain of an http(s) URL (en.wikipedia.org → wikipedia.org)."""
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return None
    labels = parts.hostname.lower().split(".")
    keep = 3 if len(labels) > 2 and labels[-2] in SECOND_LEVEL and len(labels[-1]) == 2 else 2
    return ".".join(labels[-keep:])


def strs(value, cap: int = 10) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(v).strip() for v in value if str(v).strip()][:cap]


def truthy(value) -> bool:
    if value is True:
        return True
    return isinstance(value, str) and value.strip().lower() in {"true", "yes", "pass"}


@dataclass(frozen=True)
class WorkPackage:
    floor: str
    summary: str
    artifacts: list[str]
    sources: list[str]
    checks_run: list[dict]
    open_questions: list[str]

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "WorkPackage":
        return cls(**d)

    def validate(self) -> list[str]:
        problems = []
        if not self.summary.strip():
            problems.append("summary is empty")
        if not self.checks_run:
            problems.append("no checks were run")
        sections = [s for s in self.summary.split("## ") if s.strip()]
        if sections and all(s.rstrip().endswith("(no result)") for s in sections):
            problems.append("no task produced a result")
        if self.floor in REALITY_FLOORS and self.checks_run and not self.checks_run[-1].get("pass"):
            problems.append("reality check failed: tests or app did not pass")
        return problems
