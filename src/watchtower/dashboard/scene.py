"""9c: the watchtower scene. One canvas, vanilla JS, no assets: a stone lighthouse on a sea rock under a textured sky that
follows the real time of day. Each floor of the tower opens into a cutaway room beside it where that floor's staff work;
job packets ride the lift between floors; deployed apps are boats on the water. Text goes on the canvas with fillText
only; nothing here builds HTML. Read-only: it just draws the state the page already polls."""

SCENE_JS = r"""
SCENE = (() => {
  const cv = document.getElementById('scene'), g = cv.getContext('2d');
  const REDUCED = matchMedia('(prefers-reduced-motion: reduce)').matches;
  const ORDER = ['csuite', 'f5', 'f4', 'f3', 'f2', 'f1'];
  const NAMES = { csuite: 'PENTHOUSE  C-suite', f5: 'F5  Oversight', f4: 'F4  QA & Deploy', f3: 'F3  Build', f2: 'F2  Dev', f1: 'F1  Research' };
  const HUE = { csuite: 44, f5: 285, f4: 160, f3: 24, f2: 205, f1: 120 };
  let W = 0, H = 0, dpr = 1, DT = 0.016, relayout = false, failed = false, T = 0, last = 0, drawn = 0, mouse = { x: -1, y: -1 }, mode = 'auto', btn = null, L = {}, cloudTex = null;
  let state = { jobs: [], deployments: [], chain_ok: true };
  const awake = new Set(), lit = new Set(), prevFloor = new Map(), packets = [], gulls = [];
  const staff = ROSTER.filter((r) => ORDER.includes(r.floor)).map((r, i) => ({ ...r, i, x: 0, tx: 0, home: 0.5, wait: 1 + (i % 7), seed: i * 2.39 }));
  const byFloor = Object.fromEntries(ORDER.map((f) => [f, staff.filter((s) => s.floor === f)]));
  const rnd = (a) => { const v = Math.sin(a * 127.1 + 311.7) * 43758.5453; return v - Math.floor(v); };
  const hsl = (h, s, l, a = 1) => `hsla(${h},${s}%,${l}%,${a})`;
  const mix = (a, b, t) => a.map((v, i) => Math.round(v + (b[i] - v) * t));
  const rgb = (c, a = 1) => `rgba(${c[0]},${c[1]},${c[2]},${a})`;
  const rr = (x, y, w, h, r) => { g.beginPath(); if (g.roundRect) g.roundRect(x, y, w, h, r); else g.rect(x, y, w, h); };   // old browsers: square corners
  const SKY = { day: [8, 72, 168, 44, 128, 214, 168, 214, 244], dusk: [38, 36, 96, 190, 92, 110, 250, 176, 120], night: [3, 5, 22, 14, 16, 52, 30, 28, 74] };
  const SEA = { day: [22, 120, 150, 8, 54, 92], dusk: [70, 70, 110, 16, 26, 60], night: [12, 34, 66, 3, 10, 24] };

  function hours() { const d = new Date(); return d.getHours() + d.getMinutes() / 60; }
  function light() {   // 0 = deep night .. 1 = full day, from the clock unless the button forced a mode
    if (mode === 'day') return 1; if (mode === 'night') return 0;
    return Math.max(0, Math.min(1, (Math.sin(Math.PI * (hours() - 6) / 12) + 0.25) / 0.6));
  }
  function pal(tbl, k) { const a = k > 0.5 ? mix(tbl.dusk, tbl.day, (k - 0.5) * 2) : mix(tbl.night, tbl.dusk, k * 2); return [a.slice(0, 3), a.slice(3, 6), a.slice(6, 9)]; }

  function makeClouds() {   // a high mackerel sky: many soft puffs in wavy bands, drawn once, scrolled each frame
    cloudTex = document.createElement('canvas'); cloudTex.width = Math.ceil(W * 1.6); cloudTex.height = Math.ceil(H * 0.72);
    const c = cloudTex.getContext('2d');
    for (let i = 0; i < 2600; i++) {
      const x = rnd(i * 3.1) * cloudTex.width, v = rnd(i * 7.7), y = v * cloudTex.height * (0.15 + 0.85 * v);
      const band = 0.5 + 0.5 * Math.sin(x * 0.006 + y * 0.03 + Math.sin(y * 0.02) * 2.2), dense = band * (1 - 0.55 * (y / cloudTex.height));
      if (rnd(i * 5.3) > dense) continue;
      const r = 6 + rnd(i * 9.1) * 22 * (0.4 + y / cloudTex.height), gr = c.createRadialGradient(x, y, 0, x, y, r);
      gr.addColorStop(0, 'rgba(255,255,255,.22)'); gr.addColorStop(1, 'rgba(255,255,255,0)'); c.fillStyle = gr; c.beginPath(); c.ellipse(x, y, r * 1.8, r * 0.8, 0, 0, 6.3); c.fill();
    }
  }

  function layout() {
    dpr = Math.min(2, devicePixelRatio || 1); W = Math.max(1, innerWidth); H = Math.max(1, innerHeight);
    cv.width = W * dpr; cv.height = H * dpr; g.setTransform(dpr, 0, 0, dpr, 0, 0); makeClouds();
    const hy = H * 0.77, base = H * 0.835, Ht = H * 0.66, top = base - Ht, bw = Ht * 0.105, tw = bw * 0.6, plinth = base - Ht * 0.13, gal = top + Ht * 0.115;
    L = { hy, base, Ht, top, bw, tw, plinth, gal, cx: W * 0.5, bodyTop: gal + Ht * 0.03, fh: (plinth - gal - Ht * 0.03) / ORDER.length, rooms: {} };
    L.half = (y) => { const t = Math.min(1, Math.max(0, (y - gal) / (base - gal))); return tw + (bw - tw) * t + (y > plinth ? bw * 0.1 : 0); };
    L.cw = Math.max(110, Math.min(310, (W - 2 * (bw + 60)) / 2 - 24)); L.ch = Math.max(40, Math.min(112, L.fh * 2 - 26));
    ORDER.forEach((f, k) => { const wy = L.bodyTop + L.fh * (k + 0.5), left = k % 2 === 0, hw = L.half(wy);
      L.rooms[f] = { wy, left, x: left ? L.cx - hw - 46 - L.cw : L.cx + hw + 46, y: wy - L.ch / 2, w: L.cw, h: L.ch }; });
    staff.forEach((s) => { s.home = (byFloor[s.floor].indexOf(s) + 0.5) / byFloor[s.floor].length; s.x = s.tx = s.home; });
  }

  function update(s) {
    state = s; awake.clear(); lit.clear();
    s.jobs.forEach((j) => {
      if (j.status === 'running') (j.awake || []).forEach((a) => awake.add(a));
      if ((j.status === 'running' || j.status === 'paused') && j.floor) lit.add(j.floor);
      const was = prevFloor.get(j.id);
      if (j.floor && was && was !== j.floor && L.rooms[was] && L.rooms[j.floor]) packets.push({ from: was, to: j.floor, t: 0 });
      if (j.floor) prevFloor.set(j.id, j.floor);
    });
    if (prevFloor.size > 200) prevFloor.clear();
  }

  function sky(k) {
    const [a, b, c] = pal(SKY, k), gr = g.createLinearGradient(0, 0, 0, L.hy);
    gr.addColorStop(0, rgb(a)); gr.addColorStop(0.55, rgb(b)); gr.addColorStop(1, rgb(c)); g.fillStyle = gr; g.fillRect(0, 0, W, L.hy + 2);
    if (k < 0.55) for (let i = 0; i < 200; i++) { const al = (0.55 - k) / 0.55 * (0.35 + 0.65 * (0.5 + 0.5 * Math.sin(T * 1.3 + i))); g.fillStyle = `rgba(255,255,255,${al})`; g.beginPath(); g.arc(rnd(i) * W, rnd(i + 99) * L.hy * 0.8, 0.4 + rnd(i + 5) * 1.1, 0, 6.3); g.fill(); }
    const sun = k > 0.45, h = hours(), p = mode === 'auto' ? (sun ? (h - 6) / 12 : ((h + 6) % 12) / 12) : (sun ? 0.62 : 0.4);   // sun by day, moon by night, along an arc
    const sx = W * (0.1 + 0.8 * Math.min(1, Math.max(0, p))), sy = L.hy * (0.88 - 0.74 * Math.sin(Math.PI * Math.min(1, Math.max(0, p))));
    const og = g.createRadialGradient(sx, sy, 4, sx, sy, sun ? 220 : 130); og.addColorStop(0, sun ? 'rgba(255,244,200,.85)' : 'rgba(255,246,220,.3)'); og.addColorStop(1, 'rgba(255,240,200,0)'); g.fillStyle = og; g.fillRect(sx - 220, sy - 220, 440, 440);
    g.fillStyle = sun ? '#fffbe6' : '#fff6dc'; g.beginPath(); g.arc(sx, sy, sun ? 26 : 22, 0, 6.3); g.fill();
    const off = (T * 6) % cloudTex.width, off2 = (T * 11) % cloudTex.width, ch = cloudTex.height;   // textured cloud deck, two layers for parallax
    g.save(); g.globalAlpha = 0.2 + 0.8 * k; g.drawImage(cloudTex, -off, 0); g.drawImage(cloudTex, cloudTex.width - off, 0);
    g.globalAlpha = (0.2 + 0.8 * k) * 0.55; g.drawImage(cloudTex, -off2, ch * 0.1, cloudTex.width, ch * 0.9); g.drawImage(cloudTex, cloudTex.width - off2, ch * 0.1, cloudTex.width, ch * 0.9); g.restore();
    const haze = g.createLinearGradient(0, L.hy - 120, 0, L.hy); haze.addColorStop(0, 'rgba(255,255,255,0)'); haze.addColorStop(1, rgb(c, 0.75)); g.fillStyle = haze; g.fillRect(0, L.hy - 120, W, 120);
    if (k > 0.3 && k < 0.7) { g.fillStyle = `rgba(255,150,90,${0.18 * (1 - Math.abs(k - 0.5) * 5)})`; g.fillRect(0, 0, W, L.hy); }
    if (REDUCED) return;
    if (gulls.length < 5 && Math.random() < 0.005) gulls.push({ x: -20, y: L.hy * (0.3 + Math.random() * 0.4), v: 30 + Math.random() * 30, p: Math.random() * 6 });
    for (let i = gulls.length - 1; i >= 0; i--) { const q = gulls[i]; q.x += q.v * DT; const f = Math.sin(T * 9 + q.p) * 5; g.strokeStyle = k > 0.4 ? 'rgba(255,255,255,.9)' : 'rgba(180,190,220,.6)'; g.lineWidth = 1.6; g.beginPath(); g.moveTo(q.x - 9, q.y - f); g.quadraticCurveTo(q.x - 4, q.y - 4, q.x, q.y); g.quadraticCurveTo(q.x + 4, q.y - 4, q.x + 9, q.y - f); g.stroke(); if (q.x > W + 20) gulls.splice(i, 1); }
  }

  function sea(k) {
    const [top, bot] = pal(SEA, k), gr = g.createLinearGradient(0, L.hy, 0, H); gr.addColorStop(0, rgb(top)); gr.addColorStop(1, rgb(bot)); g.fillStyle = gr; g.fillRect(0, L.hy, W, H - L.hy);
    const sl = g.createLinearGradient(0, L.hy, 0, L.hy + 30); sl.addColorStop(0, 'rgba(255,255,255,.35)'); sl.addColorStop(1, 'rgba(255,255,255,0)'); g.fillStyle = sl; g.fillRect(0, L.hy, W, 30);
    for (let i = 0; i < 260; i++) {   // whitecaps and swell, denser and bigger toward the viewer
      const depth = Math.pow(rnd(i * 1.7), 1.6), y = L.hy + 6 + depth * (H - L.hy), w = 8 + depth * 90, x = ((rnd(i * 2.9) * (W + 200) + T * (6 + depth * 26) * (i % 2 ? 1 : -0.6)) % (W + 200) + (W + 200)) % (W + 200) - 100;
      g.fillStyle = `rgba(255,255,255,${(0.10 + depth * 0.35) * (0.3 + 0.7 * k)})`; g.fillRect(x, y, w, 1 + depth * 2.4);
    }
  }

  function island(k) {
    const { cx, base, bw } = L, w = bw * 6.4, y = base, dk = 0.45 + 0.55 * k;
    const foam = (r, a) => { g.fillStyle = `rgba(255,255,255,${a})`; g.beginPath(); g.ellipse(cx, y + 18, w * r, 9 + Math.sin(T * 1.4) * 2, 0, 0, 6.3); g.fill(); };
    foam(0.62, 0.22 * dk); foam(0.54, 0.35 * dk);
    g.beginPath(); g.moveTo(cx - w * 0.52, y + 22);
    for (let i = 0; i <= 14; i++) { const t = i / 14; g.lineTo(cx - w * 0.5 + t * w, y - (Math.sin(t * Math.PI) * bw * 0.52 + rnd(i * 4.3) * bw * 0.22) + 14); }
    g.lineTo(cx + w * 0.52, y + 22); g.closePath();
    const rg = g.createLinearGradient(0, y - bw, 0, y + 24); rg.addColorStop(0, rgb(mix([150, 118, 76], [60, 52, 60], 1 - dk))); rg.addColorStop(1, rgb(mix([84, 64, 44], [24, 22, 30], 1 - dk))); g.fillStyle = rg; g.fill();
    g.strokeStyle = `rgba(30,20,10,${0.35 * dk})`; g.lineWidth = 1; for (let i = 0; i < 10; i++) { const x = cx - w * 0.4 + rnd(i * 6.1) * w * 0.8; g.beginPath(); g.moveTo(x, y + 4 - rnd(i) * 10); g.lineTo(x + 10 + rnd(i + 3) * 16, y + 16); g.stroke(); }
    g.fillStyle = `rgba(255,255,255,${0.5 * dk})`; for (let i = 0; i < 9; i++) { g.beginPath(); g.ellipse(cx - w * 0.5 + (i / 8) * w, y + 21 + Math.sin(T * 1.6 + i) * 1.2, 14 + rnd(i) * 22, 3, 0, 0, 6.3); g.fill(); }
    const refl = g.createLinearGradient(0, y + 24, 0, y + 24 + L.Ht * 0.3); refl.addColorStop(0, `rgba(210,205,190,${0.22 * dk})`); refl.addColorStop(1, 'rgba(210,205,190,0)');
    g.fillStyle = refl; for (let i = 0; i < 18; i++) g.fillRect(cx - bw * 0.7 + Math.sin(T * 1.3 + i) * 4 + rnd(i) * 6, y + 24 + i * L.Ht * 0.3 / 18, bw * 1.4, 2);
  }

  function boats(k) {   // each deployed app is a boat on the water: text only, never a link
    state.deployments.slice(0, 6).forEach((d, i) => {
      const side = i % 2 ? 1 : -1, x = L.cx + side * (L.bw * 3.3 + 70 + Math.floor(i / 2) * 150), y = L.hy + (H - L.hy) * (0.28 + (i % 3) * 0.12) + Math.sin(T * 1.2 + i) * 2.5;
      g.save(); g.translate(x, y); g.rotate(Math.sin(T * 1.1 + i * 2) * 0.05);
      g.fillStyle = '#3a2a22'; g.beginPath(); g.moveTo(-26, -2); g.lineTo(26, -2); g.lineTo(18, 10); g.lineTo(-18, 10); g.closePath(); g.fill();
      g.fillStyle = '#e8e2d2'; g.beginPath(); g.moveTo(0, -4); g.lineTo(0, -34); g.lineTo(18, -6); g.closePath(); g.fill(); g.strokeStyle = '#2a2018'; g.lineWidth = 1.5; g.beginPath(); g.moveTo(0, -4); g.lineTo(0, -38); g.stroke();
      g.fillStyle = '#f87171'; g.fillRect(0, -38, 9, 5);
      const glow = g.createRadialGradient(-20, -4, 0, -20, -4, 22); glow.addColorStop(0, `rgba(255,210,110,${0.9 - 0.6 * k})`); glow.addColorStop(1, 'rgba(255,210,110,0)'); g.fillStyle = glow; g.fillRect(-44, -26, 44, 44);
      g.restore(); g.textAlign = 'center'; g.font = '600 11px ui-monospace,Menlo,monospace'; const addr = d.port ? '127.0.0.1:' + d.port : '-', pw = Math.max(g.measureText(addr).width, g.measureText(d.name.slice(0, 18)).width) + 14;
      g.fillStyle = 'rgba(6,16,36,.7)'; rr(x - pw / 2, y + 14, pw, 34, 7); g.fill(); g.fillStyle = '#ffe3a1'; g.fillText(d.name.slice(0, 18), x, y + 28); g.fillStyle = '#b9cdea'; g.fillText(addr, x, y + 42);
    });
  }

  const lantern = () => ({ x: L.cx, y: L.top + L.Ht * 0.045 });

  function beam(k) {
    const run = state.jobs.some((j) => j.status === 'running'), a = T * (run ? 0.9 : 0.3), { x, y } = lantern(), len = Math.max(W, H) * 1.3, s = (0.18 + 0.7 * (1 - k)) * (run ? 1 : 0.55);
    [0, Math.PI].forEach((o) => {
      const c = Math.cos(a + o), sn = Math.sin(a + o); if (c < -0.15) return;
      g.save(); g.globalCompositeOperation = 'lighter'; const gr = g.createLinearGradient(x, y, x + sn * len, y); gr.addColorStop(0, `rgba(255,238,160,${s * (0.4 + 0.6 * Math.max(0, c))})`); gr.addColorStop(1, 'rgba(255,238,160,0)');
      const spread = 8 + 60 * Math.max(0.1, Math.abs(c)); g.fillStyle = gr; g.beginPath(); g.moveTo(x, y); g.lineTo(x + sn * len, y - spread * 3); g.lineTo(x + sn * len, y + spread * 3); g.closePath(); g.fill(); g.restore();
    });
  }

  function tower(k) {
    const { cx, top, base, plinth, gal, bodyTop, fh, bw, tw, half } = L, dk = 0.5 + 0.5 * k;
    const stone = g.createLinearGradient(cx - bw, 0, cx + bw, 0);
    stone.addColorStop(0, rgb(mix([120, 114, 104], [30, 32, 52], 1 - dk))); stone.addColorStop(0.38, rgb(mix([236, 229, 212], [70, 74, 110], 1 - dk))); stone.addColorStop(0.72, rgb(mix([210, 202, 184], [56, 60, 94], 1 - dk))); stone.addColorStop(1, rgb(mix([120, 114, 104], [24, 26, 44], 1 - dk)));
    g.beginPath(); g.moveTo(cx - half(gal), gal); g.lineTo(cx + half(gal), gal); g.lineTo(cx + half(plinth), plinth); g.lineTo(cx - half(plinth), plinth); g.closePath(); g.fillStyle = stone; g.fill();
    g.strokeStyle = `rgba(70,58,44,${0.16 * dk})`; g.lineWidth = 1; for (let y = gal + 5; y < plinth; y += 7) { g.beginPath(); g.moveTo(cx - half(y), y); g.lineTo(cx + half(y), y); g.stroke(); }
    g.strokeStyle = `rgba(60,52,44,${0.35 * dk})`; g.lineWidth = 2; ORDER.forEach((f, i) => { const y = bodyTop + fh * i; g.beginPath(); g.moveTo(cx - half(y), y); g.lineTo(cx + half(y), y); g.stroke(); });
    const pl = g.createLinearGradient(cx - bw, 0, cx + bw, 0); pl.addColorStop(0, '#2c2b2c'); pl.addColorStop(0.45, '#5a5755'); pl.addColorStop(1, '#232224');   // dark granite base
    g.beginPath(); g.moveTo(cx - half(plinth), plinth); g.lineTo(cx + half(plinth), plinth); g.lineTo(cx + half(base), base); g.lineTo(cx - half(base), base); g.closePath(); g.fillStyle = pl; g.fill();
    g.strokeStyle = 'rgba(0,0,0,.35)'; for (let y = plinth + 6; y < base; y += 8) { g.beginPath(); g.moveTo(cx - half(y), y); g.lineTo(cx + half(y), y); g.stroke(); }
    ORDER.forEach((f) => {
      const r = L.rooms[f], wy = r.wy, wx = cx + half(wy) * 0.1, on = lit.has(f);
      if (on) { const hg = g.createRadialGradient(wx, wy, 1, wx, wy, 30); hg.addColorStop(0, hsl(HUE[f], 100, 70, 0.8)); hg.addColorStop(1, hsl(HUE[f], 100, 70, 0)); g.fillStyle = hg; g.fillRect(wx - 30, wy - 30, 60, 60); }
      g.fillStyle = on ? hsl(HUE[f], 100, 78) : '#1b2030'; g.beginPath(); g.moveTo(wx - 4, wy + 8); g.lineTo(wx - 4, wy - 4); g.quadraticCurveTo(wx, wy - 11, wx + 4, wy - 4); g.lineTo(wx + 4, wy + 8); g.closePath(); g.fill();
      g.strokeStyle = on ? hsl(HUE[f], 90, 70, 0.8) : 'rgba(255,255,255,.2)'; g.lineWidth = on ? 1.6 : 1; g.setLineDash([4, 5]); g.beginPath(); g.moveTo(wx, wy); g.lineTo(r.left ? r.x + r.w : r.x, wy); g.stroke(); g.setLineDash([]);
    });
    const gw = tw * 1.55; g.fillStyle = '#34323a'; g.fillRect(cx - gw, gal - 4, gw * 2, 7); g.fillStyle = '#26242c'; g.beginPath(); g.moveTo(cx - tw * 1.1, gal + 3); g.lineTo(cx + tw * 1.1, gal + 3); g.lineTo(cx + tw, gal + 14); g.lineTo(cx - tw, gal + 14); g.closePath(); g.fill();   // gallery + corbels
    g.strokeStyle = '#2b2a31'; g.lineWidth = 1.4; for (let i = 0; i <= 12; i++) { const x = cx - gw + (i / 12) * gw * 2; g.beginPath(); g.moveTo(x, gal - 4); g.lineTo(x, gal - 14); g.stroke(); } g.beginPath(); g.moveTo(cx - gw, gal - 14); g.lineTo(cx + gw, gal - 14); g.stroke();
    const ly = top + L.Ht * 0.03, lh = gal - 4 - ly, lw = tw * 1.05, on = state.jobs.some((j) => j.status === 'running'), pulse = on ? 0.75 + 0.25 * Math.sin(T * 6) : 0.45;   // lantern room
    g.fillStyle = `rgba(255,236,150,${0.55 + 0.4 * pulse * (1 - k * 0.5)})`; g.fillRect(cx - lw, ly, lw * 2, lh);
    g.strokeStyle = '#2d2b33'; g.lineWidth = 1.5; for (let i = -3; i <= 3; i++) { g.beginPath(); g.moveTo(cx + i * lw / 3, ly); g.lineTo(cx + i * lw / 3 + lh * 0.5, gal - 4); g.moveTo(cx + i * lw / 3, ly); g.lineTo(cx + i * lw / 3 - lh * 0.5, gal - 4); g.stroke(); }
    g.fillStyle = '#2d2b33'; g.fillRect(cx - lw - 2, ly - 3, lw * 2 + 4, 4); g.beginPath(); g.moveTo(cx - lw - 3, ly - 3); g.quadraticCurveTo(cx, top - L.Ht * 0.03, cx + lw + 3, ly - 3); g.fill();
    g.strokeStyle = '#3a3840'; g.lineWidth = 1.3; for (let i = -4; i <= 4; i++) { g.beginPath(); g.moveTo(cx + i * 3, top - L.Ht * 0.015); g.lineTo(cx + i * 12, top - L.Ht * 0.055 - Math.abs(i) * 1.5); g.stroke(); }   // sunburst vane
    g.fillStyle = state.chain_ok === false ? '#f87171' : '#4ade80'; g.beginPath(); g.moveTo(cx, top - L.Ht * 0.055); g.lineTo(cx + 22, top - L.Ht * 0.045); g.lineTo(cx, top - L.Ht * 0.032); g.fill();   // flag: audit chain
    const { x, y } = lantern(), lg = g.createRadialGradient(x, y, 2, x, y, 90); lg.addColorStop(0, `rgba(255,244,190,${0.6 * pulse})`); lg.addColorStop(1, 'rgba(255,244,190,0)'); g.save(); g.globalCompositeOperation = 'lighter'; g.fillStyle = lg; g.fillRect(x - 90, y - 90, 180, 180); g.restore();
    lift();
  }

  function lift() {   // job packets climb the tower's axis between floor windows
    for (let i = packets.length - 1; i >= 0; i--) {
      const p = packets[i]; p.t += REDUCED ? 1 : 0.012; const tt = Math.min(1, p.t);
      const a = L.rooms[p.from].wy, b = L.rooms[p.to].wy, e = tt < 0.5 ? 2 * tt * tt : 1 - Math.pow(-2 * tt + 2, 2) / 2, y = a + (b - a) * e, x = L.cx - L.half(y) * 0.12;
      const gl = g.createRadialGradient(x, y, 1, x, y, 26); gl.addColorStop(0, 'rgba(255,240,170,.95)'); gl.addColorStop(1, 'rgba(255,240,170,0)'); g.fillStyle = gl; g.fillRect(x - 26, y - 26, 52, 52);
      g.fillStyle = '#fffbe0'; g.fillRect(x - 5, y - 4, 10, 8); g.fillStyle = '#7a6a2a'; g.fillRect(x - 3, y - 2, 6, 1);
      if (p.t >= 1.15) packets.splice(i, 1);
    }
  }

  function room(f, k) {
    const r = L.rooms[f], on = lit.has(f), h = HUE[f];
    g.save(); g.globalAlpha = on ? 1 : 0.82;
    g.shadowColor = on ? hsl(h, 90, 60, 0.6) : 'rgba(0,0,0,.4)'; g.shadowBlur = on ? 22 : 10; rr(r.x, r.y, r.w, r.h, 9); g.fillStyle = hsl(h, 30, 14); g.fill(); g.shadowBlur = 0;
    rr(r.x, r.y, r.w, r.h, 9); g.clip();
    const gr = g.createLinearGradient(0, r.y, 0, r.y + r.h); gr.addColorStop(0, hsl(h, 38, on ? 26 : 16)); gr.addColorStop(1, hsl(h, 42, on ? 16 : 10)); g.fillStyle = gr; g.fillRect(r.x, r.y, r.w, r.h);
    g.fillStyle = hsl(h, 50, 50, 0.1); g.fillRect(r.x + r.w * 0.55, r.y + 8, r.w * 0.34, r.h * 0.38);   // a window onto the sea inside the room
    if (on) { const pg = g.createRadialGradient(r.x + r.w / 2, r.y + r.h * 0.7, 4, r.x + r.w / 2, r.y + r.h * 0.7, r.w * 0.6); pg.addColorStop(0, hsl(h, 90, 62, 0.25 + 0.06 * Math.sin(T * 3))); pg.addColorStop(1, hsl(h, 90, 62, 0)); g.fillStyle = pg; g.fillRect(r.x, r.y, r.w, r.h); }
    g.fillStyle = 'rgba(0,0,0,.45)'; g.fillRect(r.x, r.y + r.h - 5, r.w, 5);
    byFloor[f].forEach((s) => person(s, r)); g.restore();
    rr(r.x, r.y, r.w, r.h, 9); g.strokeStyle = on ? hsl(h, 90, 68, 0.95) : 'rgba(255,255,255,.25)'; g.lineWidth = on ? 2 : 1; g.stroke();
    g.font = '700 11px system-ui,sans-serif'; const tw = g.measureText(NAMES[f]).width + 14, tx = r.left ? r.x : r.x + r.w - tw;
    rr(tx, r.y - 17, tw, 17, 6); g.fillStyle = hsl(h, 55, on ? 30 : 18, 0.95); g.fill(); g.textAlign = 'left'; g.fillStyle = hsl(h, 80, on ? 88 : 72); g.fillText(NAMES[f], tx + 7, r.y - 5);
  }

  function person(s, r) {
    const working = awake.has(s.id), sc = Math.max(0.3, r.h / 100), px = r.x + 22 + s.x * (r.w - 58), py = r.y + r.h - 6, h = HUE[s.floor];
    s.px = px; s.py = py - 30 * sc;
    const step = REDUCED ? 0 : Math.sin(T * 9 + s.seed) * 4 * sc, moving = !working && Math.abs(s.tx - s.x) > 0.004;
    if (working) {
      g.fillStyle = '#2b2236'; g.fillRect(px - 22 * sc, py - 14 * sc, 44 * sc, 4 * sc); g.fillRect(px - 20 * sc, py - 10 * sc, 3 * sc, 10 * sc); g.fillRect(px + 17 * sc, py - 10 * sc, 3 * sc, 10 * sc);
      const mg = g.createRadialGradient(px + 12 * sc, py - 28 * sc, 2, px + 12 * sc, py - 28 * sc, 40 * sc); mg.addColorStop(0, hsl(h, 100, 70, 0.5)); mg.addColorStop(1, hsl(h, 100, 70, 0)); g.fillStyle = mg; g.fillRect(px - 30 * sc, py - 70 * sc, 90 * sc, 70 * sc);
      g.fillStyle = hsl(h, 90, 62); g.fillRect(px + 5 * sc, py - 36 * sc, 17 * sc, 11 * sc); g.fillStyle = hsl(h, 100, 88); for (let q = 0; q < 3; q++) g.fillRect(px + 7 * sc, py - 34 * sc + q * 3 * sc, (6 + ((T * 7 + q * 3) % 8)) * sc, 1.4 * sc);
    }
    g.fillStyle = hsl(h, 55, 52); g.fillRect(px - 5 * sc, py - 30 * sc, 10 * sc, 16 * sc);
    g.fillStyle = '#20233f'; if (working) { g.fillRect(px - 5 * sc, py - 14 * sc, 14 * sc, 4 * sc); g.fillRect(px + 5 * sc, py - 12 * sc, 4 * sc, 12 * sc); } else { g.fillRect(px - 5 * sc, py - 14 * sc, 4 * sc, 14 * sc + (moving ? step : 0)); g.fillRect(px + sc, py - 14 * sc, 4 * sc, 14 * sc - (moving ? step : 0)); }
    g.fillStyle = hsl(h, 55, 45); g.fillRect(px + 4 * sc, py - 28 * sc, working ? 11 * sc : 3 * sc, 3 * sc); if (working) g.fillRect(px + 12 * sc, py - 26 * sc + (REDUCED ? 0 : Math.sin(T * 18 + s.seed) * 2 * sc), 3 * sc, 3 * sc);
    g.fillStyle = '#f1d3b6'; g.beginPath(); g.arc(px, py - 36 * sc, 6 * sc, 0, 6.3); g.fill(); g.fillStyle = hsl((h + 140) % 360, 40, 25); g.beginPath(); g.arc(px, py - 38 * sc, 6.2 * sc, 3.14, 6.28); g.fill();
    if (s.id.endsWith('.lead') || s.floor === 'csuite') { g.fillStyle = '#ffd86b'; g.fillRect(px - 3 * sc, py - 45 * sc, 6 * sc, 2 * sc); }
    if (!working && !moving && !REDUCED) { g.fillStyle = 'rgba(190,210,255,.7)'; g.font = `600 ${Math.round(9 * sc + 2)}px system-ui`; g.textAlign = 'center'; g.fillText('z', px + 10 * sc, py - 44 * sc - ((T * 8 + s.i * 5) % 8)); }
    if (working) bubble(s, px, Math.max(r.y + 20, py - 54 * sc), h, r);
  }

  function bubble(s, x, y, h, r) {
    const dots = '.'.repeat(1 + (Math.floor(T * 2.5 + s.i) % 3)), txt = s.title.replace(/\(.*\)/, '').trim().slice(0, 24) + dots;
    g.font = '600 10px system-ui,sans-serif'; const w = g.measureText(txt).width + 12, bx = Math.min(r.x + r.w - w - 2, Math.max(r.x + 2, x - w / 2));
    g.fillStyle = 'rgba(8,10,24,.9)'; g.strokeStyle = hsl(h, 90, 65, 0.9); g.lineWidth = 1; rr(bx, y - 16, w, 16, 6); g.fill(); g.stroke();
    g.fillStyle = '#eaf2ff'; g.textAlign = 'left'; g.fillText(txt, bx + 6, y - 5);
  }

  function basement() {
    const on = awake.size > 0, y = L.base + 2;
    g.textAlign = 'center'; g.font = '700 10px system-ui'; g.fillStyle = on ? '#ffd68a' : '#9aa3b8'; g.fillText('GROUND ENGINE  ' + (on ? awake.size + ' agent' + (awake.size > 1 ? 's' : '') + ' working' : 'idle'), L.cx, y + 14);
    [[-34, 7], [0, 9], [34, 7]].forEach(([dx, r], q) => {
      g.save(); g.translate(L.cx + dx, y + 34); g.rotate((on ? T * (q % 2 ? -1.6 : 1.3) : 0) + q); g.fillStyle = on ? '#e9b44c' : '#6a6e86';
      for (let t = 0; t < 8; t++) { g.rotate(0.785); g.fillRect(-1.5, -r - 3, 3, 4); } g.beginPath(); g.arc(0, 0, r, 0, 6.3); g.fill(); g.fillStyle = '#1b1d30'; g.beginPath(); g.arc(0, 0, r * 0.4, 0, 6.3); g.fill(); g.restore();
    });
  }

  function hud() {
    const run = state.jobs.filter((j) => j.status === 'running').length, wait = state.jobs.filter((j) => j.status === 'paused').length;
    g.fillStyle = 'rgba(8,14,34,.55)'; rr(14, 12, Math.min(380, W - 28), 56, 12); g.fill(); g.textAlign = 'left'; g.font = '800 18px system-ui,sans-serif'; g.fillStyle = '#f2f6ff'; g.fillText('THE WATCHTOWER', 28, 38);
    g.font = '500 12px system-ui'; g.fillStyle = '#c3d2ee'; g.fillText(`${run} running | ${wait} waiting for you | ${awake.size} agents awake | ${state.chain_ok === false ? 'AUDIT CHAIN BROKEN' : 'audit chain ok'}`, 28, 57);
    state.jobs.filter((j) => j.status === 'running' || j.status === 'paused').slice(0, 5).forEach((j, i) => {
      const y = 78 + i * 44; g.fillStyle = 'rgba(8,14,34,.62)'; g.strokeStyle = 'rgba(160,190,255,.35)'; rr(14, y, Math.min(290, W - 28), 36, 8); g.fill(); g.stroke();
      g.fillStyle = j.status === 'running' ? '#fde68a' : '#fbbf24'; g.font = '700 11px ui-monospace,Menlo,monospace'; g.fillText(j.id.slice(0, 12) + '  ' + j.status + '  ' + (j.floor ? j.floor.toUpperCase() : 'planning'), 24, y + 15);
      g.fillStyle = '#d3def2'; g.font = '500 11px system-ui'; g.fillText(j.prompt.slice(0, 42), 24, y + 29);
    });
    const label = 'sky: ' + mode; g.font = '600 11px system-ui'; btn = { x: 14, y: H - 34, w: g.measureText(label).width + 18, h: 22 };
    g.fillStyle = 'rgba(8,14,34,.6)'; g.strokeStyle = 'rgba(160,190,255,.4)'; rr(btn.x, btn.y, btn.w, btn.h, 8); g.fill(); g.stroke(); g.fillStyle = '#d6e2fa'; g.fillText(label, btn.x + 9, btn.y + 15);
    const hit = staff.find((s) => s.px && Math.abs(mouse.x - s.px) < 14 && Math.abs(mouse.y - s.py) < 26);
    if (hit) {
      const t = `${hit.title}  (${hit.id})  ${awake.has(hit.id) ? 'working' : 'idle'}`; g.font = '600 12px system-ui'; const w = g.measureText(t).width + 16, tx = Math.min(W - w - 8, mouse.x + 14);
      g.fillStyle = 'rgba(8,10,24,.95)'; g.strokeStyle = '#8ba7ff'; rr(tx, mouse.y - 12, w, 24, 6); g.fill(); g.stroke(); g.fillStyle = '#fff'; g.fillText(t, tx + 8, mouse.y + 4);
    }
  }

  function wander(dt) {
    staff.forEach((s) => {
      if (awake.has(s.id)) s.tx = s.home; else { s.wait -= dt; if (s.wait <= 0) { s.tx = Math.min(1, Math.max(0, s.home + (rnd(s.seed + T) - 0.5) * 0.5)); s.wait = 2 + rnd(s.seed + T * 3) * 6; } }
      const d = s.tx - s.x; s.x += Math.sign(d) * Math.min(Math.abs(d), dt * (REDUCED ? 0 : 0.07));
    });
  }

  function frame(ts) {
    requestAnimationFrame(frame);   // re-arm first: one bad frame must not freeze the scene
    const dt = Math.min(0.1, (ts - last) / 1000 || 0.016); last = ts; T += dt; DT = dt;
    if (relayout) { relayout = false; layout(); }   // resize events only flag it; the frame rebuilds once
    if (REDUCED && T - drawn < 0.5) return;   // reduced motion: a calm slow refresh, not 60 fps
    drawn = T;
    try { const k = light(); wander(dt); sky(k); beam(k); sea(k); island(k); boats(k); tower(k); ORDER.forEach((f) => room(f, k)); basement(); hud(); }
    catch (e) { if (!failed) { failed = true; console.error('watchtower scene:', e); } cv.width = cv.width; g.setTransform(dpr, 0, 0, dpr, 0, 0); }   // a throw can leave a clip or saved state behind: reset the whole context
  }
  addEventListener('resize', () => { relayout = true; });
  cv.addEventListener('mousemove', (e) => { mouse = { x: e.clientX, y: e.clientY }; });
  cv.addEventListener('mouseleave', () => { mouse = { x: -1, y: -1 }; });
  cv.addEventListener('click', (e) => { if (btn && e.clientX >= btn.x && e.clientX <= btn.x + btn.w && e.clientY >= btn.y && e.clientY <= btn.y + btn.h) mode = { auto: 'day', day: 'night', night: 'auto' }[mode]; });
  layout(); requestAnimationFrame(frame);
  return { update };
})();
"""
