import httpx
import pytest

from watchtower.beacon.fetcher import MAX_BYTES, FetchError, Fetcher
from watchtower.beacon.netguard import BlockedURL

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


@pytest.mark.parametrize("exc", [httpx.ConnectTimeout("t"), httpx.ConnectError("reset"), httpx.ReadTimeout("r")])
def test_network_errors_become_fetch_errors(exc):
    def boom():
        raise exc

    f, _ = fetcher({"https://a.example/x": boom})
    with pytest.raises(FetchError):
        f.fetch("https://a.example/x")


def test_malformed_redirect_location_is_fetch_error():
    f, _ = fetcher({"https://a.example/x": lambda: httpx.Response(302, headers={"location": "http://[::1"})})
    with pytest.raises((FetchError, BlockedURL)):
        f.fetch("https://a.example/x")


def test_overall_deadline():
    times = [0.0]  # the deadline is set at 0s; every later reading is 30s
    f = Fetcher(resolve=resolve, transport=httpx.MockTransport(
        lambda r: httpx.Response(404) if r.url.path == "/robots.txt" else httpx.Response(
            200, headers={"content-type": "text/html"}, text=ARTICLE)), clock=lambda: times.pop(0) if times else 30.0)
    with pytest.raises(FetchError, match="longer than"):
        f.fetch("https://a.example/x")


def test_huge_robots_txt_is_not_read_whole():
    f, _ = fetcher({"https://a.example/x": html()}, robots={"a.example": "# pad\n" * 200_000 + "Disallow: /x\n"})
    with pytest.raises(FetchError, match="robots"):
        f.fetch("https://a.example/x")


def test_robots_redirect_is_followed_through_the_guard():
    seen = []

    def handler(request):
        seen.append(str(request.url))
        if str(request.url) == "https://a.example/robots.txt":
            return httpx.Response(301, headers={"location": "https://b.example/robots.txt"})
        if str(request.url) == "https://b.example/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: /\n")
        return httpx.Response(200, headers={"content-type": "text/html"}, text=ARTICLE)

    f = Fetcher(resolve=resolve, transport=httpx.MockTransport(handler))
    with pytest.raises(FetchError, match="robots"):
        f.fetch("https://a.example/x")


def test_default_client_ignores_proxy_env_and_guards_connections(monkeypatch):
    from watchtower.beacon.fetcher import GuardedBackend
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:9")
    f = Fetcher(resolve=resolve)
    assert f._client._trust_env is False
    assert isinstance(f._client._transport._pool._network_backend, GuardedBackend)


def test_guarded_backend_refuses_rebound_private_ip():
    from watchtower.beacon.fetcher import GuardedBackend
    with pytest.raises(BlockedURL):
        GuardedBackend(lambda host: ["127.0.0.1"]).connect_tcp("rebind.example", 443)
