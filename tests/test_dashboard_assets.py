"""9d: the dashboard serves its own 3D modules and the owner's backdrop photos, and nothing else."""
import json
import re
import threading

import pytest

from test_dashboard_server import _get
from watchtower.dashboard.server import make_server

PNG = b"\x89PNG\r\n\x1a\n" + b"\0" * 64
JPG = b"\xff\xd8\xff\xe0" + b"\0" * 64
WEBP = b"RIFF\x10\0\0\0WEBPVP8 " + b"\0" * 32


@pytest.fixture
def served(conn, settings):
    (settings.home / "backdrops").mkdir()
    server = make_server(settings.db_path, 0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield server
    server.shutdown()
    server.server_close()


def test_a_vendored_module_is_served_as_javascript(served):
    r, data = _get(served, "/static/vendor/three/three.module.js")
    assert r.status == 200 and r.getheader("Content-Type").startswith("text/javascript")
    assert r.getheader("X-Content-Type-Options") == "nosniff" and b"Three.js Authors" in data[:300]


@pytest.mark.parametrize("path", [
    "/static/../server.py", "/static/%2e%2e/server.py", "/static/vendor/../../data.py", "/static/vendor/three/../../../page.py",
    "/static//etc/passwd", "/static/vendor/three/LICENSE", "/static/vendor/three/VERSION", "/static/nope.js", "/static/",
    "/static/vendor\\three\\three.module.js", "/static/vendor/three/three.module.js%00.png", "/static/.hidden.js",
])
def test_nothing_outside_the_web_folder_or_of_another_type_is_served(served, path):
    r, _ = _get(served, path)
    assert r.status == 404


def test_static_files_obey_the_host_check_and_are_read_only(served):
    r, _ = _get(served, "/static/vendor/three/three.module.js", host="evil.example")
    assert r.status == 403
    r, _ = _get(served, "/static/vendor/three/three.module.js", method="POST", body=b"x")
    assert r.status == 405


def test_the_csp_allows_only_own_scripts_and_images(served):
    r, _ = _get(served, "/")
    csp = r.getheader("Content-Security-Policy")
    assert re.search(r"script-src 'nonce-[^']+' 'self'", csp) and "img-src 'self'" in csp and "default-src 'none'" in csp
    assert "unsafe" not in csp and "http" not in csp and "data:" not in csp


def test_backdrops_are_listed_and_served_only_when_they_are_real_images(served, settings):
    d = settings.home / "backdrops"
    (d / "loch.png").write_bytes(PNG)
    (d / "tokyo.jpeg").write_bytes(JPG)
    (d / "wales.webp").write_bytes(WEBP)
    (d / "evil.png").write_bytes(b"<html><script>alert(1)</script>")
    (d / "notes.txt").write_bytes(PNG)
    (d / "sub").mkdir()
    r, data = _get(served, "/api/backdrops")
    assert r.status == 200 and json.loads(data) == ["loch.png", "tokyo.jpeg", "wales.webp"]
    r, data = _get(served, "/backdrops/loch.png")
    assert r.status == 200 and r.getheader("Content-Type") == "image/png" and data == PNG
    assert r.getheader("Cross-Origin-Resource-Policy") == "same-origin"
    assert _get(served, "/backdrops/tokyo.jpeg")[0].getheader("Content-Type") == "image/jpeg"
    for bad in ("evil.png", "notes.txt", "sub", "../watchtower.db", "%2e%2e/watchtower.db", "nope.png", ""):
        assert _get(served, "/backdrops/" + bad)[0].status == 404


def test_a_symlink_out_of_the_backdrop_folder_is_not_followed(served, settings, tmp_path):
    outside = tmp_path / "secret.png"
    outside.write_bytes(PNG)
    (settings.home / "backdrops" / "link.png").symlink_to(outside)
    assert json.loads(_get(served, "/api/backdrops")[1]) == []
    assert _get(served, "/backdrops/link.png")[0].status == 404


def test_the_backdrop_list_needs_the_pages_own_header_and_a_missing_folder_is_empty(served, settings):
    assert _get(served, "/api/backdrops", headers={"X-Watchtower": None})[0].status == 403
    (settings.home / "backdrops").rmdir()
    assert json.loads(_get(served, "/api/backdrops")[1]) == []


def test_an_oversized_backdrop_is_refused(served, settings, monkeypatch):
    from watchtower.dashboard import assets
    monkeypatch.setattr(assets, "MAX_BACKDROP", 100)
    (settings.home / "backdrops" / "big.png").write_bytes(PNG + b"0" * 200)
    assert json.loads(_get(served, "/api/backdrops")[1]) == []
    assert _get(served, "/backdrops/big.png")[0].status == 404


def test_every_listed_backdrop_loads_through_the_url_the_page_builds(served, settings):
    from urllib.parse import quote
    d = settings.home / "backdrops"
    (d / "my sunset.png").write_bytes(PNG)          # a space can never round-trip through an undecoded path, so it is not listed
    (d / "Tokyo_dawn-2.JPG").write_bytes(JPG)
    names = json.loads(_get(served, "/api/backdrops")[1])
    assert names == ["Tokyo_dawn-2.JPG"]
    for n in names:
        assert quote(n, safe="") == n and _get(served, "/backdrops/" + quote(n, safe=""))[0].status == 200


def test_a_js_symlink_inside_web_that_points_outside_is_refused_and_so_is_an_oversized_module(tmp_path, monkeypatch):
    from watchtower.dashboard import assets
    web = tmp_path / "web"
    (web / "app").mkdir(parents=True)
    (tmp_path / "secret.js").write_text("export const k = 'secret'")
    (web / "app" / "link.js").symlink_to(tmp_path / "secret.js")
    (web / "app" / "ok.js").write_text("export const a = 1")
    (web / "app" / "big.js").write_text("x" * 50)
    monkeypatch.setattr(assets, "WEB", web)
    assert assets.read_static("app/link.js") is None and assets.read_static("app/ok.js") is not None
    monkeypatch.setattr(assets, "MAX_STATIC", 10)
    assert assets.read_static("app/big.js") is None
