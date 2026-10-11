from __future__ import annotations

import hashlib
from dataclasses import dataclass
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import httpx
import trafilatura

from watchtower.engine.beacon.netguard import Resolver, check_url, system_resolver
from watchtower.engine.db import now

MAX_BYTES = 2_000_000
MAX_TEXT = 20_000
MAX_REDIRECTS = 5
USER_AGENT = "WatchtowerBeacon/0.1 (local research agent)"
TEXT_TYPES = {"text/html", "application/xhtml+xml", "text/plain"}


class FetchError(Exception):
    pass


@dataclass(frozen=True)
class Page:
    url: str
    final_url: str
    title: str
    text: str
    fetched_at: str
    sha256: str


class Fetcher:
    """Fetches one web page safely: every redirect hop is re-checked against the network guard,
    robots.txt is honoured, size and type are capped, and only the main text is kept."""

    def __init__(self, resolve: Resolver = system_resolver, transport: httpx.BaseTransport | None = None,
                 timeout: float = 10.0):
        self._resolve = resolve
        self._client = httpx.Client(transport=transport, timeout=timeout, follow_redirects=False,
                                    headers={"User-Agent": USER_AGENT})
        self._robots: dict[str, RobotFileParser] = {}

    def close(self) -> None:
        self._client.close()

    def fetch(self, url: str) -> Page:
        current = url
        for _ in range(MAX_REDIRECTS + 1):
            check_url(current, self._resolve)
            if not self._robots_allow(current):
                raise FetchError(f"robots.txt disallows {current}")
            with self._client.stream("GET", current) as resp:
                if resp.is_redirect:
                    location = resp.headers.get("location")
                    if not location:
                        raise FetchError("redirect without a location")
                    current = str(httpx.URL(current).join(location))
                    continue
                if resp.status_code != 200:
                    raise FetchError(f"HTTP {resp.status_code} from {current}")
                ctype = resp.headers.get("content-type", "").split(";")[0].strip().lower()
                if ctype not in TEXT_TYPES:
                    raise FetchError(f"unsupported content type {ctype or 'unknown'}")
                body = bytearray()
                for chunk in resp.iter_bytes():
                    body += chunk
                    if len(body) > MAX_BYTES:
                        raise FetchError("page is larger than 2 MB")
                raw = bytes(body).decode(resp.encoding or "utf-8", errors="replace")
                break
        else:
            raise FetchError(f"more than {MAX_REDIRECTS} redirects")
        title, text = current, raw
        if ctype != "text/plain":
            text = trafilatura.extract(raw) or ""
            meta = trafilatura.extract_metadata(raw)
            title = (meta.title if meta and meta.title else "") or current
        text = text.strip()[:MAX_TEXT]
        if not text:
            raise FetchError("page has no readable text")
        return Page(url, current, title, text, now(), hashlib.sha256(text.encode()).hexdigest())

    def _robots_allow(self, url: str) -> bool:
        parts = urlsplit(url)
        root = f"{parts.scheme}://{parts.netloc}"
        if root not in self._robots:
            parser = RobotFileParser()
            try:
                resp = self._client.get(root + "/robots.txt")
                if resp.status_code == 200:
                    parser.parse(resp.text.splitlines())
                elif resp.status_code in (401, 403) or resp.status_code >= 500:
                    parser.disallow_all = True
                else:
                    parser.allow_all = True
            except httpx.HTTPError:
                parser.disallow_all = True
            self._robots[root] = parser
        return self._robots[root].can_fetch(USER_AGENT, url)
