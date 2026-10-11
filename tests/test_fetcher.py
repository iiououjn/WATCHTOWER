import httpx
import pytest

from watchtower.engine.beacon.fetcher import MAX_BYTES, FetchError, Fetcher
from watchtower.engine.beacon.netguard import BlockedURL

ARTICLE = ("<html><head><title>Fresnel lens</title></head><body><article><h1>Fresnel lens</h1>"
           + "<p>A Fresnel lens is a compact lens used in lighthouses to project light far out to sea. </p>" * 8
           + "</article></body></html>")
PUBLIC = {"a.example": ["93.184.216.34"], "b.example": ["93.184.216.35"], "evil.example": ["10.0.0.1"]}


def resolve(host):
    if host not in PUBLIC:
        raise OSError("nxdomain")
    return PUBLIC[host]


def fetcher(routes, robots=None):
    seen = []

    def handler(request):
        seen.append(str(request.url))
        if request.url.path == "/robots.txt":
            body = (robots or {}).get(request.url.host)
            return httpx.Response(200, text=body) if body is not None else httpx.Response(404)
        return routes[str(request.url)]()

    return Fetcher(resolve=resolve, transport=httpx.MockTransport(handler)), seen


def html(body=ARTICLE, ctype="text/html; charset=utf-8"):
    return lambda: httpx.Response(200, headers={"content-type": ctype}, text=body)


def test_extracts_main_text_and_metadata():
    f, _ = fetcher({"https://a.example/x": html()})
    page = f.fetch("https://a.example/x")
    assert "compact lens used in lighthouses" in page.text
    assert page.title == "Fresnel lens" and page.final_url == "https://a.example/x"
    assert len(page.sha256) == 64


def test_follows_public_redirect_and_records_final_url():
    f, _ = fetcher({"https://a.example/old": lambda: httpx.Response(301, headers={"location": "https://b.example/new"}),
                    "https://b.example/new": html()})
    assert f.fetch("https://a.example/old").final_url == "https://b.example/new"


def test_redirect_to_private_host_is_blocked_before_request():
    f, seen = fetcher({"https://a.example/x": lambda: httpx.Response(302, headers={"location": "http://evil.example/admin"})})
    with pytest.raises(BlockedURL):
        f.fetch("https://a.example/x")
    assert not any("evil.example" in u for u in seen)


def test_redirect_to_ip_literal_is_blocked():
    f, seen = fetcher({"https://a.example/x": lambda: httpx.Response(302, headers={"location": "http://169.254.169.254/latest"})})
    with pytest.raises(BlockedURL):
        f.fetch("https://a.example/x")


def test_too_many_redirects():
    loop = lambda: httpx.Response(302, headers={"location": "https://a.example/x"})  # noqa: E731
    f, _ = fetcher({"https://a.example/x": loop})
    with pytest.raises(FetchError, match="redirects"):
        f.fetch("https://a.example/x")


def test_size_cap():
    f, _ = fetcher({"https://a.example/big": html(body="x" * (MAX_BYTES + 10))})
    with pytest.raises(FetchError, match="2 MB"):
        f.fetch("https://a.example/big")


def test_unsupported_content_type():
    f, _ = fetcher({"https://a.example/f.pdf": html(ctype="application/pdf")})
    with pytest.raises(FetchError, match="content type"):
        f.fetch("https://a.example/f.pdf")


def test_http_error_status():
    f, _ = fetcher({"https://a.example/x": lambda: httpx.Response(500)})
    with pytest.raises(FetchError, match="HTTP 500"):
        f.fetch("https://a.example/x")


def test_robots_disallow_is_honoured():
    f, seen = fetcher({"https://a.example/private/x": html()},
                      robots={"a.example": "User-agent: *\nDisallow: /private/"})
    with pytest.raises(FetchError, match="robots"):
        f.fetch("https://a.example/private/x")
    assert "https://a.example/private/x" not in seen


def test_plain_text_pages():
    f, _ = fetcher({"https://a.example/t.txt": html(body="plain notes about lenses " * 20, ctype="text/plain")})
    assert f.fetch("https://a.example/t.txt").text.startswith("plain notes")


def test_page_without_readable_text():
    f, _ = fetcher({"https://a.example/x": html(body="<html><body></body></html>")})
    with pytest.raises(FetchError, match="readable"):
        f.fetch("https://a.example/x")
