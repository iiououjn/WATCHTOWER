"""9c: the watchtower scene. One canvas, vanilla JS, no assets: a night coast, the tower cut open so every floor shows its
staff at work, job packets riding the lift between floors, deployed apps as lit huts on the shore. Text goes on the
canvas with fillText only; nothing here builds HTML. Read-only: it just draws the state the page already polls."""

SCENE_JS = r"""
const SCENE = (() => {
  const cv = document.getElementById('scene'), g = cv.getContext('2d');
  const REDUCED = matchMedia('(prefers-reduced-motion: reduce)').matches;
  const ORDER = ['csuite', 'f5', 'f4', 'f3', 'f2', 'f1'];
  const NAMES = { csuite: 'PENTHOUSE  C-suite', f5: 'F5  Oversight', f4: 'F4  QA & Deploy', f3: 'F3  Build', f2: 'F2  Dev', f1: 'F1  Research' };
  const HUE = { csuite: 48, f5: 285, f4: 160, f3: 28, f2: 205, f1: 120 };
  let W = 0, H = 0, dpr = 1, T = 0, last = 0, mouse = { x: -1, y: -1 };
  let state = { jobs: [], deployments: [], chain_ok: true };
  const awake = new Set(), lit = new Set(), prevFloor = new Map(), packets = [], shooting = [];
  const stars = Array.from({ length: 180 }, (_, i) => ({ x: ((i * 9301 + 49297) % 233280) / 233280, y: ((i * 4321 + 7919) % 233280) / 233280 * 0.62, r: 0.4 + (i % 5) * 0.25, p: i * 1.7 }));
  const staff = ROSTER.filter((r) => ORDER.includes(r.floor)).map((r, i) => ({ ...r, i, x: 0, tx: 0, w: 0, wait: 1 + (i % 7), face: 1, seed: i * 2.39 }));
  const byFloor = Object.fromEntries(ORDER.map((f) => [f, staff.filter((s) => s.floor === f)]));
  const rnd = (a) => { const v = Math.sin(a * 127.1) * 43758.5453; return v - Math.floor(v); };
  const hsl = (h, s, l, a = 1) => `hsla(${h},${s}%,${l}%,${a})`;
  let L = {};

  function layout() {
    dpr = Math.min(2, devicePixelRatio || 1); W = innerWidth; H = innerHeight;
    cv.width = W * dpr; cv.height = H * dpr; g.setTransform(dpr, 0, 0, dpr, 0, 0);
    const base = H * 0.88, fh = Math.max(52, Math.min(96, (H * 0.74) / 7.2)), tw = Math.max(300, Math.min(W * 0.5, 600));
    L = { base, fh, tw, cx: W / 2, top: base - fh * 6 - fh * 0.12, rooms: {} };
    ORDER.forEach((f, k) => { L.rooms[f] = { y: base - fh * (ORDER.length - k), h: fh }; });
    L.wallL = (y) => L.cx - (tw / 2) * (0.78 + 0.22 * Math.min(1, Math.max(0, (y - L.top) / (base - L.top))));
    L.wallR = (y) => L.cx + (tw / 2) * (0.78 + 0.22 * Math.min(1, Math.max(0, (y - L.top) / (base - L.top))));
    staff.forEach((s) => { const row = byFloor[s.floor], n = row.length, k = row.indexOf(s); s.home = (k + 0.5) / n; s.x = s.tx = s.home; });
  }

  function update(s) {
    state = s; awake.clear(); lit.clear();
    s.jobs.forEach((j) => {
      if (j.status === 'running') (j.awake || []).forEach((a) => awake.add(a));
      if ((j.status === 'running' || j.status === 'paused') && j.floor) lit.add(j.floor);
      const was = prevFloor.get(j.id);
      if (j.floor && was && was !== j.floor && L.rooms && L.rooms[was] && L.rooms[j.floor]) packets.push({ from: was, to: j.floor, t: 0, id: j.id });
      if (j.floor) prevFloor.set(j.id, j.floor);
    });
  }

  function sky() {
    const gr = g.createLinearGradient(0, 0, 0, H);
    gr.addColorStop(0, '#04061a'); gr.addColorStop(0.45, '#12123a'); gr.addColorStop(0.75, '#2a1c4d'); gr.addColorStop(1, '#0b2540');
    g.fillStyle = gr; g.fillRect(0, 0, W, H);
    stars.forEach((s) => { const a = 0.35 + 0.65 * (0.5 + 0.5 * Math.sin(T * 1.3 + s.p)); g.fillStyle = `rgba(255,255,255,${a})`; g.beginPath(); g.arc(s.x * W, s.y * H, s.r, 0, 6.3); g.fill(); });
    if (!REDUCED) for (let b = 0; b < 3; b++) {   // aurora ribbons
      g.beginPath(); const y0 = H * (0.16 + b * 0.07);
      for (let x = 0; x <= W; x += 14) { const y = y0 + Math.sin(x * 0.004 + T * 0.35 + b * 2) * 38 + Math.sin(x * 0.011 - T * 0.2) * 14; x ? g.lineTo(x, y) : g.moveTo(x, y); }
      g.lineTo(W, y0 + 120); g.lineTo(0, y0 + 120); g.closePath();
      const ag = g.createLinearGradient(0, y0 - 40, 0, y0 + 120); const h = 150 + b * 55;
      ag.addColorStop(0, hsl(h, 90, 60, 0.0)); ag.addColorStop(0.35, hsl(h, 90, 60, 0.13)); ag.addColorStop(1, hsl(h, 90, 60, 0));
      g.fillStyle = ag; g.fill();
    }
    const mx = W * 0.82, my = H * 0.17;                    // moon
    const mg = g.createRadialGradient(mx, my, 6, mx, my, 120); mg.addColorStop(0, 'rgba(255,248,220,.35)'); mg.addColorStop(1, 'rgba(255,248,220,0)');
    g.fillStyle = mg; g.fillRect(mx - 120, my - 120, 240, 240);
    g.fillStyle = '#fff6dc'; g.beginPath(); g.arc(mx, my, 24, 0, 6.3); g.fill();
    g.fillStyle = 'rgba(180,170,150,.35)'; [[-7, -5, 5], [6, 6, 4], [4, -9, 3]].forEach(([a, b, r]) => { g.beginPath(); g.arc(mx + a, my + b, r, 0, 6.3); g.fill(); });
    if (!REDUCED && Math.random() < 0.004) shooting.push({ x: Math.random() * W, y: Math.random() * H * 0.3, t: 0 });
    for (let i = shooting.length - 1; i >= 0; i--) {
      const m = shooting[i]; m.t += 0.02; const x = m.x + m.t * 260, y = m.y + m.t * 110;
      const sg = g.createLinearGradient(x, y, x - 90, y - 38); sg.addColorStop(0, 'rgba(255,255,255,.9)'); sg.addColorStop(1, 'rgba(255,255,255,0)');
      g.strokeStyle = sg; g.lineWidth = 2; g.beginPath(); g.moveTo(x, y); g.lineTo(x - 90, y - 38); g.stroke();
      if (m.t > 1) shooting.splice(i, 1);
    }
    for (let c = 0; c < 4; c++) {                          // drifting clouds
      const x = ((T * (6 + c * 3) + c * 400) % (W + 400)) - 200, y = H * (0.28 + c * 0.05);
      g.fillStyle = 'rgba(120,120,190,.10)'; [[0, 0, 70, 16], [40, -8, 50, 14], [-40, 4, 45, 12]].forEach(([a, b, rx, ry]) => { g.beginPath(); g.ellipse(x + a, y + b, rx, ry, 0, 0, 6.3); g.fill(); });
    }
  }

  function land() {
    const hy = L.base + 6;
    [[0.62, '#161a3e', 0.55, 0.0021], [0.74, '#101636', 0.42, 0.0033], [0.84, '#0a1128', 0.32, 0.0049]].forEach(([k, col, amp, f], n) => {
      g.fillStyle = col; g.beginPath(); g.moveTo(0, H);
      for (let x = 0; x <= W; x += 12) g.lineTo(x, H * k + Math.sin(x * f + n * 3) * 55 * amp + Math.sin(x * f * 2.7 + n) * 22 * amp);
      g.lineTo(W, H); g.closePath(); g.fill();
    });
    const sea = g.createLinearGradient(0, hy, 0, H); sea.addColorStop(0, '#0d2d4f'); sea.addColorStop(1, '#04101f');
    g.fillStyle = sea; g.fillRect(0, hy, W, H - hy);
    for (let i = 0; i < 46; i++) {                          // moon glitter + swell lines
      const y = hy + 8 + (i / 46) * (H - hy), x = W * 0.82 + Math.sin(T * 0.8 + i) * (10 + i * 1.6), w = 14 + i * 1.3;
      g.fillStyle = `rgba(255,246,220,${0.22 - i * 0.004})`; g.fillRect(x - w / 2, y, w, 1.6);
      g.fillStyle = 'rgba(120,170,255,.07)'; g.fillRect(((i * 97 + T * 12) % W), y + 3, 60 + i, 1);
    }
    g.fillStyle = '#10121f'; g.beginPath();                 // rocky island under the tower
    g.moveTo(L.cx - L.tw * 0.9, hy + 40); g.quadraticCurveTo(L.cx - L.tw * 0.5, hy - 24, L.cx - L.tw * 0.36, L.base);
    g.lineTo(L.cx + L.tw * 0.36, L.base); g.quadraticCurveTo(L.cx + L.tw * 0.55, hy - 18, L.cx + L.tw * 0.95, hy + 44); g.closePath(); g.fill();
    g.fillStyle = 'rgba(255,255,255,.12)'; for (let i = 0; i < 9; i++) g.fillRect(L.cx - L.tw * 0.8 + i * L.tw * 0.2 + Math.sin(T + i) * 5, hy + 30 + (i % 3) * 5, 36, 2);
  }

  function huts() {                                         // deployed apps live on the shore, text only
    state.deployments.slice(0, 6).forEach((d, i) => {
      const side = i % 2 ? 1 : -1, x = L.cx + side * (L.tw * 0.62 + 70 + Math.floor(i / 2) * 120), y = L.base + 26;
      g.fillStyle = '#1a1830'; g.fillRect(x - 28, y - 22, 56, 26); g.beginPath(); g.moveTo(x - 34, y - 22); g.lineTo(x, y - 44); g.lineTo(x + 34, y - 22); g.closePath(); g.fill();
      const w = 0.7 + 0.3 * Math.sin(T * 2 + i); g.fillStyle = `rgba(255,210,110,${w})`; g.fillRect(x - 8, y - 14, 16, 12);
      g.textAlign = 'center'; g.fillStyle = '#ffe3a1'; g.font = '600 11px ui-monospace,Menlo,monospace';
      g.fillText(d.name.slice(0, 18), x, y + 18); g.fillStyle = '#9fb4d6'; g.fillText('127.0.0.1:' + d.port, x, y + 32);
    });
  }

  function beam() {
    const run = state.jobs.some((j) => j.status === 'running'), ang = T * (run ? 0.9 : 0.25), x = L.cx, y = L.top - 18;
    const len = Math.max(W, H) * 1.2;
    [-1, 1].forEach((d) => {
      const a = ang * d, k = Math.cos(a);                    // foreshortened sweep so it reads as 3D
      g.save(); g.globalCompositeOperation = 'lighter';
      const gr = g.createLinearGradient(x, y, x + Math.sin(a) * len, y);
      gr.addColorStop(0, `rgba(255,236,150,${run ? 0.55 : 0.2})`); gr.addColorStop(1, 'rgba(255,236,150,0)');
      g.fillStyle = gr; g.beginPath(); g.moveTo(x, y); g.lineTo(x + Math.sin(a) * len, y - 70 * Math.abs(k) - 18); g.lineTo(x + Math.sin(a) * len, y + 70 * Math.abs(k) + 18); g.closePath(); g.fill(); g.restore();
    });
  }

  function shell() {
    const { cx, top, base, fh } = L;
    g.save(); g.beginPath(); g.moveTo(L.wallL(top), top); g.lineTo(L.wallR(top), top); g.lineTo(L.wallR(base), base); g.lineTo(L.wallL(base), base); g.closePath();
    const st = g.createLinearGradient(L.wallL(base), 0, L.wallR(base), 0); st.addColorStop(0, '#1d2036'); st.addColorStop(0.5, '#2a2e4c'); st.addColorStop(1, '#171a2e');
    g.fillStyle = st; g.fill(); g.clip();
    ORDER.forEach((f) => room(f));
    g.restore();
    g.strokeStyle = '#4b5280'; g.lineWidth = 3; g.beginPath(); g.moveTo(L.wallL(top), top); g.lineTo(L.wallL(base), base); g.moveTo(L.wallR(top), top); g.lineTo(L.wallR(base), base); g.stroke();
    const rg = g.createLinearGradient(0, top - 70, 0, top); rg.addColorStop(0, '#3a2a63'); rg.addColorStop(1, '#241a42');   // lantern room + roof
    g.fillStyle = rg; g.beginPath(); g.moveTo(L.wallL(top) - 10, top); g.lineTo(cx, top - 70); g.lineTo(L.wallR(top) + 10, top); g.closePath(); g.fill();
    const run = state.jobs.some((j) => j.status === 'running'), pulse = run ? 0.7 + 0.3 * Math.sin(T * 6) : 0.35;
    const lg = g.createRadialGradient(cx, top - 20, 2, cx, top - 20, 80); lg.addColorStop(0, `rgba(255,240,170,${pulse})`); lg.addColorStop(1, 'rgba(255,240,170,0)');
    g.fillStyle = lg; g.fillRect(cx - 90, top - 110, 180, 180); g.fillStyle = '#fff3b8'; g.beginPath(); g.arc(cx, top - 20, 8, 0, 6.3); g.fill();
    g.strokeStyle = '#6a6fa6'; g.lineWidth = 2; g.beginPath(); g.moveTo(cx, top - 70); g.lineTo(cx, top - 96); g.stroke();
    g.fillStyle = state.chain_ok === false ? '#f87171' : '#4ade80'; g.beginPath(); g.moveTo(cx, top - 96); g.lineTo(cx + 24, top - 90); g.lineTo(cx, top - 82); g.fill();  // flag: audit chain
    ORDER.forEach((f) => { const r = L.rooms[f], on = lit.has(f); g.textAlign = 'right'; g.font = '700 12px system-ui,sans-serif'; g.fillStyle = hsl(HUE[f], 75, on ? 78 : 58, on ? 1 : 0.85); g.fillText(NAMES[f], L.wallL(r.y + r.h / 2) - 14, r.y + r.h / 2 + 4); });
    elevator();
  }

  function room(f) {
    const r = L.rooms[f], on = lit.has(f), h = HUE[f], x0 = L.wallL(r.y + r.h / 2) + 14, x1 = L.wallR(r.y + r.h / 2) - 14;
    const gr = g.createLinearGradient(0, r.y, 0, r.y + r.h);
    gr.addColorStop(0, hsl(h, 40, on ? 24 : 12)); gr.addColorStop(1, hsl(h, 45, on ? 15 : 8)); g.fillStyle = gr; g.fillRect(L.wallL(r.y) - 4, r.y + 2, L.wallR(r.y) - L.wallL(r.y) + 8, r.h - 2);
    if (on) { const pg = g.createRadialGradient(L.cx, r.y + r.h * 0.6, 4, L.cx, r.y + r.h * 0.6, L.tw * 0.5); pg.addColorStop(0, hsl(h, 90, 60, 0.22 + 0.06 * Math.sin(T * 3))); pg.addColorStop(1, hsl(h, 90, 60, 0)); g.fillStyle = pg; g.fillRect(x0 - 20, r.y, x1 - x0 + 40, r.h); }
    g.fillStyle = '#0a0c18'; g.fillRect(L.wallL(r.y + r.h) - 4, r.y + r.h - 4, L.wallR(r.y + r.h) - L.wallL(r.y + r.h) + 8, 4);   // floor slab
    g.fillStyle = 'rgba(160,200,255,.07)'; g.fillRect(L.wallL(r.y) - 4, r.y, L.wallR(r.y) - L.wallL(r.y) + 8, 3);                 // glass filter line
        byFloor[f].forEach((s) => person(s, r, x0, x1, on));
  }

  function person(s, r, x0, x1, on) {
    const working = awake.has(s.id), span = x1 - x0 - 84, px = x0 + 22 + s.x * span, py = r.y + r.h - 8, sc = r.h / 90, h = HUE[s.floor];
    s.px = px; s.py = py - 34 * sc;
    const step = REDUCED ? 0 : Math.sin(T * 9 + s.seed) * 4 * sc, moving = !working && Math.abs(s.tx - s.x) > 0.004;
    if (working) {                                          // desk + glowing monitor
      g.fillStyle = '#2b2236'; g.fillRect(px - 22 * sc, py - 14 * sc, 44 * sc, 4 * sc); g.fillRect(px - 20 * sc, py - 10 * sc, 3 * sc, 10 * sc); g.fillRect(px + 17 * sc, py - 10 * sc, 3 * sc, 10 * sc);
      const mg = g.createRadialGradient(px + 12 * sc, py - 28 * sc, 2, px + 12 * sc, py - 28 * sc, 40 * sc); mg.addColorStop(0, hsl(h, 100, 70, 0.45)); mg.addColorStop(1, hsl(h, 100, 70, 0));
      g.fillStyle = mg; g.fillRect(px - 30 * sc, py - 70 * sc, 90 * sc, 70 * sc);
      g.fillStyle = hsl(h, 90, 62); g.fillRect(px + 5 * sc, py - 36 * sc, 17 * sc, 11 * sc); g.fillStyle = hsl(h, 100, 88); for (let k = 0; k < 3; k++) g.fillRect(px + 7 * sc, py - 34 * sc + k * 3 * sc, (6 + ((T * 7 + k * 3) % 8)) * sc, 1.4 * sc);
    }
    g.fillStyle = hsl(h, 55, 52);   // body
    g.fillRect(px - 5 * sc, py - 30 * sc, 10 * sc, 16 * sc);
    g.fillStyle = '#20233f'; if (working) { g.fillRect(px - 5 * sc, py - 14 * sc, 14 * sc, 4 * sc); g.fillRect(px + 5 * sc, py - 12 * sc, 4 * sc, 12 * sc); }
    else { g.fillRect(px - 5 * sc, py - 14 * sc, 4 * sc, 14 * sc + (moving ? step : 0)); g.fillRect(px + 1 * sc, py - 14 * sc, 4 * sc, 14 * sc - (moving ? step : 0)); }
    g.fillStyle = hsl(h, 55, 45); const arm = working && !REDUCED ? Math.sin(T * 18 + s.seed) * 2 * sc : 0;
    g.fillRect(px + 4 * sc, py - 28 * sc, working ? 11 * sc : 3 * sc, 3 * sc + arm * 0); if (working) g.fillRect(px + 12 * sc, py - 26 * sc + arm, 3 * sc, 3 * sc);
    g.fillStyle = '#f1d3b6'; g.beginPath(); g.arc(px, py - 36 * sc , 6 * sc, 0, 6.3); g.fill();
    g.fillStyle = hsl((h + 140) % 360, 40, 25); g.beginPath(); g.arc(px, py - 38 * sc, 6.2 * sc, 3.14, 6.28); g.fill();
    if (s.id.endsWith('.lead') || s.floor === 'csuite') { g.fillStyle = '#ffd86b'; g.fillRect(px - 3 * sc, py - 45 * sc, 6 * sc, 2 * sc); }
    if (!working && !moving && !REDUCED) { g.fillStyle = 'rgba(190,210,255,.65)'; g.font = `600 ${Math.round(9 * sc + 2)}px system-ui`; g.textAlign = 'center'; g.fillText('z', px + 10 * sc, py - 44 * sc - ((T * 8 + s.i * 5) % 8)); }
    if (working) bubble(s, px, py - 54 * sc, h);
  }

  function bubble(s, x, y, h) {
    const dots = '.'.repeat(1 + (Math.floor(T * 2.5 + s.i) % 3)), txt = s.title.replace(/\(.*\)/, '').trim().slice(0, 26) + dots;
    g.font = '600 10px system-ui,sans-serif'; const w = g.measureText(txt).width + 12;
    g.fillStyle = 'rgba(8,10,24,.88)'; g.strokeStyle = hsl(h, 90, 65, 0.9); g.lineWidth = 1;
    g.beginPath(); g.roundRect(x - w / 2, y - 16, w, 16, 6); g.fill(); g.stroke();
    g.beginPath(); g.moveTo(x - 3, y); g.lineTo(x, y + 5); g.lineTo(x + 3, y); g.fillStyle = hsl(h, 90, 65, 0.9); g.fill();
    g.fillStyle = '#eaf2ff'; g.textAlign = 'center'; g.fillText(txt, x, y - 5);
  }

  function elevator() {
    const ex = (y) => L.wallR(y) - 12, y0 = L.top + 4, y1 = L.base - 4;
    g.fillStyle = 'rgba(6,8,18,.85)'; g.beginPath(); g.moveTo(ex(y0) - 5, y0); g.lineTo(ex(y0) + 5, y0); g.lineTo(ex(y1) + 5, y1); g.lineTo(ex(y1) - 5, y1); g.closePath(); g.fill();
    g.strokeStyle = 'rgba(160,190,255,.25)'; g.lineWidth = 1; g.beginPath(); g.moveTo(ex(y0), y0); g.lineTo(ex(y1), y1); g.stroke();
    for (let i = packets.length - 1; i >= 0; i--) {
      const p = packets[i]; p.t += REDUCED ? 1 : 0.012;
      const a = L.rooms[p.from].y + L.fh * 0.5, b = L.rooms[p.to].y + L.fh * 0.5, e = p.t < 0.5 ? 2 * p.t * p.t : 1 - Math.pow(-2 * p.t + 2, 2) / 2, y = a + (b - a) * Math.min(1, e), x = ex(y);
      const gl = g.createRadialGradient(x, y, 1, x, y, 26); gl.addColorStop(0, 'rgba(255,240,170,.9)'); gl.addColorStop(1, 'rgba(255,240,170,0)'); g.fillStyle = gl; g.fillRect(x - 26, y - 26, 52, 52);
      g.fillStyle = '#fffbe0'; g.fillRect(x - 5, y - 4, 10, 8); g.fillStyle = '#7a6a2a'; g.fillRect(x - 3, y - 2, 6, 1);
      if (p.t >= 1.15) packets.splice(i, 1);
    }
  }

  function basement() {                                     // ground engine: the model sockets turn when anyone is working
    const y = L.base, cx = L.cx, on = awake.size > 0;
    g.fillStyle = '#0c0e1c'; g.fillRect(L.wallL(y) - 6, y, L.wallR(y) - L.wallL(y) + 12, 34);
    [[-60, 11], [-18, 15], [30, 11]].forEach(([dx, r], k) => {
      g.save(); g.translate(L.wallR(y) - 34 - k * 36, y + 17); g.rotate((on ? T * (k % 2 ? -1.6 : 1.3) : 0) + k);
      g.fillStyle = on ? '#e9b44c' : '#5b5f7a'; for (let t = 0; t < 8; t++) { g.rotate(0.785); g.fillRect(-2, -r - 4, 4, 6); }
      g.beginPath(); g.arc(0, 0, r, 0, 6.3); g.fill(); g.fillStyle = '#0c0e1c'; g.beginPath(); g.arc(0, 0, r * 0.4, 0, 6.3); g.fill(); g.restore();
    });
    g.textAlign = 'left'; g.font = '700 10px system-ui'; g.fillStyle = on ? '#ffd68a' : '#6c708c'; g.fillText('GROUND ENGINE  ' + (on ? awake.size + ' agent' + (awake.size > 1 ? 's' : '') + ' working' : 'idle'), L.wallL(y) + 6, y + 12);
  }

  function hud() {
    g.textAlign = 'left'; g.font = '800 18px system-ui,sans-serif'; g.fillStyle = '#e8eefc'; g.fillText('THE WATCHTOWER', 22, 34);
    const run = state.jobs.filter((j) => j.status === 'running').length, wait = state.jobs.filter((j) => j.status === 'paused').length;
    g.font = '500 12px system-ui'; g.fillStyle = '#93a6c6'; g.fillText(`${run} running  |  ${wait} waiting for you  |  ${awake.size} agents awake  |  ${state.chain_ok === false ? 'AUDIT CHAIN BROKEN' : 'audit chain ok'}`, 22, 54);
    state.jobs.filter((j) => j.status === 'running' || j.status === 'paused').slice(0, 5).forEach((j, i) => {
      const y = 86 + i * 44; g.fillStyle = 'rgba(10,14,34,.7)'; g.strokeStyle = 'rgba(140,170,255,.3)'; g.beginPath(); g.roundRect(22, y, 270, 36, 8); g.fill(); g.stroke();
      g.fillStyle = j.status === 'running' ? '#fde68a' : '#fbbf24'; g.font = '700 11px ui-monospace,Menlo,monospace'; g.fillText(j.id.slice(0, 12) + '  ' + j.status + '  ' + (j.floor ? j.floor.toUpperCase() : 'planning'), 32, y + 15);
      g.fillStyle = '#b7c5e0'; g.font = '500 11px system-ui'; g.fillText(j.prompt.slice(0, 40), 32, y + 29);
    });
    const hit = staff.find((s) => s.px && Math.abs(mouse.x - s.px) < 14 && Math.abs(mouse.y - s.py) < 28);
    if (hit) { const t = `${hit.title}  (${hit.id})  ${awake.has(hit.id) ? 'working' : 'idle'}`; g.font = '600 12px system-ui'; const w = g.measureText(t).width + 16;
      g.fillStyle = 'rgba(8,10,24,.95)'; g.strokeStyle = '#8ba7ff'; g.beginPath(); g.roundRect(mouse.x + 14, mouse.y - 12, w, 24, 6); g.fill(); g.stroke(); g.fillStyle = '#fff'; g.textAlign = 'left'; g.fillText(t, mouse.x + 22, mouse.y + 4); }
  }

  function wander(dt) {
    staff.forEach((s) => {
      if (awake.has(s.id)) { s.tx = s.home; } else { s.wait -= dt; if (s.wait <= 0) { s.tx = Math.min(1, Math.max(0, s.home + (rnd(s.seed + T) - 0.5) * 0.5)); s.wait = 2 + rnd(s.seed + T * 3) * 6; } }
      const d = s.tx - s.x; s.x += Math.sign(d) * Math.min(Math.abs(d), dt * (REDUCED ? 0 : 0.07));
    });
  }

  function frame(ts) {
    const dt = Math.min(0.1, (ts - last) / 1000 || 0.016); last = ts; T += dt; wander(dt);
    sky(); land(); beam(); huts(); shell(); basement(); hud();
    requestAnimationFrame(frame);
  }
  addEventListener('resize', layout); cv.addEventListener('mousemove', (e) => { mouse = { x: e.clientX, y: e.clientY }; }); cv.addEventListener('mouseleave', () => { mouse = { x: -1, y: -1 }; });
  layout(); requestAnimationFrame(frame);
  return { update };
})();
"""
