"""9e: the hosted demo is a static copy of the 3D page playing a made-up run. It must work under /<repo>/, carry no real data
and publish nothing but JavaScript."""
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from watchtower.dashboard.assets import WEB
from watchtower.dashboard.page import render_page

ROOT = Path(__file__).resolve().parent.parent
NODE = shutil.which("node")
sys.path.insert(0, str(ROOT / "scripts"))
import build_demo  # noqa: E402


def test_the_demo_page_uses_relative_urls_a_meta_csp_and_the_made_up_state():
    html = render_page("ignored", demo=True)
    assert 'src="static/app/demo.js"' in html and 'src="static/app/main.js"' in html and '"./static/vendor/three/three.module.js"' in html
    assert '<meta http-equiv="Content-Security-Policy"' in html and "'nonce-demo'" in html and "unsafe" not in html
    assert not re.search(r'(src|href)="/', html) and '"/static' not in html and "ignored" not in html
    assert html.index("demo.js") < html.index("window.WT = {")
    live = render_page("n0")
    assert "demo.js" not in live and "Content-Security-Policy" not in live and '"/static/vendor/three/three.module.js"' in live


def test_the_build_writes_only_javascript_and_the_licence_and_every_import_resolves(tmp_path):
    out = tmp_path / "site"
    written = build_demo.build(out)
    on_disk = {p.relative_to(out).as_posix() for p in out.rglob("*") if p.is_file()}
    assert on_disk == set(written) | {".nojekyll", "vercel.json", "static/vendor/three/LICENSE"}
    assert all(w == "index.html" or w.endswith(".js") for w in written) and not any(".py" in w or ".db" in w for w in on_disk)
    for f in (out / "static" / "app").glob("*.js"):
        for spec in re.findall(r"from\s+'(\./[^']+)'", f.read_text()):
            assert (f.parent / spec).resolve().is_file(), f"{f.name} imports missing {spec}"
    for f in (out / "static" / "app").glob("*.js"):
        for spec in re.findall(r"from\s+'(three(?:/addons/[^']+)?)'", f.read_text()):
            target = out / "static/vendor/three" / ("three.module.js" if spec == "three" else "addons/" + spec[len("three/addons/"):])
            assert target.is_file(), f"{f.name}: {spec}"
    assert sum(p.stat().st_size for p in out.rglob("*") if p.is_file()) < 6 * 1024 * 1024


_PROBE = r"""
const fs = require('fs'), vm = require('vm');
const ctx = { window: {}, Date, Math, JSON }; vm.createContext(ctx); vm.runInContext(fs.readFileSync(process.argv[2], 'utf8'), ctx);
const roster = new Set(JSON.parse(process.argv[3])); const out = { keys: null, statuses: new Set(), floors: new Set(), bad: [], paused: 0, appr: 0, boats: 0, minAwake: 99, maxAwake: 0 };
for (let t = 1.6e9; t < 1.6e9 + 300; t += 1) {
  const s = ctx.window.WT_DEMO_STATE(t); const text = JSON.stringify(s); if (text.includes('<')) out.bad.push('lt');
  out.keys = Object.keys(s).sort(); for (const j of s.jobs) { out.statuses.add(j.status); if (j.floor) out.floors.add(j.floor); if (j.status !== 'running' && j.awake.length) out.bad.push('awake while ' + j.status); for (const a of j.awake) if (!roster.has(a)) out.bad.push('unknown agent ' + a); out.maxAwake = Math.max(out.maxAwake, j.awake.length); }
  out.paused += s.jobs.filter((j) => j.status === 'paused').length; out.appr += s.approvals.length; out.boats += s.deployments.length;
  for (const d of s.deployments) if (!Number.isInteger(d.port)) out.bad.push('port');
  if (!/^\d{4}-\d\d-\d\dT/.test(s.now) || s.chain_ok !== true) out.bad.push('now/chain');
}
out.statuses = [...out.statuses].sort(); out.floors = [...out.floors].sort(); console.log(JSON.stringify(out));
"""


@pytest.mark.skipif(not NODE, reason="node is not installed")
def test_the_made_up_state_has_the_real_states_shape_and_only_real_agents(tmp_path, settings, conn):
    from watchtower.dashboard.data import state
    real_keys = sorted(state(settings.db_path))
    from watchtower.roles import load_roles
    probe = tmp_path / "probe.js"
    probe.write_text(_PROBE)
    done = subprocess.run([NODE, str(probe), str(WEB / "app" / "demo.js"), json.dumps(sorted(load_roles()))], capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr
    o = json.loads(done.stdout)
    assert o["keys"] == real_keys and o["bad"] == []
    assert o["statuses"] == ["done", "paused", "running"] and o["floors"] == ["csuite", "f1", "f2", "f3", "f4", "f5"]
    assert o["paused"] > 0 and o["appr"] > 0 and o["boats"] > 0 and o["maxAwake"] >= 3


def test_the_pages_workflow_is_least_privilege_pinned_and_gated_by_the_checks():
    wf = (ROOT / ".github" / "workflows" / "pages.yml").read_text()
    assert "scripts/build_demo.py" in wf and "uv run pytest -q" in wf and "uv run ruff check" in wf and "permissions: {}" in wf
    build, deploy = wf.split("  deploy:")
    assert "contents: read" in build and "pages: write" not in build and "id-token" not in build
    assert "pages: write" in deploy and "id-token: write" in deploy and "needs: build" in deploy and "actions/checkout" not in deploy
    assert "pull_request" not in wf and "secrets." not in wf and "cancel-in-progress: false" in wf
    uses = [line for line in wf.splitlines() if "uses:" in line]
    assert len(uses) == 4 and all(re.search(r"uses: [\w./-]+@[0-9a-f]{40} # v\d+", line) for line in uses)
