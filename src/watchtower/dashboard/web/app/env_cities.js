import * as THREE from 'three';
import { mat, box, cyl, rng, fbm, ridged, canvasTexture, stoneTexture } from './util.js';
import { smooth, clamp } from './logic.js';
import { Batch, windowMaterials, terrain, trees, ring, rainFx } from './env_kit.js';

const angDiff = (a, b) => { let d = (a - b) % (Math.PI * 2); if (d > Math.PI) d -= Math.PI * 2; if (d < -Math.PI) d += Math.PI * 2; return Math.abs(d); };
const mask = (x, z, a0, half) => 1 - smooth(half - 0.35, half, angDiff(Math.atan2(x, z), a0));
function coast(a0, half, extra) {
  return (x, z, r) => { const m = mask(x, z, a0, half), edge = 740 + fbm(x * 0.004, z * 0.004, 2, 3) * 160; return (m * smooth(edge, edge + 120, r) * (5 + fbm(x * 0.003, z * 0.003, 6, 3) * 14) + extra(x, z, r, m)) ; };
}

function skyline(batch, { a0, span, rIn, rOut, n, hMin, hMax, w = [18, 44], pal, seed, core = 0.5, slab = false }) {
  const r = rng(seed);
  for (let i = 0; i < n; i++) {
    const t = r(), a = a0 + (t - 0.5) * span, rad = rIn + r() * (rOut - rIn), mid = 1 - Math.abs(t - core) * 1.4, h = hMin + Math.pow(r(), 1.8) * (hMax - hMin) * clamp(mid + 0.35, 0.3, 1.2);
    const [x, , z] = ring(a, rad), ww = slab ? 60 + r() * 30 : w[0] + r() * (w[1] - w[0]), dd = slab ? 14 + r() * 4 : w[0] + r() * (w[1] - w[0]);
    batch.box(x, 0, z, ww, h, dd, pal[Math.floor(r() * pal.length)], a + Math.PI / 2 + (r() - 0.5) * 0.15);
    if (h > 130 && r() > 0.5) batch.box(x, h, z, ww * 0.45, 12 + r() * 25, dd * 0.45, 0xb9bec4, a + Math.PI / 2);
  }
}

function wrap(P, group, wm, extra = {}) {
  const fx = extra.fx || [];
  return { group, params: P, update(dt, t, info) { wm && wm.night(1 - info.dl); fx.forEach((f) => f.update(dt, info.cam, info.fx, t)); if (extra.tick) extra.tick(dt, t, info); }, dispose() {} };
}
function lightsAlong(g, pts, color = 0xffd9a0) {
  const geo = new THREE.BufferGeometry().setFromPoints(pts); const m = new THREE.Points(geo, new THREE.PointsMaterial({ color, size: 4, sizeAttenuation: true, transparent: true, opacity: 0.0, fog: false, depthWrite: false })); m.frustumCulled = false; g.add(m); return m;
}
function boatsAt(g, n, rMin, rMax, seed) {
  const r = rng(seed), hull = mat(0x3a2a22, { roughness: 0.8 }), cols = [0xe8d6a8, 0xd9533a, 0xf3f0e6, 0x3a7ac0];
  for (let i = 0; i < n; i++) { const b = new THREE.Group(), a = r() * 6.28, d = rMin + r() * (rMax - rMin); const hm = new THREE.Mesh(new THREE.BoxGeometry(7, 1.8, 2.6), hull); hm.position.y = 0.5; b.add(hm); const s = new THREE.Mesh(new THREE.PlaneGeometry(5, 7), new THREE.MeshStandardMaterial({ color: cols[i % 4], side: THREE.DoubleSide })); s.position.set(0, 5, 0); s.rotation.y = Math.PI / 2; b.add(s); box(0.2, 9, 0.2, hull, 0, 4.5, 0, b); b.position.set(Math.sin(a) * d, 0, Math.cos(a) * d); b.rotation.y = r() * 6; g.add(b); }
}
function cableBridge(a, rad, len, pylonH, color, style) {
  const g = new THREE.Group(), [cx, , cz] = ring(a, rad); g.position.set(cx, 0, cz); g.rotation.y = a + Math.PI / 2;
  const deck = new THREE.Mesh(new THREE.BoxGeometry(len, 3.5, 20), mat(color, { roughness: 0.7 })); deck.position.y = 22; g.add(deck);
  const pts = [];
  const px = style === 'sealink' ? [-len * 0.18, len * 0.18] : [-len * 0.22, len * 0.22];
  px.forEach((x) => { const tw = new THREE.Mesh(new THREE.BoxGeometry(style === 'sealink' ? 7 : 12, pylonH, 7), mat(color)); tw.position.set(x, pylonH / 2, 0); g.add(tw); [-1, 1].forEach((side) => { for (let i = 1; i <= 22; i++) { const dx = i * (style === 'sealink' ? 11 : 9); [-1, 1].forEach((dir) => pts.push(new THREE.Vector3(x, pylonH - 2 - i * 0.4, side * 4), new THREE.Vector3(x + dir * dx, 23, side * 8))); } }); });
  if (style === 'suspension') { for (let s = -1; s <= 1; s += 2) { let prev = null; for (let i = 0; i <= 60; i++) { const x = -len / 2 + (i / 60) * len, u = (x - px[0]) / (px[1] - px[0]), y = u >= 0 && u <= 1 ? 26 + 4 * (u - 0.5) * (u - 0.5) * 4 * 20 - 4 + 0 : 26 + clamp(Math.abs(x) / len, 0, 1) * 55; const p = new THREE.Vector3(x, Math.min(y, pylonH - 4), s * 9); if (prev) pts.push(prev, p); prev = p; if (i % 3 === 0) pts.push(new THREE.Vector3(x, 23, s * 9), new THREE.Vector3(x, p.y, s * 9)); } } }
  g.add(new THREE.LineSegments(new THREE.BufferGeometry().setFromPoints(pts), new THREE.LineBasicMaterial({ color: 0xe6e6e6 })));
  return g;
}

export function mumbai(P) {
  const g = new THREE.Group(), a0 = 3.7, half = 1.5, wm = windowMaterials(0xd6c9b3), pal = [0xd7c7a8, 0xc9b79a, 0xe0d2b6, 0xbfae92, 0xd4b79a, 0xc2c8c4, 0xcfa88c];
  const h = coast(a0, half, () => 0); g.add(terrain({ size: 9000, seg: 220, hole: 640, height: (x, z, r) => h(x, z, r), color: (c, x, z, y) => { if (y < 1) c.setHex(0xb9a57a); else c.setHSL(0.1, 0.18, 0.4 + fbm(x * 0.01, z * 0.01, 3, 2) * 0.1); } }));
  const b = new Batch(); skyline(b, { a0, span: 2.4, rIn: 980, rOut: 1900, n: 520, hMin: 40, hMax: 250, pal, seed: 5, core: 0.4 }); g.add(b.mesh(wm.material));
  const gate = new THREE.Group(), bas = mat(0xc2a45c, { roughness: 0.9 }); box(10, 26, 14, bas, -14, 13, 0, gate); box(10, 26, 14, bas, 14, 13, 0, gate); box(38, 8, 14, bas, 0, 30, 0, gate); const dome = new THREE.Mesh(new THREE.SphereGeometry(8, 20, 12, 0, 6.3, 0, 1.6), bas); dome.position.y = 34; gate.add(dome); for (const x of [-19, 19]) { cyl(2.2, 2.6, 8, bas, x, 32, 6, gate, 10); } const gp = ring(a0 - 0.28, 700); gate.position.set(gp[0], 4, gp[2]); gate.rotation.y = a0 - 0.28 + Math.PI; gate.scale.setScalar(1.5); g.add(gate);
  const taj = new THREE.Group(); box(60, 40, 30, mat(0x9a4a32), 0, 20, 0, taj); [[-26, 12], [26, 12]].forEach(([x]) => { const d = new THREE.Mesh(new THREE.SphereGeometry(7, 14, 8, 0, 6.3, 0, 1.6), mat(0x4a7a66)); d.position.set(x, 42, 0); taj.add(d); }); const tp = ring(a0 + 0.02, 760); taj.position.set(tp[0], 4, tp[2]); taj.rotation.y = a0 + Math.PI; g.add(taj);
  g.add(cableBridge(a0 + 1.1, 1300, 2000, 128, 0xcfcfcf, 'sealink'));
  boatsAt(g, 14, 320, 880, 9); g.add(trees(160, (i, r) => { const a = a0 + (r() - 0.5) * 2.2, d = 770 + r() * 60, p = ring(a, d); return [p[0], 3, p[2]]; }, { color: 0x2f7a3a, size: [9, 14], kind: 'blob', seed: 7 }));
  const lp = []; for (let i = 0; i < 160; i++) { const a = a0 - 1.2 + (i / 160) * 2.4, p = ring(a, 764 + Math.sin(i * 0.3) * 10); lp.push(new THREE.Vector3(p[0], 9, p[2])); } const lights = lightsAlong(g, lp);
  return wrap({ ...P, turbidity: 11, rayleigh: 1.1, mie: 0.02, cover: 0.36, soft: 0.4, fog: 0xe8c7a0, fogDensity: 0.00078, exposure: 1.02, water: 0x3a6a6a }, g, wm, { tick(dt, t, info) { lights.material.opacity = (1 - info.dl) * 0.95; } });
}

function nSeoul() {
  const g = new THREE.Group(), c = mat(0xd6d6d2, { roughness: 0.7 }); cyl(5, 7, 120, c, 0, 60, 0, g, 16); const pod = new THREE.Mesh(new THREE.CylinderGeometry(15, 11, 12, 20), new THREE.MeshStandardMaterial({ color: 0xbfd2e0, metalness: 0.4, roughness: 0.25, emissive: 0xffe0a0, emissiveIntensity: 0.15 })); pod.position.y = 122; g.add(pod);
  cyl(11, 15, 3, c, 0, 130, 0, g, 20); cyl(0.8, 3, 90, mat(0xbababa, { metalness: 0.7, roughness: 0.4 }), 0, 176, 0, g, 8); return g;
}
function hanok(g, cx, cz, rot, r) {
  const tile = mat(0x3b3e44, { roughness: 0.8 }), wall = mat(0xe8dcc0), wood = mat(0x6a3f2a);
  const h = new THREE.Group(); box(10, 3.2, 6, wall, 0, 1.6, 0, h); box(10.4, 0.4, 6.4, wood, 0, 3.3, 0, h);
  const roof = new THREE.Mesh(new THREE.CylinderGeometry(0.2, 5.4, 3.2, 4, 1), tile); roof.rotation.y = Math.PI / 4; roof.scale.set(1.55, 1, 0.95); roof.position.y = 5; roof.castShadow = true; h.add(roof);
  for (const s of [-1, 1]) { const e = box(11.5, 0.4, 1, tile, 0, 3.7, s * 3.5, h); e.rotation.x = s * -0.25; } h.position.set(cx, 3, cz); h.rotation.y = rot; g.add(h);
}

export function korea(P) {
  const g = new THREE.Group(), a0 = 0.6, half = 1.9, wm = windowMaterials(0xe2e4e6, [40, 60, 84]), pal = [0xe9ebec, 0xdedfe0, 0xcbd2d8, 0xd9d2c4, 0xc8ccd2];
  const nam = { x: ring(a0 + 0.35, 1750)[0], z: ring(a0 + 0.35, 1750)[2] };
  const h = coast(a0, half, (x, z, r, m) => Math.exp(-(((x - nam.x) ** 2 + (z - nam.z) ** 2) / (2 * 330 * 330))) * 280 * m + Math.pow(ridged(x * 0.0007, z * 0.0007, 4, 5), 2.2) * 950 * smooth(3000, 4600, r) * (1 - mask(x, z, a0, half) * 0.9));
  g.add(terrain({ size: 11000, seg: 260, hole: 640, height: (x, z, r) => h(x, z, r), color: (c, x, z, y) => { const n = fbm(x * 0.01, z * 0.01, 3, 3); if (y > 480) c.setHSL(0.1, 0.05, 0.62 + n * 0.1); else if (y > 60) c.setHSL(0.12 - n * 0.08, 0.5, 0.3 + n * 0.1); else c.setHSL(0.09, 0.15, 0.4); } }));
  const b = new Batch(); skyline(b, { a0, span: 3.0, rIn: 950, rOut: 2100, n: 420, hMin: 50, hMax: 110, pal, seed: 3, slab: true }); skyline(b, { a0: a0 - 0.5, span: 1.6, rIn: 1500, rOut: 2300, n: 70, hMin: 150, hMax: 260, pal: [0xbcc9d4, 0xd5dde4], seed: 8, w: [26, 40], core: 0.5 }); g.add(b.mesh(wm.material));
  const lotte = new THREE.Mesh(new THREE.CylinderGeometry(7, 40, 555, 6, 1), new THREE.MeshStandardMaterial({ map: wm.material.map, color: 0xbfd0dc, metalness: 0.6, roughness: 0.2 })); const lp = ring(a0 - 0.9, 2500); lotte.position.set(lp[0], 277, lp[2]); lotte.material.map.repeat.set(6, 20); g.add(lotte);
  const tw = nSeoul(); tw.position.set(nam.x, 270, nam.z); g.add(tw);
  const r = rng(5); for (let i = 0; i < 16; i++) { const a = a0 + 0.1 + (r() - 0.5) * 0.5, d = 840 + r() * 140, p = ring(a, d); hanok(g, p[0], p[2], a + (r() - 0.5) * 0.6, d); }
  g.add(trees(420, (i, rr) => { const a = a0 + (rr() - 0.5) * 3, d = 780 + rr() * 900, p = ring(a, d), y = h(p[0], p[2], d); return y > 3 && y < 300 ? [p[0], y - 6, p[2]] : null; }, { color: (rr) => [0xd9622b, 0xe09a2a, 0xb8321f, 0x7a8a2a][Math.floor(rr() * 4)], size: [8, 15], kind: 'blob', seed: 6 }));
  const br = new THREE.Group(), [bx, , bz] = ring(a0 + 1.0, 1020); br.position.set(bx, 0, bz); br.rotation.y = a0 + 1.0 + Math.PI / 2; box(1700, 3, 26, mat(0x9aa0a6), 0, 12, 0, br); for (let i = -8; i <= 8; i++) box(8, 12, 22, mat(0x888e94), i * 100, 6, 0, br); g.add(br);
  const pts = []; for (let i = 0; i < 90; i++) pts.push(new THREE.Vector3((i / 89 - 0.5) * 1700, 15, (i % 2 ? 11 : -11))); const bl = new THREE.Points(new THREE.BufferGeometry().setFromPoints(pts), new THREE.PointsMaterial({ color: 0xffe4a8, size: 5, transparent: true, opacity: 0, fog: false, depthWrite: false })); br.add(bl);
  return wrap({ ...P, turbidity: 7, rayleigh: 1.5, mie: 0.01, cover: 0.4, soft: 0.4, fog: 0xcfd6dc, fogDensity: 0.00072, exposure: 1, water: 0x2c5a6a }, g, wm, { tick(dt, t, info) { bl.material.opacity = (1 - info.dl) * 0.95; } });
}

function empire() {
  const g = new THREE.Group(), m = mat(0xc9c4b6, { roughness: 0.7 }); [[60, 30, 80], [46, 24, 60], [34, 24, 44], [22, 40, 30], [12, 18, 8]].forEach(([w, h, y0], i) => { const yy = [0, 80, 140, 184, 214][i]; box(w, h + (i === 0 ? 80 : 0) - (i === 0 ? 0 : 0), w * 0.9, m, 0, yy + (i === 0 ? 40 : h / 2), 0, g); });
  box(12, 16, 12, m, 0, 232, 0, g); cyl(0.4, 1.6, 55, mat(0xaaaaaa, { metalness: 0.7 }), 0, 266, 0, g, 6); return g;
}
function oneWtc() {
  const g = new THREE.Group(), m = new THREE.MeshStandardMaterial({ color: 0xa8c4d8, metalness: 0.7, roughness: 0.18 }); const t = new THREE.Mesh(new THREE.CylinderGeometry(24, 36, 360, 4, 1), m); t.rotation.y = Math.PI / 4; t.position.y = 180; g.add(t); const top = new THREE.Mesh(new THREE.ConeGeometry(24, 40, 4), m); top.rotation.y = Math.PI / 4; top.position.y = 380; g.add(top); cyl(0.5, 2, 120, mat(0xdddddd, { metalness: 0.8 }), 0, 460, 0, g, 6); return g;
}
function liberty() {
  const g = new THREE.Group(), rock = mat(0x6a6a64, { roughness: 1 }), cop = new THREE.MeshStandardMaterial({ color: 0x6fb5a0, roughness: 0.55, metalness: 0.25 }), gran = mat(0xb9b6ac);
  cyl(30, 40, 8, rock, 0, 4, 0, g, 16); const star = cyl(24, 28, 9, gran, 0, 12, 0, g, 10); box(20, 30, 20, gran, 0, 31, 0, g); box(15, 6, 15, gran, 0, 49, 0, g);
  const body = new THREE.Mesh(new THREE.ConeGeometry(8, 36, 16), cop); body.position.y = 70; body.castShadow = true; g.add(body); const head = new THREE.Mesh(new THREE.SphereGeometry(3.2, 12, 10), cop); head.position.y = 91; g.add(head);
  for (let i = 0; i < 7; i++) { const a = (i / 7) * Math.PI + Math.PI * 0.5, sp = new THREE.Mesh(new THREE.ConeGeometry(0.7, 6, 5), cop); sp.position.set(Math.cos(a) * 3.6, 95, Math.sin(a) * 3.6 * 0.2); sp.rotation.z = Math.cos(a) * 0.9; g.add(sp); }
  const arm = cyl(1.4, 1.8, 24, cop, 6, 98, 0, g, 8); arm.rotation.z = -0.2; const torch = new THREE.Mesh(new THREE.SphereGeometry(2.6, 10, 8), new THREE.MeshStandardMaterial({ color: 0xffffff, emissive: 0xffc860, emissiveIntensity: 5 })); torch.position.set(4.6, 112, 0); g.add(torch); g.userData.torch = torch; return g;
}

export function usa(P) {
  const g = new THREE.Group(), a0 = 4.05, half = 1.2, wm = windowMaterials(0xc3c6c9, [28, 40, 60]), pal = [0xb8bcc0, 0xc9c2b4, 0xa9adb4, 0xd0cdc5, 0x9aa0a6, 0xb5a79a];
  const h = coast(a0, half, () => 0); g.add(terrain({ size: 9000, seg: 220, hole: 640, height: (x, z, r) => h(x, z, r), color: (c, x, z, y) => { if (y < 1) c.setHex(0x7a7468); else c.setHSL(0.09, 0.05, 0.3 + fbm(x * 0.01, z * 0.01, 3, 2) * 0.1); } }));
  const b = new Batch(); skyline(b, { a0, span: 1.9, rIn: 980, rOut: 1800, n: 720, hMin: 50, hMax: 280, pal, seed: 11, core: 0.45, w: [16, 36] }); g.add(b.mesh(wm.material));
  const es = empire(); const ep = ring(a0 + 0.05, 1500); es.position.set(ep[0], 0, ep[2]); es.scale.setScalar(1.15); g.add(es); const wtc = oneWtc(); const wp = ring(a0 - 0.5, 1180); wtc.position.set(wp[0], 0, wp[2]); g.add(wtc);
  const lib = liberty(); const lp = ring(a0 - 1.0, 520); lib.position.set(lp[0], 0, lp[2]); lib.rotation.y = a0 - 1.0 + Math.PI; lib.scale.setScalar(1.1); g.add(lib);
  const bb = cableBridge(a0 + 1.05, 1500, 1700, 90, 0x8e8a80, 'suspension'); g.add(bb);
  boatsAt(g, 10, 260, 900, 14);
  return wrap({ ...P, turbidity: 6, rayleigh: 1.5, mie: 0.006, cover: 0.32, soft: 0.4, fog: 0xbac8d6, fogDensity: 0.0006, exposure: 1, water: 0x1c4a5e }, g, wm, { tick(dt, t) { const tc = lib.userData.torch; if (tc) tc.material.emissiveIntensity = 4 + Math.sin(t * 9) * 1.2; } });
}

function burjKhalifa() {
  const g = new THREE.Group(), m = new THREE.MeshStandardMaterial({ color: 0xc8d6e0, metalness: 0.8, roughness: 0.16 });
  [[0, 230, 30, 22], [230, 190, 22, 15], [420, 170, 15, 9], [590, 150, 9, 3.5]].forEach(([y, h, rb, rt]) => { const t = new THREE.Mesh(new THREE.CylinderGeometry(rt, rb, h, 6, 1), m); t.position.y = y + h / 2; t.castShadow = true; g.add(t); });
  cyl(0.5, 2.4, 100, mat(0xe2e2e2, { metalness: 0.8, roughness: 0.2 }), 0, 790, 0, g, 6); return g;
}
function burjAlArab() {
  const g = new THREE.Group(), white = new THREE.MeshStandardMaterial({ color: 0xf2f4f6, roughness: 0.5, side: THREE.DoubleSide }), glass = mat(0x7ab8d0, { metalness: 0.5, roughness: 0.15 });
  const sail = new THREE.Mesh(new THREE.CylinderGeometry(55, 55, 190, 40, 1, true, 0.2, 2.4), white); sail.position.set(-18, 105, 0); sail.rotation.y = 0.4; sail.scale.set(0.55, 1, 1); g.add(sail);
  box(14, 200, 14, glass, 22, 100, 0, g); cyl(22, 22, 3, mat(0x777777), 24, 190, 0, g, 16); box(10, 12, 10, glass, 18, 206, 0, g); const isl = cyl(60, 70, 8, mat(0xcdb98a, { roughness: 1 }), 0, 0, 0, g, 24);
  for (let i = 0; i < 9; i++) box(1, 100, 1, mat(0xb0b4b8), -40 + i * 6, 56, 0, g).rotation.z = 0.3; return g;
}

export function dubai(P) {
  const g = new THREE.Group(), a0 = 2.25, half = 1.25, wm = windowMaterials(0xcfd8de, [24, 52, 72]), pal = [0xaecbd8, 0xc0d0d8, 0x9fb7c4, 0xd6dde0, 0xb2c2cc, 0xe0d5c0];
  const dunes = (x, z, r, m) => (1 - m) * smooth(900, 1500, r) * (Math.pow(ridged(x * 0.0011, z * 0.0011 + 2, 5, 4), 1.4) * 70 + 8) * 0.9;
  const h = coast(a0, half, dunes); g.add(terrain({ size: 12000, seg: 280, hole: 640, height: (x, z, r) => h(x, z, r), color: (c, x, z, y) => { const n = fbm(x * 0.02, z * 0.02, 4, 3); if (y < 1.5) c.setHex(0xe5d4a6); else c.setHSL(0.1 - n * 0.02, 0.5 + n * 0.1, 0.55 + n * 0.12); } }));
  const b = new Batch(); skyline(b, { a0, span: 2.2, rIn: 1250, rOut: 2300, n: 420, hMin: 70, hMax: 330, pal, seed: 21, core: 0.5, w: [22, 46] }); g.add(b.mesh(wm.material));
  const bk = burjKhalifa(); const kp = ring(a0, 2750); bk.position.set(kp[0], 0, kp[2]); g.add(bk);
  const ba = burjAlArab(); const ap = ring(a0 + 0.7, 520); ba.position.set(ap[0], 0, ap[2]); ba.rotation.y = a0 + 0.7 + Math.PI; g.add(ba);
  g.add(trees(180, (i, r) => { const a = a0 + (r() - 0.5) * 2, d = 790 + r() * 80, p = ring(a, d); return [p[0], 4, p[2]]; }, { color: 0x4a7a32, size: [8, 13], kind: 'blob', seed: 9 }));
  boatsAt(g, 6, 300, 900, 4);
  return wrap({ ...P, turbidity: 9, rayleigh: 1, mie: 0.02, cover: 0.14, soft: 0.4, fog: 0xe6cfa8, fogDensity: 0.00076, exposure: 1.05, water: 0x1a8aa0 }, g, wm);
}
