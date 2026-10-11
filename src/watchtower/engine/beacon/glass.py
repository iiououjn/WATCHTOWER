from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from urllib.parse import urlsplit

import yaml

from watchtower.engine.floor import truthy, untrusted
from watchtower.engine.model_socket import BadModelOutput

GLASS_DIR = Path(__file__).resolve().parents[2] / "glass"
INJECTION = re.compile(
    r"\b(ignore|disregard|forget|override)\b.{0,40}\b(instructions|prompts|messages|rules|above|guidelines)\b"
    r"|\byour (previous |prior |original )?(instructions|rules|prompt)\b|you are now|new instructions\s*:"
    r"|system prompt|\[role:|</?untrusted|<\|im_start\|>|<\|system\|>|from now on|\bact as\b"
    r"|\bpretend (to be|you are)\b",
    re.IGNORECASE,
)
CONFUSABLES = str.maketrans("аеорсухіјѕԁɡАЕОРСХІЈЅ", "aeopcyxijsdgAEOPCXIJS")


def normalize(text: str) -> str:
    """Defeat cheap evasions: NFKC, drop invisible format characters, fold Cyrillic look-alikes."""
    text = unicodedata.normalize("NFKC", text)
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Cf")
    return text.translate(CONFUSABLES)
SECRET = re.compile(
    r"sk-[A-Za-z0-9_-]{20,}|AKIA[0-9A-Z]{16}|-----BEGIN [A-Z ]*PRIVATE KEY-----|ghp_[A-Za-z0-9]{36}"
    r"|xox[baprs]-[A-Za-z0-9-]{10,}"
)
RELEVANCE_PROMPT = (
    "Task:\n{task}\n\nPage:\n{page}\n\n"
    'Is this page relevant and useful for the task? Reply as JSON: {{"relevant": boolean, "reason": string}}'
)


@dataclass(frozen=True)
class GlassRules:
    name: str
    deny_domains: tuple[str, ...]
    allow_domains: tuple[str, ...]
    min_chars: int = 200
    max_injection_ratio: float = 0.3


@dataclass(frozen=True)
class GlassVerdict:
    passed: bool
    reasons: list[str]
    text: str


def load_glass_rules(floor: str, directory: Path = GLASS_DIR) -> GlassRules:
    data = yaml.safe_load((directory / f"{floor}.yaml").read_text()) or {}
    return GlassRules(
        name=str(data.get("name") or floor),
        deny_domains=tuple(data.get("deny_domains") or ()),
        allow_domains=tuple(data.get("allow_domains") or ()),
        min_chars=int(data.get("min_chars", 200)),
        max_injection_ratio=float(data.get("max_injection_ratio", 0.3)),
    )


def _matches(host: str, domains: tuple[str, ...]) -> bool:
    return any(host == d or host.endswith("." + d) for d in domains)


class Glass:
    """A floor's glass layer: cheap deterministic checks first, then an optional model relevance check.
    Pages that pass are returned with instruction-like paragraphs removed."""

    def __init__(self, rules: GlassRules, ask: Callable[[str], dict] | None = None):
        self._rules = rules
        self._ask = ask

    def domain_allowed(self, url: str) -> bool:
        """Re-check a source against the current domain rules (non-web sources always pass)."""
        parts = urlsplit(url)
        if parts.scheme not in ("http", "https"):
            return True
        host = (parts.hostname or "").lower()
        if _matches(host, self._rules.deny_domains):
            return False
        return not self._rules.allow_domains or _matches(host, self._rules.allow_domains)

    def inspect(self, url: str, text: str, task: str) -> GlassVerdict:
        host = (urlsplit(url).hostname or "").lower()
        if _matches(host, self._rules.deny_domains):
            return self._reject(f"domain {host} is denied by glass {self._rules.name}")
        if self._rules.allow_domains and not _matches(host, self._rules.allow_domains):
            return self._reject(f"domain {host} is not on glass {self._rules.name}'s allow list")
        if SECRET.search(text):
            return self._reject("page contains secret-like strings")
        paragraphs = [normalize(p).strip() for p in text.splitlines() if p.strip()]
        flagged = set()
        for i, p in enumerate(paragraphs):
            if INJECTION.search(p):
                flagged.add(i)
            elif (i + 1 < len(paragraphs) and not INJECTION.search(paragraphs[i + 1])
                  and INJECTION.search(p + " " + paragraphs[i + 1])):
                flagged.update({i, i + 1})  # instruction split across two lines
        if paragraphs and len(flagged) / len(paragraphs) > self._rules.max_injection_ratio:
            return self._reject("page is mostly instruction-like text (likely prompt injection)")
        clean = "\n".join(p for i, p in enumerate(paragraphs) if i not in flagged)
        if len(clean) < self._rules.min_chars:
            return self._reject("too little readable text")
        notes = [f"removed {len(flagged)} instruction-like paragraph(s)"] if flagged else []
        if self._ask is not None:
            try:
                verdict = self._ask(RELEVANCE_PROMPT.format(task=task, page=untrusted(url, clean[:2000])))
            except BadModelOutput:
                return self._reject("relevance check failed (model gave no usable answer)")
            if not truthy(verdict.get("relevant")):
                return self._reject(f"not relevant: {str(verdict.get('reason') or 'no reason given')[:200]}")
        return GlassVerdict(True, notes, clean)

    @staticmethod
    def _reject(reason: str) -> GlassVerdict:
        return GlassVerdict(False, [reason], "")
