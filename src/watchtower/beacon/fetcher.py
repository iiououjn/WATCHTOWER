from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from typing import Callable
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import httpcore
import httpx
import trafilatura

from watchtower.beacon.netguard import BlockedURL, Resolver, check_url, public_ip, system_resolver
from watchtower.engine.db import now

MAX_BYTES = 2_000_000
MAX_ROBOTS_BYTES = 512_000
MAX_TEXT = 20_000
MAX_REDIRECTS = 5
DEADLINE_SECONDS = 20.0
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


class GuardedBackend(httpcore.SyncBackend):
    """Resolves, vets and connects in one step, so DNS cannot rebind between the check and the
    connection. TLS still verifies against the hostname (httpcore passes server_hostname)."""

    def __init__(self, resolve: Resolver = system_resolver):
        self._resolve = resolve

    def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        ip = public_ip(host, self._resolve)
        return super().connect_tcp(ip, port, timeout=timeout, local_address=local_address,
                                   socket_options=socket_options)


def _guarded_transport(resolve: Resolver) -> httpx.HTTPTransport:
    transport = httpx.HTTPTransport(trust_env=False)
    transport._pool._network_backend = GuardedBackend(resolve)  # httpx exposes no public hook
    return transport


class Fetcher:
    """Fetches one web page safely: every hop (page and robots.txt) is re-checked, connections go
    only to vetted public IPs, robots.txt is honoured, and size, type and total time are capped."""

    def __init__(self, resolve: Resolver = system_resolver, transport: httpx.BaseTransport | None = None,
                 timeout: float = 10.0, clock: Callable[[], float] = time.monotonic):
        self._resolve = resolve
        self._clock = clock
        self._client = httpx.Client(
            transport=transport or _guarded_transport(resolve), timeout=timeout, follow_redirects=False,
            trust_env=False, headers={"User-Agent": USER_AGENT, "Accept-Encoding": "gzip, identity"},
        )
        self._robots: dict[str, RobotFileParser] = {}

    def close(self) -> None:
        self._client.close()

    def fetch(self, url: str) -> Page:
        deadline = self._clock() + DEADLINE_SECONDS
        try:
            final_url, ctype, raw = self._get(url, deadline, MAX_BYTES, check_robots=True)
            if ctype not in TEXT_TYPES:
                raise FetchError(f"unsupported content type {ctype or 'unknown'}")
            title, text = final_url, raw.decode("utf-8", errors="replace")
            if ctype != "text/plain":
                text = trafilatura.extract(raw) or ""
                meta = trafilatura.extract_metadata(raw)
                title = (meta.title if meta and meta.title else "") or final_url
        except (httpx.HTTPError, ValueError, LookupError, httpcore.ConnectError) as e:
            raise FetchError(f"network error fetching {url}: {type(e).__name__}") from e
        text = text.strip()[:MAX_TEXT]
        if not text:
            raise FetchError("page has no readable text")
        return Page(url, final_url, title, text, now(), hashlib.sha256(text.encode()).hexdigest())

    def _get(self, url: str, deadline: float, cap: int, check_robots: bool) -> tuple[str, str, bytes]:
        """GET with manual redirects; every hop passes the guard (and robots, for pages)."""
        current = url
        for _ in range(MAX_REDIRECTS + 1):
            check_url(current, self._resolve)
            if check_robots and not self._robots_allow(current, deadline):
                raise FetchError(f"robots.txt disallows {current}")
            with self._client.stream("GET", current) as resp:
                if resp.is_redirect:
                    location = resp.headers.get("location")
                    if not location:
                        raise FetchError("redirect without a location")
                    current = str(httpx.URL(current).join(location))
                    continue
                if resp.status_code != 200:
                    raise _Status(resp.status_code, f"HTTP {resp.status_code} from {current}")
                ctype = resp.headers.get("content-type", "").split(";")[0].strip().lower()
                body = bytearray()
                for chunk in resp.iter_bytes():
                    body += chunk
                    if len(body) > cap:
                        raise FetchError(f"response from {current} is larger than {cap / 1e6:g} MB")
                    if self._clock() > deadline:
                        raise FetchError(f"fetch took longer than {DEADLINE_SECONDS:.0f}s")
                if self._clock() > deadline:
                    raise FetchError(f"fetch took longer than {DEADLINE_SECONDS:.0f}s")
                return current, ctype, bytes(body)
        raise FetchError(f"more than {MAX_REDIRECTS} redirects")

    def _robots_allow(self, url: str, deadline: float) -> bool:
        parts = urlsplit(url)
        root = f"{parts.scheme}://{parts.netloc}"
        if root not in self._robots:
            parser = RobotFileParser()
            try:
                _, _, body = self._get(root + "/robots.txt", deadline, MAX_ROBOTS_BYTES, check_robots=False)
                parser.parse(body.decode("utf-8", errors="replace").splitlines())
            except _Status as e:
                if e.code in (401, 403) or e.code >= 500:
                    parser.disallow_all = True
                else:
                    parser.allow_all = True
            except (FetchError, BlockedURL, httpx.HTTPError, ValueError):
                parser.disallow_all = True
            self._robots[root] = parser
        return self._robots[root].can_fetch(USER_AGENT, url)


class _Status(FetchError):
    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code
