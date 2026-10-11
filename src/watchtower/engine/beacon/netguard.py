from __future__ import annotations

import ipaddress
import socket
from typing import Callable
from urllib.parse import urlsplit

Resolver = Callable[[str], list[str]]


class BlockedURL(Exception):
    pass


def system_resolver(host: str) -> list[str]:
    return [info[4][0] for info in socket.getaddrinfo(host, None)]


def check_url(url: str, resolve: Resolver = system_resolver) -> str:
    """Allow only http(s) URLs whose host resolves exclusively to public IPs.
    Blocks localhost, private/link-local/cloud-metadata ranges and IPv4-mapped tricks."""
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        raise BlockedURL(f"scheme {parts.scheme or '(none)'!r} not allowed")
    if parts.username or parts.password:
        raise BlockedURL("credentials in URL not allowed")
    host = parts.hostname
    if not host:
        raise BlockedURL("URL has no host")
    public_ip(host, resolve)
    return host


def public_ip(host: str, resolve: Resolver = system_resolver) -> str:
    """Resolve host and return an address to connect to, only if every address is public."""
    try:
        addresses = resolve(host)
    except OSError as e:
        raise BlockedURL(f"cannot resolve {host}") from e
    if not addresses:
        raise BlockedURL(f"cannot resolve {host}")
    for raw in addresses:
        ip = ipaddress.ip_address(raw.split("%")[0])
        if ip.version == 6 and ip.ipv4_mapped:
            ip = ip.ipv4_mapped
        if not ip.is_global:
            raise BlockedURL(f"{host} resolves to non-public address {ip}")
    return addresses[0].split("%")[0]
