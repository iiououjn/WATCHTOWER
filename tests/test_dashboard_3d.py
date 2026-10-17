"""9d: the 3D office. The page loads its own pinned three.js and app modules; nothing it loads or draws can come from
anywhere else, and the pure rules (sun, activity, roster) are checked in plain node."""
import hashlib
import json
import re
import shutil
import subprocess
import threading
from pathlib import Path

import pytest

from test_dashboard_server import _get
from watchtower.dashboard.assets import WEB
from watchtower.dashboard.page import render_page
from watchtower.dashboard.server import make_server
from watchtower.roles import load_roles

APP = WEB / "app"
VENDOR = WEB / "vendor" / "three"
NODE = shutil.which("node")
needs_node = pytest.mark.skipif(not NODE, reason="node is not installed")
BANNED = ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", "new Function", "setAttribute('style'", ".href", "http://", "https://", "XMLHttpRequest", "WebSocket", "localStorage", "import(")


@pytest.fixture
def served(conn, settings):
    server = make_server(settings.db_path, 0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield server
    server.shutdown()
    server.server_close()


def _roster(html):
    return json.loads(re.search(r"const ROSTER = (\[.*?\]);\n", html, re.S).group(1))


def test_the_page_loads_its_modules_through_a_nonce_import_map():
    html = render_page("n0")
    assert '<script type="importmap" nonce="n0">' in html and '<script type="module" nonce="n0" src="/static/app/main.js">' in html
    imap = json.loads(re.search(r'<script type="importmap" nonce="n0">(.*?)</script>', html).group(1))["imports"]
    assert imap == {"three": "/static/vendor/three/three.module.js", "three/addons/": "/static/vendor/three/addons/"}
    assert 'id="stage"' in html and 'id="hud"' in html and 'id="ledger"' in html and "window.WT = { roster: ROSTER" in html


def test_the_roster_is_every_role_and_cannot_close_the_script_tag(monkeypatch):
    roster = _roster(render_page("n"))
    roles = load_roles()
    assert {r["id"] for r in roster} == set(roles) and {r["id"]: r["title"] for r in roster} == {i: r.title for i, r in roles.items()}
    from watchtower import roles as roles_mod
    evil = roles_mod.Role("x.evil", "</script><script>alert(1)</script><!--", "f1", "small", "p")
    monkeypatch.setattr(roles_mod, "load_roles", lambda: {"x.evil": evil})
    html = render_page("n")
    assert "</script><script>alert" not in html and _roster(html)[0]["title"] == evil.title


def _imports(path: Path) -> list[str]:
    return re.findall(r"(?:^|\n)\s*import\s[^;]*?from\s+'([^']+)'", path.read_text())


def _resolve(spec: str, frm: Path) -> Path:
    if spec == "three":
        return VENDOR / "three.module.js"
    if spec.startswith("three/addons/"):
        return VENDOR / "addons" / spec[len("three/addons/"):]
    return (frm.parent / spec).resolve()


def test_every_module_the_app_imports_exists_and_is_served(served):
    seen, todo = set(), [APP / "main.js"]
    while todo:
        f = todo.pop()
        if f in seen:
            continue
        assert f.is_file(), f"missing module {f}"
        seen.add(f)
        todo += [_resolve(s, f) for s in _imports(f)]
    assert len(seen) > 20
    for f in sorted(seen):
        rel = f.relative_to(WEB).as_posix()
        r, data = _get(served, "/static/" + rel)
        assert r.status == 200 and data == f.read_bytes(), rel


def test_the_vendored_three_js_matches_its_pinned_hashes_and_nothing_extra_is_there():
    sums = dict(reversed(line.split("  ", 1)) for line in (VENDOR / "SHA256SUMS").read_text().splitlines())
    on_disk = {"./" + p.relative_to(VENDOR).as_posix() for p in VENDOR.rglob("*") if p.is_file() and p.name != "SHA256SUMS"}
    assert set(sums) == on_disk and (VENDOR / "VERSION").read_text().startswith("three 0.186.1")
    for rel, digest in sums.items():
        assert hashlib.sha256((VENDOR / rel).read_bytes()).hexdigest() == digest, rel


def test_app_code_never_writes_html_loads_remote_files_or_stores_anything():
    files = sorted(APP.glob("*.js"))
    assert {f.name for f in files} >= {"main.js", "tower.js", "offices.js", "people.js", "furniture.js", "sky.js", "water.js", "hud.js", "logic.js", "util.js", "envs.js"}
    for f in files:
        text = f.read_text()
        for banned in BANNED:
            assert banned not in text, f"{f.name} uses {banned}"
        assert len(text.splitlines()) < 500, f"{f.name} is over 500 lines"


def test_every_place_has_a_builder_a_name_a_view_and_a_light():
    logic = (APP / "logic.js").read_text()
    places = re.findall(r"'(\w+)'", re.search(r"PLACES = \[(.*?)\]", logic).group(1))
    builders = re.findall(r"\w+", re.search(r"const BUILD = \{(.*?)\}", (APP / "envs.js").read_text()).group(1))
    assert places == ["ocean", "scotland", "wales", "mumbai", "japan", "korea", "usa", "dubai"] and set(builders) == set(places)
    for table in ("PLACE_NAMES", "PLACE_VIEW", "PLACE_HOUR"):
        assert set(re.findall(r"(\w+):", re.search(table + r" = \{(.*?)\}", logic, re.S).group(1))) == set(places), table


@needs_node
def test_app_modules_are_valid_javascript(tmp_path):
    for f in sorted(APP.glob("*.js")):
        copy = tmp_path / (f.stem + ".mjs")
        copy.write_text(f.read_text())
        done = subprocess.run([NODE, "--check", str(copy)], capture_output=True, text=True)
        assert done.returncode == 0, f"{f.name}: {done.stderr}"


_LOGIC = r"""
import * as L from '%s';
const out = {};
out.noon = Math.round(L.sunElevation(12)); out.dawn = Math.round(L.sunElevation(6)); out.night = L.daylight(0); out.day = L.daylight(12); out.dusk = L.daylight(18.2);
const a = L.activity({ jobs: [
  { id: 'a', status: 'running', floor: 'f2', awake: ['f2.coder', 'ceo'] }, { id: 'b', status: 'paused', floor: 'f5', awake: ['f5.gate'] },
  { id: 'c', status: 'done', floor: 'f1', awake: ['f1.lead'] }, { id: 'd', status: 'running', floor: 'dev', awake: [] } ] });
out.awake = [...a.awake].sort(); out.lit = [...a.lit].sort(); out.floorOf = [...a.floorOf].sort();
out.empty = (() => { const e = L.activity(null); return [e.awake.size, e.lit.size]; })();
out.by = Object.fromEntries(Object.entries(L.rosterByFloor([{ id: 'x', floor: 'f1' }, { id: 'y', floor: 'f1' }, { id: 'z', floor: 'nope' }])).map(([k, v]) => [k, v.length]));
out.title = L.shortTitle('Oversight Gate Reviewer (code) with a very long extra name'); out.addr = [L.addressOf({ port: 8100 }), L.addressOf({ port: 0 }), L.addressOf(null)];
out.clamp = [L.clamp(5, 0, 1), L.clamp(-5, 0, 1)]; out.floors = L.FLOORS;
console.log(JSON.stringify(out));
"""


@needs_node
def test_the_pure_rules_behave(tmp_path):
    script = tmp_path / "t.mjs"
    script.write_text(_LOGIC % (APP / "logic.js").as_posix())
    done = subprocess.run([NODE, str(script)], capture_output=True, text=True, timeout=30)
    assert done.returncode == 0, done.stderr
    o = json.loads(done.stdout)
    assert o["noon"] == 62 and o["dawn"] == 0 and o["night"] == 0 and o["day"] == 1 and 0 < o["dusk"] < 1
    assert o["awake"] == ["ceo", "f2.coder"]      # only running jobs wake agents
    assert o["lit"] == ["f2", "f5"] and o["floorOf"] == [["a", "f2"], ["b", "f5"], ["c", "f1"]] and o["empty"] == [0, 0]
    assert o["by"]["f1"] == 2 and o["by"]["f2"] == 0 and len(o["title"]) <= 26 and "(" not in o["title"]
    assert o["addr"] == ["127.0.0.1:8100", "-", "-"] and o["clamp"] == [1, 0] and o["floors"][0] == "csuite" and o["floors"][-1] == "f1"
