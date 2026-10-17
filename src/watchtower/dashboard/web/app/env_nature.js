import * as THREE from 'three';
import { mat, box, cyl, canvasTexture, stoneTexture, rng, fbm, ridged } from './util.js';
import { clamp, smooth } from './logic.js';
import { terrain, trees, rainFx, petalFx, ring } from './env_kit.js';

const stone = (c = [150, 146, 136], seed = 2) => { const t = stoneTexture(c, 12, seed); t.repeat.set(3, 2); return new THREE.MeshStandardMaterial({ map: t, roughness: 0.95 }); };
const crenel = (g, x, y, z, w, d, m, n = 6) => { for (let i = 0; i < n; i++) box(w / (n * 2 - 1), 2.2, 1.4, m, x - w / 2 + (w / (n * 2 - 1)) * (i * 2 + 0.5), y, z, g); };

function tower(g, m, x, z, r, h, roofColor, y0 = 0) {
  const c = cyl(r, r * 1.08, h, m, x, y0 + h / 2, z, g, 18); const top = cyl(r * 1.18, r * 1.12, 2.4, m, x, y0 + h + 1.2, z, g, 18);
  if (roofColor) { const cone = new THREE.Mesh(new THREE.ConeGeometry(r * 1.25, r * 1.5, 18), mat(roofColor, { roughness: 0.7 })); cone.position.set(x, y0 + h + 3.2 + r * 0.7, z); cone.castShadow = true; g.add(cone); }
  else for (let i = 0; i < 10; i++) { const a = (i / 10) * 6.28; box(2.2, 2.2, 2.2, m, x + Math.sin(a) * r * 1.15, y0 + h + 3.4, z + Math.cos(a) * r * 1.15, g); }
  return c;
}

function castle(kind) {
  const g = new THREE.Group(), m = stone(kind === 'wales' ? [160, 150, 128] : [128, 122, 114], kind === 'wales' ? 3 : 4);
  if (kind === 'scotland') {   // Eilean Donan: a keep and towers on a rock islet, a stone bridge to the shore
    const islet = new THREE.Mesh(new THREE.CylinderGeometry(34, 46, 14, 20), mat(0x4a4a44, { roughness: 1 })); islet.position.y = 0; g.add(islet);
    const base = 7; box(26, 30, 22, m, 0, base + 15, 0, g); crenel(g, 0, base + 31, 11, 26, 2, m); crenel(g, 0, base + 31, -11, 26, 2, m);
    tower(g, m, -16, 10, 6, 22, 0x3a3a46, base); tower(g, m, 17, -9, 7, 26, null, base); box(30, 9, 3, m, 0, base + 4.5, 17, g); box(3, 9, 24, m, -20, base + 4.5, -3, g);
    for (let i = 0; i < 4; i++) box(34 + i * 14, 3 + (i % 2), 8, m, 70 + i * 34, 3.5, 36 + i * 7, g).rotation.y = 0.2;
    box(2, 7, 2, mat(0x22222a), 0, base + 36, 0, g);
  } else {                     // Caernarfon: banded polygonal towers around a long curtain wall
    const band = new THREE.MeshStandardMaterial({ map: (() => { const t = canvasTexture(128, 128, (c, w, h) => { for (let y = 0; y < h; y += 16) { c.fillStyle = (y / 16) % 2 ? '#a89c82' : '#7c7466'; c.fillRect(0, y, w, 16); } }, { repeat: [2, 2] }); return t; })(), roughness: 0.95 });
    box(60, 20, 6, m, 0, 10, 20, g); box(60, 20, 6, m, 0, 10, -20, g); box(6, 20, 40, m, 30, 10, 0, g); box(6, 20, 40, m, -30, 10, 0, g); crenel(g, 0, 21, 20, 60, 2, m, 12); crenel(g, 0, 21, -20, 60, 2, m, 12);
    for (const [x, z, h] of [[-30, 20, 34], [30, 20, 38], [-30, -20, 32], [30, -20, 30], [0, 20, 42]]) { const c = cyl(8, 8.8, h, band, x, h / 2, z, g, 8); cyl(9.6, 9, 3, band, x, h + 1.5, z, g, 8); for (let i = 0; i < 8; i++) { const a = (i / 8) * 6.28; box(2.4, 2.2, 2.4, m, x + Math.sin(a) * 9.3, h + 4, z + Math.cos(a) * 9.3, g); } }
    const flagT = canvasTexture(128, 80, (c, w, h) => { c.fillStyle = '#ffffff'; c.fillRect(0, 0, w, h / 2); c.fillStyle = '#00a651'; c.fillRect(0, h / 2, w, h / 2); c.fillStyle = '#d4111e'; c.beginPath(); c.ellipse(w / 2, h / 2, 26, 15, 0, 0, 6.3); c.fill(); });
    const flag = new THREE.Mesh(new THREE.PlaneGeometry(10, 6), new THREE.MeshBasicMaterial({ map: flagT, side: THREE.DoubleSide })); flag.position.set(0, 52, 20); g.add(flag); box(0.4, 14, 0.4, mat(0x333333), 0, 47, 20, g); g.userData.flag = flag;
  }
  return g;
}

function base(params, group, extra = {}) {
  const fx = extra.fx || [], night = extra.night, flags = [];
  return { group, params, update(dt, t, info) { fx.forEach((f) => f.update(dt, info.cam, info.fx, t)); if (night) night(1 - info.dl); if (extra.tick) extra.tick(dt, t, info); }, dispose() {} };
}

export function ocean(P) {
  const g = new THREE.Group(), r = rng(6), rock = mat(0x4b4a46, { roughness: 1 });
  for (let i = 0; i < 9; i++) { const a = r() * 6.28, d = 500 + r() * 2200, s = 8 + r() * 30, m = new THREE.Mesh(new THREE.DodecahedronGeometry(s, 1), rock); m.position.set(Math.sin(a) * d, s * 0.2, Math.cos(a) * d); m.scale.y = 0.7; g.add(m); }
  return base({ ...P }, g);
}

export function scotland(P) {
  const g = new THREE.Group(), h = (x, z, r) => (Math.pow(ridged(x * 0.00052 + 3, z * 0.00052 + 1, 2, 5), 1.7) * 980 + fbm(x * 0.004, z * 0.004, 9, 4) * 70) * smooth(750, 2300, r);
  const t = terrain({ size: 10000, seg: 230, hole: 650, height: h, color: (c, x, z, y) => { const n = fbm(x * 0.01, z * 0.01, 5, 3); if (y > 650 + n * 120) c.setHex(0xe8ecef); else if (y > 380) c.setHSL(0.07, 0.08, 0.34 + n * 0.12); else if (y > 110) c.setHSL(0.84 - n * 0.12, 0.18, 0.28 + n * 0.1); else if (y > 6) c.setHSL(0.24 + n * 0.04, 0.34, 0.22 + n * 0.08); else c.setHex(0x40452e); } }); g.add(t);
  const cs = castle('scotland'); cs.position.set(...ring(2.55, 540)); cs.rotation.y = 0.8; g.add(cs);
  g.add(trees(900, (i, r) => { const a = r() * 6.28, d = 760 + r() * 900, x = Math.sin(a) * d, z = Math.cos(a) * d, y = h(x, z, d) - 12 * 0; return y > 4 && y < 180 ? [x, y - 10, z] : null; }, { color: 0x1e3d26, size: [9, 22], seed: 3 }));
  const rain = rainFx(); g.add(rain.object);
  return base({ ...P, turbidity: 8.5, rayleigh: 0.9, mie: 0.006, cover: 0.8, soft: 0.45, fog: 0x98a2aa, fogDensity: 0.0007, exposure: 0.92, water: 0x1b3a40 }, g, { fx: [rain] });
}

export function wales(P) {
  const g = new THREE.Group(), h = (x, z, r) => (fbm(x * 0.0016, z * 0.0016, 3, 5) * 190 + Math.pow(ridged(x * 0.0005 - 2, z * 0.0005 + 4, 6, 5), 2) * 900 * smooth(1800, 3600, r)) * smooth(650, 1400, r) + 3 * smooth(700, 800, r);
  g.add(terrain({ size: 10000, seg: 230, hole: 640, height: h, color: (c, x, z, y) => { const n = fbm(x * 0.012, z * 0.012, 1, 3); if (y < 7) c.setHex(0xd9c79a); else if (y > 520 + n * 80) c.setHSL(0.1, 0.08, 0.36); else c.setHSL(0.26 + n * 0.05, 0.5, 0.26 + n * 0.14); } }));
  const cs = castle('wales'); cs.position.set(...ring(0.95, 640)); cs.rotation.y = 0.95 + Math.PI; g.add(cs);
  const sheep = new THREE.InstancedMesh(new THREE.SphereGeometry(1, 6, 5), mat(0xf0eee6, { roughness: 1 }), 320), m4 = new THREE.Matrix4(), r = rng(12); let n = 0;
  for (let i = 0; i < 320; i++) { const a = r() * 6.28, d = 800 + r() * 1100, x = Math.sin(a) * d, z = Math.cos(a) * d, y = h(x, z, d) - 12; if (y < 6 || y > 160) continue; m4.compose(new THREE.Vector3(x, y + 1.2, z), new THREE.Quaternion(), new THREE.Vector3(2.2, 1.5, 1.6)); sheep.setMatrixAt(n++, m4); }
  sheep.count = n; sheep.frustumCulled = false; g.add(sheep);
  g.add(trees(500, (i, r) => { const a = r() * 6.28, d = 800 + r() * 1200, x = Math.sin(a) * d, z = Math.cos(a) * d, y = h(x, z, d) - 12; return y > 8 && y < 140 ? [x, y, z] : null; }, { color: 0x3e7a34, size: [9, 17], kind: 'blob', seed: 4 }));
  const rain = rainFx(); g.add(rain.object);
  return base({ ...P, turbidity: 5.5, rayleigh: 1.6, mie: 0.005, cover: 0.62, soft: 0.4, fog: 0xaebfc9, fogDensity: 0.00058, exposure: 0.95, water: 0x1d5a66 }, g, { fx: [rain], tick(dt, t) { const f = cs.userData.flag; if (f) f.rotation.y = Math.sin(t * 2) * 0.25; } });
}

function pagoda() {
  const g = new THREE.Group(), wood = mat(0x7a2e22, { roughness: 0.7 }), roof = mat(0x2c3a3a, { roughness: 0.6 }), wall = mat(0xd8c9a8);
  for (let i = 0; i < 5; i++) { const s = 1 - i * 0.14, y = i * 7; box(12 * s, 5, 12 * s, i % 2 ? wall : wood, 0, y + 2.5 + 3, 0, g); const rf = new THREE.Mesh(new THREE.ConeGeometry(11.5 * s, 3.6, 4), roof); rf.rotation.y = Math.PI / 4; rf.position.y = y + 7.4 + 3; rf.scale.set(1, 1, 1); rf.castShadow = true; g.add(rf); }
  cyl(0.3, 0.3, 9, mat(0xb8a25a, { metalness: 0.7, roughness: 0.4 }), 0, 41, 0, g, 8); box(14, 3, 14, mat(0x77705f), 0, 1.5, 0, g); return g;
}
function torii() {
  const g = new THREE.Group(), red = mat(0xd2331f, { roughness: 0.55 });
  for (const s of [-1, 1]) cyl(0.9, 1.1, 14, red, s * 6, 7, 0, g, 12); const top = box(18, 1.6, 1.8, red, 0, 14.4, 0, g); top.rotation.z = 0; box(21, 1.1, 2.3, mat(0x1c1c1c), 0, 15.7, 0, g); box(14, 1, 1.2, red, 0, 11.5, 0, g);
  return g;
}
function tokyoTower() {
  const g = new THREE.Group(), red = mat(0xe0431f, { roughness: 0.6 }), white = mat(0xf1f1ee, { roughness: 0.6 });
  [[160, 22, 12], [150, 12, 6], [110, 6, 3]].forEach(([h, rb, rt], i) => { const c = new THREE.Mesh(new THREE.CylinderGeometry(rt, rb, h, 4, 1, true), i % 2 ? white : red); c.rotation.y = Math.PI / 4; c.position.y = [80, 235, 365][i]; c.material.side = THREE.DoubleSide; g.add(c); });
  const deck = cyl(20, 18, 6, red, 0, 150, 0, g, 4); deck.rotation.y = Math.PI / 4; cyl(0.8, 2.4, 70, white, 0, 395, 0, g, 6); return g;
}

export function japan(P) {
  const g = new THREE.Group(), fuji = { x: -1200, z: -6800 }, h = (x, z, r) => { const d = Math.hypot(x - fuji.x, z - fuji.z), cone = Math.pow(Math.max(0, 1 - d / 5200), 1.55) * 3100; return (cone + fbm(x * 0.0012, z * 0.0012, 8, 4) * 260 * smooth(600, 2500, r) + ridged(x * 0.0007, z * 0.0007, 3, 4) * 380 * smooth(2800, 4800, r) * (d > 3500 ? 1 : 0)) * smooth(700, 1500, r); };
  g.add(terrain({ size: 17000, seg: 300, hole: 650, height: h, color: (c, x, z, y) => { const n = fbm(x * 0.006, z * 0.006, 2, 3); if (y > 1750 + n * 380) c.setHex(0xf3f5f8); else if (y > 900) c.setHSL(0.06, 0.15, 0.32 + n * 0.1); else if (y > 8) c.setHSL(0.3 + n * 0.04, 0.36, 0.22 + n * 0.08); else c.setHex(0xcbb98e); } }));
  const isle = new THREE.Mesh(new THREE.CylinderGeometry(70, 86, 10, 24), new THREE.MeshStandardMaterial({ color: 0x4e6a3a, roughness: 1 })); const ip = ring(1.35, 310); isle.position.set(ip[0], 0, ip[2]); g.add(isle);
  const pg = pagoda(); pg.position.set(ip[0] + 8, 5, ip[2] - 6); pg.scale.setScalar(1.15); g.add(pg);
  const r = rng(31), pink = [0xffb7c8, 0xffa6bd, 0xffd0dc];
  for (let i = 0; i < 26; i++) { const a = r() * 6.28, d = r() * 58, tx = ip[0] + Math.sin(a) * d, tz = ip[2] + Math.cos(a) * d; const trunk = cyl(0.5, 0.8, 5, mat(0x4a3428), tx, 7.5, tz, g, 6); for (let k = 0; k < 4; k++) { const s = new THREE.Mesh(new THREE.IcosahedronGeometry(3 + r() * 2.5, 1), mat(pink[Math.floor(r() * 3)], { roughness: 1 })); s.position.set(tx + (r() - 0.5) * 4, 11 + r() * 3, tz + (r() - 0.5) * 4); s.castShadow = true; g.add(s); } }
  const tg = torii(); const tp = ring(2.55, 150); tg.position.set(tp[0], -2, tp[2]); tg.rotation.y = 2.55 + Math.PI / 2; g.add(tg);
  const tt = tokyoTower(); const tp2 = ring(4.35, 3300); tt.position.set(tp2[0], 0, tp2[2]); tt.scale.setScalar(2.2); g.add(tt);
  const petals = petalFx(); g.add(petals.object);
  return base({ ...P, turbidity: 4, rayleigh: 2.2, mie: 0.003, cover: 0.34, soft: 0.35, fog: 0xdccfdd, fogDensity: 0.00052, exposure: 1, water: 0x2a5f78 }, g, { fx: [petals] });
}
