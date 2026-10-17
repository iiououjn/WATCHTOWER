"""9a: the dashboard page. One static template; every value from the tower is put on the page with textContent,
never as HTML, so model or app text cannot run as markup or script. The nonce lets only this script and style run."""

CSS = """
:root{color-scheme:dark;--bg:#0e1420;--panel:#16202f;--line:#26344a;--text:#e6ecf5;--dim:#8da0ba;--ok:#4ade80;--warn:#fbbf24;--bad:#f87171;--beam:#fde68a}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:14px/1.45 system-ui,sans-serif}
h1{font-size:18px;margin:0}h2{font-size:13px;margin:0 0 8px;color:var(--dim);text-transform:uppercase;letter-spacing:.06em}
html,body{height:100%;overflow:hidden}#stage{position:fixed;inset:0}#stage canvas{display:block;width:100vw;height:100vh}
#hud{position:fixed;inset:0;pointer-events:none;z-index:5;font:13px/1.4 system-ui,sans-serif}#hud>*{pointer-events:auto}
.wt-top{position:absolute;left:14px;top:12px;max-width:min(420px,calc(100vw - 150px));padding:10px 14px;background:rgba(8,14,34,.55);border:1px solid rgba(160,190,255,.25);border-radius:12px;backdrop-filter:blur(8px)}
.wt-title{font-weight:800;font-size:17px;letter-spacing:.04em}.wt-stats{color:#c3d2ee;font-size:12px}.wt-stats.bad{color:var(--bad)}
.wt-jobs{display:flex;flex-direction:column;gap:6px;margin-top:8px}.wt-job{display:flex;flex-direction:column;padding:6px 9px;border-radius:8px;background:rgba(8,14,34,.6);border:1px solid rgba(160,190,255,.25)}
.wt-job b{font:700 11px ui-monospace,Menlo,monospace;color:#fde68a}.wt-job span{font-size:11px;color:#d3def2}
.wt-bar{position:absolute;left:50%;bottom:14px;transform:translateX(-50%);display:flex;flex-direction:column;gap:7px;align-items:center;width:min(980px,calc(100vw - 24px))}
.wt-row{display:flex;flex-wrap:wrap;gap:6px;justify-content:center;align-items:center;padding:6px 8px;background:rgba(8,14,34,.55);border:1px solid rgba(160,190,255,.22);border-radius:14px;backdrop-filter:blur(8px)}
.wt-chip{font:600 12px system-ui,sans-serif;color:#dbe6fb;background:rgba(30,44,80,.7);border:1px solid rgba(160,190,255,.3);border-radius:99px;padding:5px 11px;cursor:pointer}
.wt-chip:hover{background:rgba(60,84,150,.8)}.wt-chip.on{background:#3b63d8;border-color:#9db8ff;color:#fff}.wt-floor.on{background:hsl(var(--hue,210),60%,38%)}
.wt-lbl,.wt-clock{color:#b9c9e6;font-size:12px}.wt-slider{width:min(300px,40vw);accent-color:#fbbf24}
.wt-tip{position:fixed;left:var(--x,0);top:var(--y,0);padding:7px 11px;border-radius:9px;background:rgba(8,10,24,.94);border:1px solid #8ba7ff;display:flex;flex-direction:column;pointer-events:none;color:#fff;font-size:12px}
.wt-tip span{color:#aab8d6}
#ledger{position:fixed;right:14px;top:14px;z-index:9;max-width:min(560px,calc(100vw - 28px));max-height:calc(100vh - 28px);overflow:auto;background:rgba(10,14,30,.88);border:1px solid var(--line);border-radius:10px;padding:8px 12px;backdrop-filter:blur(6px)}
#ledger summary{cursor:pointer;font-weight:600}.drawer{margin-top:10px}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:12px 14px;margin-bottom:16px}
.chip{display:inline-block;margin:2px 4px 0 0;padding:1px 7px;border-radius:99px;background:#26344a;font-size:12px}
table{width:100%;border-collapse:collapse}td,th{text-align:left;padding:4px 6px;border-bottom:1px solid var(--line);vertical-align:top;word-break:break-word}
th{color:var(--dim);font-weight:500;font-size:12px}
.s-done{color:var(--ok)}.s-failed{color:var(--bad)}.s-paused{color:var(--warn)}.s-running{color:var(--beam)}
.meter{height:6px;background:#26344a;border-radius:3px;overflow:hidden}.meter i{display:block;height:100%;background:var(--ok)}
.mono{font-family:ui-monospace,Menlo,monospace;font-size:12px}.empty{color:var(--dim)}.bad{color:var(--bad)}
"""

JS = """
const $ = (id) => document.getElementById(id);
const ROSTER = %ROSTER%;
window.WT = { roster: ROSTER, state: null, listeners: [] };   // the 3D scene (a module) subscribes here; the ledger works without it
function el(tag, text, cls) { const e = document.createElement(tag); if (text !== undefined && text !== null) e.textContent = String(text); if (cls) e.className = cls; return e; }
function fill(node, kids) { node.replaceChildren(...kids); }
function table(heads, rows, empty) {
  if (!rows.length) return [el('div', empty, 'empty')];
  const t = el('table'), h = el('tr');
  heads.forEach((x) => h.append(el('th', x)));
  t.append(h);
  rows.forEach((r) => { const tr = el('tr'); r.forEach((c) => tr.append(c instanceof Node ? c : el('td', c))); t.append(tr); });
  return [t];
}
function cellWith(node) { const td = el('td'); td.append(node); return td; }
function render(s) {
  fill($('approvals'), table(['id', 'job', 'kind', 'summary'], s.approvals.map((a) => [a.id, a.job_id, a.kind, a.summary.slice(0, 160)]),
    'Nothing waiting for you.'));
  fill($('jobs'), table(['job', 'status', 'floor', 'prompt'], s.jobs.map((j) =>
    [j.id, cellWith(el('span', j.status, 's-' + j.status)), j.floor || (j.status === 'done' || j.status === 'failed' ? '-' : 'planning'), j.prompt.slice(0, 120) + (j.error ? ' | ' + j.error.slice(0, 120) : '')]), 'No jobs yet.'));
  fill($('deployments'), table(['app', 'job', 'address', 'since'], s.deployments.map((d) =>
    [d.name, d.job_id, d.port ? '127.0.0.1:' + d.port : '-', d.created_at.slice(0, 19)]), 'No apps deployed.'));
  fill($('budgets'), table(['job', 'tokens', 'time'], s.budgets.map((b) => {
    const m = el('div', null, 'meter'), i = el('i'); i.style.width = Math.min(100, 100 * b.used_tokens / Math.max(1, b.max_tokens)) + '%'; m.append(i);
    return [b.job_id, cellWith((() => { const d = el('div'); d.append(el('span', b.used_tokens + ' / ' + b.max_tokens, 'mono'), m); return d; })()), b.used_seconds + ' / ' + b.max_seconds + ' s'];
  }), 'No budgets yet.'));
  fill($('audit'), table(['#', 'time', 'actor', 'action', 'detail'], s.audit.slice().reverse().map((e) =>
    [e.seq, e.ts.slice(11, 19), e.actor, e.action, cellWith(el('span', e.detail.slice(0, 200), 'mono'))]), 'No audit entries.'));
  $('chain').textContent = s.chain_ok ? 'audit chain ok' : 'AUDIT CHAIN BROKEN';
  $('chain').className = s.chain_ok ? '' : 'bad';
  WT.state = s; WT.listeners.forEach((f) => { try { f(s); } catch (e) { /* the scene must never take the ledger down */ } });
  $('status').textContent = 'updated ' + s.now.slice(11, 19);
}
async function tick() {
  try {
    if (window.WT_DEMO_STATE) { render(window.WT_DEMO_STATE(Date.now() / 1000)); return; }   // the hosted demo plays a made-up run; it never talks to a tower
    const r = await fetch('api/state', { cache: 'no-store', headers: { 'X-Watchtower': '1' } });
    if (!r.ok) throw new Error('HTTP ' + r.status);
    render(await r.json());
  } catch (e) { $('status').textContent = 'cannot reach the tower database (' + e.message + ')'; }
}
tick(); setInterval(tick, 3000);
"""

BODY = """<div id="stage"></div><div id="hud"></div>
<details id="ledger"><summary>Ledger <span id="status" class="empty">loading</span> <span id="chain" class="empty"></span></summary>
<div class="drawer"><div class="panel"><h2>Waiting for you</h2><div id="approvals"></div></div>
<div class="panel"><h2>Jobs</h2><div id="jobs"></div></div>
<div class="panel"><h2>Deployed apps</h2><div id="deployments"></div></div>
<div class="panel"><h2>Budgets</h2><div id="budgets"></div></div>
<div class="panel"><h2>Audit log</h2><div id="audit"></div></div></div></details>"""


IMPORTMAP = '{"imports":{"three":"/static/vendor/three/three.module.js","three/addons/":"/static/vendor/three/addons/"}}'
DEMO_CSP = ("default-src 'none'; script-src 'self' 'nonce-demo'; style-src 'nonce-demo'; img-src 'self'; connect-src 'self'; "
            "base-uri 'none'; form-action 'none'")


def render_page(nonce: str, demo: bool = False) -> str:
    """The live page (strict CSP header, nonce per response) or, with demo=True, the static copy for GitHub Pages: relative
    URLs so it works under /<repo>/, a made-up run instead of the tower's state, and its CSP in a meta tag."""
    import json

    from watchtower.roles import load_roles

    roster = [{"id": r.id, "title": r.title, "floor": r.floor.replace("c-suite", "csuite")} for r in load_roles().values()]
    js = JS.replace("%ROSTER%", json.dumps(roster).replace("<", "\\u003c"))
    imap, main, pre, meta = IMPORTMAP, "/static/app/main.js", "", ""
    if demo:
        nonce = "demo"
        imap, main = IMPORTMAP.replace('"/static/', '"./static/'), "static/app/main.js"
        pre = f'<script nonce="{nonce}" src="static/app/demo.js"></script>'
        meta = f'<meta http-equiv="Content-Security-Policy" content="{DEMO_CSP}">'
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">{meta}'
            f'<title>The Watchtower</title><style nonce="{nonce}">{CSS}</style></head><body>{BODY}{pre}'
            f'<script nonce="{nonce}">{js}</script>'
            f'<script type="importmap" nonce="{nonce}">{imap}</script>'
            f'<script type="module" nonce="{nonce}" src="{main}"></script></body></html>')
