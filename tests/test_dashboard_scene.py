"""9c: the watchtower scene. A canvas picture of the tower with its staff; same safety rules as the rest of the page."""
import json
import re

from watchtower.dashboard.page import render_page
from watchtower.roles import load_roles

BANNED = ("innerHTML", "outerHTML", "document.write", "eval(", "insertAdjacentHTML", "new Function", "setAttribute('style'",
          "<a ", ".href", "<img", "<iframe", "src=")


def _roster(html: str) -> list[dict]:
    return json.loads(re.search(r"const ROSTER = (\[.*?\]);\n", html, re.S).group(1))


def test_the_page_has_one_full_window_canvas_for_the_scene():
    html = render_page("n")
    assert html.count('<canvas id="scene"') == 1 and 'id="ledger"' in html


def test_the_roster_is_every_role_in_the_org_chart_grouped_by_floor():
    roster = _roster(render_page("n"))
    roles = load_roles()
    assert {r["id"] for r in roster} == set(roles)
    assert all(r["floor"] in ("csuite", "f1", "f2", "f3", "f4", "f5", "glass") for r in roster)
    assert {r["id"]: r["title"] for r in roster} == {i: r.title for i, r in roles.items()}


def test_the_embedded_roster_cannot_break_out_of_the_script_tag(monkeypatch):
    from watchtower import roles
    evil = roles.Role("x.evil", "</script><script>alert(1)</script><!--", "f1", "small", "p")
    monkeypatch.setattr(roles, "load_roles", lambda: {"x.evil": evil})
    html = render_page("n")
    assert "</script><script>alert" not in html and "<!--" not in html.split("const ROSTER")[1].split(";\n")[0]
    assert _roster(html)[0]["title"] == evil.title


def test_the_scene_code_never_writes_html_or_loads_anything():
    html = render_page("n")
    for banned in BANNED:
        assert banned not in html
    assert "fillText" in html and "requestAnimationFrame" in html and "prefers-reduced-motion" in html


def test_the_scene_reads_awake_agents_and_floors_from_the_state():
    from watchtower.dashboard.scene import SCENE_JS
    assert "j.awake" in SCENE_JS and "j.floor" in SCENE_JS and "state.deployments" in SCENE_JS and "SCENE.update(s)" in render_page("n")


def test_a_failing_scene_cannot_stop_the_ledger_or_the_animation_loop():
    html = render_page("n")
    assert "try { SCENE.update(s); }" in html and html.index("fill($('audit')") < html.index("SCENE.update")
    frame = html.split("function frame(ts)")[1]
    assert frame.index("requestAnimationFrame(frame)") < frame.index("sky(k)")


def test_the_page_script_is_valid_javascript(tmp_path):
    import shutil
    import subprocess

    import pytest
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    script = re.search(r"<script nonce=\"n\">(.*)</script>", render_page("n"), re.S).group(1)
    f = tmp_path / "page.js"
    f.write_text(script)
    done = subprocess.run([node, "--check", str(f)], capture_output=True, text=True)
    assert done.returncode == 0, done.stderr


def test_a_scene_that_cannot_start_does_not_stop_the_ledger():
    html = render_page("n")
    assert "let SCENE = { update() {} };" in html and re.search(r"try \{\s*SCENE = ", html).start() < html.index("tick();")


_SMOKE = r"""
const fs = require('fs');
const code = fs.readFileSync(process.argv[2], 'utf8'), roster = JSON.parse(process.argv[3]);
let failure = null; console.error = (...a) => { failure = a.join(' '); };
const bad = (n) => { throw new Error('bad geometry: ' + n); };
const ctx = new Proxy({}, { get: (t, k) => {
  if (k in t) return t[k];
  if (k === 'measureText') return () => ({ width: 50 });
  if (k === 'createLinearGradient' || k === 'createRadialGradient') return (...a) => { if (k === 'createRadialGradient' && (a[2] < 0 || a[5] < 0)) bad(k); return { addColorStop() {} }; };
  if (k === 'arc') return (x, y, r) => { if (!(r >= 0)) bad('arc ' + r); };
  if (k === 'ellipse') return (x, y, rx, ry) => { if (!(rx >= 0 && ry >= 0)) bad('ellipse'); };
  return () => {};
}, set: (t, k, v) => { t[k] = v; return true; } });
const mk = () => ({ width: 0, height: 0, getContext: () => ctx, addEventListener() {} });
const sizes = [[320, 568], [1280, 800], [3840, 2160], [300, 150], [1024, 768]];
for (const [w, h] of sizes) {
  let frame = null;
  const doc = { getElementById: () => mk(), createElement: () => mk() };
  const run = new Function('ROSTER', 'document', 'matchMedia', 'addEventListener', 'requestAnimationFrame', 'innerWidth', 'innerHeight', 'devicePixelRatio',
    'let SCENE; ' + code + '; return SCENE;');
  const scene = run(roster, doc, () => ({ matches: false }), () => {}, (cb) => { frame = cb; }, w, h, 2);
  const job = (floor) => ({ id: 'j1', status: 'running', prompt: 'p', floor, awake: roster.map((r) => r.id), error: null });
  for (const floor of ['f2', 'f4', 'nope', null]) {
    scene.update({ jobs: [job(floor)], deployments: [{ name: 'a', port: 8100 }, { name: 'b', port: 0 }], chain_ok: false });
    for (let i = 0; i < 40; i++) { const cb = frame; frame = null; cb(i * 16); if (!frame) throw new Error('loop stopped'); }
  }
}
if (failure) { console.log(failure); process.exit(1); }
console.log('ok');
"""


def test_the_scene_draws_without_throwing_at_odd_window_sizes(tmp_path):
    import shutil
    import subprocess

    import pytest

    from watchtower.dashboard.scene import SCENE_JS
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    (tmp_path / "scene.js").write_text(SCENE_JS)
    (tmp_path / "smoke.js").write_text(_SMOKE)
    roster = json.dumps([{"id": r["id"], "title": r["title"], "floor": r["floor"]} for r in _roster(render_page("n"))])
    done = subprocess.run([node, str(tmp_path / "smoke.js"), str(tmp_path / "scene.js"), roster], capture_output=True, text=True, timeout=60)
    assert done.returncode == 0 and "ok" in done.stdout, done.stderr
