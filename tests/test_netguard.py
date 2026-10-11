import pytest

from watchtower.engine.beacon.netguard import BlockedURL, check_url


def resolver(mapping):
    def resolve(host):
        if host not in mapping:
            raise OSError("nxdomain")
        return mapping[host]
    return resolve


def test_public_url_allowed():
    assert check_url("https://en.wikipedia.org/wiki/X", resolver({"en.wikipedia.org": ["208.80.154.224"]})) \
        == "en.wikipedia.org"


@pytest.mark.parametrize("ip", ["127.0.0.1", "10.0.0.5", "192.168.1.1", "172.16.0.1", "169.254.169.254",
                                "100.64.0.1", "0.0.0.0", "::1", "fe80::1", "::ffff:127.0.0.1", "fc00::1"])
def test_non_public_addresses_blocked(ip):
    with pytest.raises(BlockedURL):
        check_url("http://evil.example/", resolver({"evil.example": [ip]}))


def test_any_private_address_among_many_blocks():
    with pytest.raises(BlockedURL):
        check_url("http://mixed.example/", resolver({"mixed.example": ["93.184.216.34", "10.0.0.1"]}))


@pytest.mark.parametrize("url", ["file:///etc/passwd", "ftp://x.example/", "gopher://x.example/",
                                 "javascript:alert(1)", "http:///nohost", "https://user:pw@x.example/"])
def test_bad_urls_blocked(url):
    with pytest.raises(BlockedURL):
        check_url(url, resolver({"x.example": ["93.184.216.34"]}))


def test_unresolvable_blocked():
    with pytest.raises(BlockedURL, match="resolve"):
        check_url("https://nope.example/", resolver({}))
