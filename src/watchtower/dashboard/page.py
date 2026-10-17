"""9a: the dashboard page. One static template; every value from the tower is put on the page with textContent,
never as HTML, so model or app text cannot run as markup or script. The nonce lets only this script and style run."""

FLOORS = [("f5", "F5 Oversight"), ("f4", "F4 Deploy / QA"), ("f3", "F3 Build"), ("f2", "F2 Dev"), ("f1", "F1 Research")]

CSS = """
:root{color-scheme:dark;--bg:#0e1420;--panel:#16202f;--line:#26344a;--text:#e6ecf5;--dim:#8da0ba;--ok:#4ade80;--warn:#fbbf24;--bad:#f87171;--beam:#fde68a}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:14px/1.45 system-ui,sans-serif}
header{display:flex;gap:16px;align-items:baseline;padding:14px 20px;border-bottom:1px solid var(--line)}
h1{font-size:18px;margin:0}h2{font-size:13px;margin:0 0 8px;color:var(--dim);text-transform:uppercase;letter-spacing:.06em}
main{display:grid;grid-template-columns:minmax(260px,340px) 1fr;gap:16px;padding:16px 20px}
@media(max-width:800px){main{grid-template-columns:1fr}}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:12px 14px;margin-bottom:16px}
#tower{display:flex;flex-direction:column;align-items:center;gap:0}
#beacon{width:18px;height:18px;border-radius:50%;background:#394a63;margin-bottom:4px}
#beacon.on{background:var(--beam);animation:spin 1.6s ease-in-out infinite alternate}
@keyframes spin{from{box-shadow:-18px 0 14px -4px var(--beam)}to{box-shadow:18px 0 14px -4px var(--beam)}}
.floor{width:100%;border:1px solid var(--line);background:#101a29;padding:8px 10px;min-height:46px}
.floor:nth-of-type(odd){background:#132033}.floor.lit{background:#2a2a14;border-color:var(--warn)}
.floor b{font-size:12px;color:var(--dim);display:block}
.chip{display:inline-block;margin:2px 4px 0 0;padding:1px 7px;border-radius:99px;background:#26344a;font-size:12px}
#engine{width:100%;margin-top:6px;border:1px dashed var(--line);border-radius:6px;padding:8px 10px;color:var(--dim);font-size:12px}
table{width:100%;border-collapse:collapse}td,th{text-align:left;padding:4px 6px;border-bottom:1px solid var(--line);vertical-align:top;word-break:break-word}
th{color:var(--dim);font-weight:500;font-size:12px}
.s-done{color:var(--ok)}.s-failed{color:var(--bad)}.s-paused{color:var(--warn)}.s-running{color:var(--beam)}
.meter{height:6px;background:#26344a;border-radius:3px;overflow:hidden}.meter i{display:block;height:100%;background:var(--ok)}
.mono{font-family:ui-monospace,Menlo,monospace;font-size:12px}.empty{color:var(--dim)}.bad{color:var(--bad)}
"""

JS = """
const $ = (id) => document.getElementById(id);
const FLOORS = %FLOORS%;
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
  const running = s.jobs.filter((j) => j.status === 'running');
  $('beacon').className = running.length ? 'on' : '';
  fill($('tower'), [$('beacon'), ...FLOORS.map(([key, name]) => {
    const f = el('div', null, 'floor'), here = s.jobs.filter((j) => j.floor === key && (j.status === 'running' || j.status === 'paused'));
    f.append(el('b', name)); here.forEach((j) => f.append(el('span', j.id + ' ' + j.status, 'chip')));
    if (here.length) f.classList.add('lit');
    return f;
  })]);
  const awake = [...new Set(running.flatMap((j) => j.awake))];
  $('engine').textContent = 'Ground engine: ' + (awake.length ? awake.join(', ') + ' working' : 'idle');
  fill($('approvals'), table(['id', 'job', 'kind', 'summary'], s.approvals.map((a) => [a.id, a.job_id, a.kind, a.summary.slice(0, 160)]),
    'Nothing waiting for you.'));
  fill($('jobs'), table(['job', 'status', 'floor', 'prompt'], s.jobs.map((j) =>
    [j.id, cellWith(el('span', j.status, 's-' + j.status)), j.floor || (j.status === 'done' || j.status === 'failed' ? '-' : 'planning'), j.prompt.slice(0, 120) + (j.error ? ' | ' + j.error.slice(0, 120) : '')]), 'No jobs yet.'));
  fill($('budgets'), table(['job', 'tokens', 'time'], s.budgets.map((b) => {
    const m = el('div', null, 'meter'), i = el('i'); i.style.width = Math.min(100, 100 * b.used_tokens / Math.max(1, b.max_tokens)) + '%'; m.append(i);
    return [b.job_id, cellWith((() => { const d = el('div'); d.append(el('span', b.used_tokens + ' / ' + b.max_tokens, 'mono'), m); return d; })()), b.used_seconds + ' / ' + b.max_seconds + ' s'];
  }), 'No budgets yet.'));
  fill($('audit'), table(['#', 'time', 'actor', 'action', 'detail'], s.audit.slice().reverse().map((e) =>
    [e.seq, e.ts.slice(11, 19), e.actor, e.action, cellWith(el('span', e.detail.slice(0, 200), 'mono'))]), 'No audit entries.'));
  $('chain').textContent = s.chain_ok ? 'audit chain ok' : 'AUDIT CHAIN BROKEN';
  $('chain').className = s.chain_ok ? '' : 'bad';
  $('status').textContent = 'updated ' + s.now.slice(11, 19);
}
async function tick() {
  try {
    const r = await fetch('/api/state', { cache: 'no-store', headers: { 'X-Watchtower': '1' } });
    if (!r.ok) throw new Error('HTTP ' + r.status);
    render(await r.json());
  } catch (e) { $('status').textContent = 'cannot reach the tower database (' + e.message + ')'; }
}
tick(); setInterval(tick, 3000);
"""

BODY = """<header><h1>THE WATCHTOWER</h1><span id="status" class="empty">loading</span><span id="chain" class="empty"></span>
<span class="empty">read only</span></header>
<main><section class="panel"><h2>Lighthouse</h2><div id="tower"><div id="beacon"></div></div><div id="engine"></div></section>
<section><div class="panel"><h2>Waiting for you</h2><div id="approvals"></div></div>
<div class="panel"><h2>Jobs</h2><div id="jobs"></div></div>
<div class="panel"><h2>Budgets</h2><div id="budgets"></div></div>
<div class="panel"><h2>Audit log</h2><div id="audit"></div></div></section></main>"""


def render_page(nonce: str) -> str:
    import json

    js = JS.replace("%FLOORS%", json.dumps([list(f) for f in FLOORS]))
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>The Watchtower</title><style nonce="{nonce}">{CSS}</style></head><body>{BODY}'
            f'<script nonce="{nonce}">{js}</script></body></html>')
