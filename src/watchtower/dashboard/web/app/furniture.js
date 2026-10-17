import * as THREE from 'three';
import { mat, box, cyl, canvasTexture, rng } from './util.js';
import { RoundedBoxGeometry } from 'three/addons/geometries/RoundedBoxGeometry.js';

const M = {};
export const m = (k, f) => (M[k] || (M[k] = f()));
const wood = () => m('wood', () => mat(0x8a5a35, { roughness: 0.55 }));
const darkWood = () => m('dwood', () => mat(0x4a3022, { roughness: 0.5 }));
const metal = () => m('metal', () => mat(0x3b4048, { roughness: 0.35, metalness: 0.8 }));
const fabric = (c) => m('fab' + c, () => mat(c, { roughness: 0.95 }));
const white = () => m('white', () => mat(0xe9e6df, { roughness: 0.6 }));

export function screenTexture(hue, seed = 1) {      // a monitor full of code-like lines; the page animates its offset
  const r = rng(seed);
  const t = canvasTexture(256, 160, (g, w, h) => {
    g.fillStyle = '#0b1220'; g.fillRect(0, 0, w, h); g.fillStyle = `hsl(${hue},30%,16%)`; g.fillRect(0, 0, w, 12);
    for (let y = 20; y < h - 4; y += 9) { let x = 8 + Math.floor(r() * 4) * 8; const n = 2 + Math.floor(r() * 5); for (let i = 0; i < n; i++) { const L = 14 + r() * 50; g.fillStyle = `hsl(${(hue + r() * 120) % 360},70%,${55 + r() * 25}%)`; g.fillRect(x, y, L, 4); x += L + 6; } }
  });
  t.wrapS = t.wrapT = THREE.RepeatWrapping; return t;
}

export function monitor(hue, seed, screens) {
  const g = new THREE.Group(), tex = screenTexture(hue, seed);
  const frame = box(0.62, 0.38, 0.03, metal(), 0, 0.27, 0, g);
  const scr = new THREE.Mesh(new THREE.PlaneGeometry(0.58, 0.34), new THREE.MeshStandardMaterial({ map: tex, emissive: 0xffffff, emissiveMap: tex, emissiveIntensity: 0.15, roughness: 0.3 }));
  scr.position.set(0, 0.27, 0.017); g.add(scr); box(0.06, 0.1, 0.05, metal(), 0, 0.05, -0.02, g); box(0.22, 0.015, 0.14, metal(), 0, 0.005, 0, g);
  screens.push({ mat: scr.material, tex });
  return g;
}

// A desk whose worker sits on the +z side (facing -z). Monitors stand on the far side, facing +z.
export function desk(opts = {}, screens = []) {
  const g = new THREE.Group(), w = opts.w || 1.6, d = opts.d || 0.8;
  box(w, 0.05, d, wood(), 0, 0.75, 0, g);
  box(0.04, 0.72, d - 0.1, metal(), -w / 2 + 0.05, 0.37, 0, g); box(0.04, 0.72, d - 0.1, metal(), w / 2 - 0.05, 0.37, 0, g);
  box(w - 0.2, 0.4, 0.03, darkWood(), 0, 0.5, -d / 2 + 0.08, g);
  const n = opts.monitors ?? 1;
  for (let i = 0; i < n; i++) { const mo = monitor(opts.hue || 210, (opts.seed || 1) * 7 + i, screens); mo.position.set((i - (n - 1) / 2) * 0.64, 0.775, -0.18); g.add(mo); }
  box(0.42, 0.015, 0.14, m('kb', () => mat(0x22262e, { roughness: 0.5 })), 0, 0.78, 0.18, g);
  const mug = cyl(0.04, 0.035, 0.09, white(), w / 2 - 0.2, 0.82, 0.12, g, 12); mug.castShadow = false;
  if (opts.lamp) { cyl(0.05, 0.06, 0.02, metal(), -w / 2 + 0.2, 0.785, -0.1, g); const arm = cyl(0.01, 0.01, 0.4, metal(), -w / 2 + 0.2, 0.98, -0.1, g, 6); arm.rotation.z = 0.25; }
  return g;
}

export function chair(color = 0x2a3550) {
  const g = new THREE.Group(), fab = fabric(color);
  for (let i = 0; i < 5; i++) { const a = (i / 5) * Math.PI * 2, leg = box(0.28, 0.025, 0.04, metal(), Math.sin(a) * 0.14, 0.07, Math.cos(a) * 0.14, g); leg.rotation.y = a; }
  cyl(0.025, 0.025, 0.3, metal(), 0, 0.22, 0, g, 8);
  const seat = new THREE.Mesh(new RoundedBoxGeometry(0.46, 0.08, 0.46, 3, 0.03), fab); seat.position.y = 0.44; seat.castShadow = true; g.add(seat);
  const back = new THREE.Mesh(new RoundedBoxGeometry(0.44, 0.52, 0.07, 3, 0.03), fab); back.position.set(0, 0.74, -0.22); back.rotation.x = -0.08; back.castShadow = true; g.add(back);
  box(0.05, 0.03, 0.26, metal(), -0.26, 0.6, -0.02, g); box(0.05, 0.03, 0.26, metal(), 0.26, 0.6, -0.02, g);
  return g;
}

export function plant(h = 1.3, seed = 2) {
  const g = new THREE.Group(), r = rng(seed);
  cyl(0.24, 0.18, 0.4, m('pot', () => mat(0xb5683d, { roughness: 0.8 })), 0, 0.2, 0, g, 16);
  const leaf = m('leaf', () => mat(0x2f7a3a, { roughness: 0.8 })), leaf2 = m('leaf2', () => mat(0x3f9a46, { roughness: 0.8 }));
  for (let i = 0; i < 26; i++) { const s = new THREE.Mesh(new THREE.SphereGeometry(0.14 + r() * 0.1, 8, 6), i % 2 ? leaf : leaf2); const a = r() * 6.28, rad = r() * 0.28; s.position.set(Math.cos(a) * rad, 0.45 + r() * h * 0.7, Math.sin(a) * rad); s.scale.y = 0.6 + r() * 0.5; s.castShadow = true; g.add(s); }
  cyl(0.02, 0.03, h * 0.6, darkWood(), 0, 0.4 + h * 0.3, 0, g, 6);
  return g;
}

export function rug(radius, color, ring) {
  const g = new THREE.Group(), tex = canvasTexture(256, 256, (c, w, h) => {
    c.fillStyle = color; c.fillRect(0, 0, w, h); c.strokeStyle = ring; c.lineWidth = 6;
    for (let i = 1; i < 5; i++) { c.beginPath(); c.arc(w / 2, h / 2, w / 2 - i * 22, 0, 6.3); c.stroke(); }
  });
  const rg = new THREE.Mesh(new THREE.CircleGeometry(radius, 48).rotateX(-Math.PI / 2), new THREE.MeshStandardMaterial({ map: tex, roughness: 1 })); rg.position.y = 0.012; rg.receiveShadow = true; g.add(rg); return g;
}

export function shelf(w = 1.8, h = 2.2, seed = 5) {
  const g = new THREE.Group(), r = rng(seed); box(w, h, 0.04, darkWood(), 0, h / 2, -0.17, g);
  box(0.04, h, 0.36, darkWood(), -w / 2, h / 2, 0, g); box(0.04, h, 0.36, darkWood(), w / 2, h / 2, 0, g);
  const rows = Math.floor(h / 0.38); const bm = [0xb04a3a, 0x3a6ea5, 0x4c8c4a, 0xd0a23a, 0x6a4a8a, 0xe8e0d0, 0x2f3a4a].map((c) => mat(c, { roughness: 0.8 }));
  for (let i = 0; i <= rows; i++) {
    box(w, 0.035, 0.36, darkWood(), 0, 0.04 + i * 0.38, 0, g);
    if (i === rows) break;
    let x = -w / 2 + 0.07; while (x < w / 2 - 0.1) { const bw = 0.03 + r() * 0.04, bh = 0.22 + r() * 0.12; box(bw, bh, 0.24, bm[Math.floor(r() * bm.length)], x + bw / 2, 0.06 + i * 0.38 + bh / 2 + 0.01, 0, g); x += bw + 0.004; }
  }
  return g;
}

export function whiteboard(w = 2, h = 1.2) {
  const g = new THREE.Group(), tex = canvasTexture(512, 300, (c, W, H) => {
    c.fillStyle = '#f4f6f8'; c.fillRect(0, 0, W, H); c.strokeStyle = '#3b6fd8'; c.lineWidth = 4; c.strokeRect(30, 30, 120, 60); c.strokeRect(220, 30, 120, 60); c.strokeRect(120, 170, 140, 60); c.strokeRect(330, 170, 140, 60);
    c.beginPath(); c.moveTo(150, 60); c.lineTo(220, 60); c.moveTo(280, 90); c.lineTo(190, 170); c.moveTo(340, 60); c.lineTo(400, 170); c.stroke(); c.fillStyle = '#d33'; c.font = '28px sans-serif'; c.fillText('TODO', 360, 110);
  });
  box(w + 0.06, h + 0.06, 0.05, metal(), 0, 1.5, 0, g);
  const p = new THREE.Mesh(new THREE.PlaneGeometry(w, h), new THREE.MeshStandardMaterial({ map: tex, roughness: 0.4 })); p.position.set(0, 1.5, 0.03); g.add(p);
  box(0.06, 0.9, 0.06, metal(), -w / 2 + 0.1, 0.45, -0.1, g); box(0.06, 0.9, 0.06, metal(), w / 2 - 0.1, 0.45, -0.1, g); return g;
}

export function rack(seed = 3, leds = []) {
  const g = new THREE.Group(), r = rng(seed); box(0.7, 2.1, 0.8, m('rack', () => mat(0x1b1f27, { roughness: 0.4, metalness: 0.6 })), 0, 1.05, 0, g);
  for (let i = 0; i < 14; i++) {
    box(0.62, 0.1, 0.02, m('unit', () => mat(0x2d333f, { roughness: 0.4 })), 0, 0.2 + i * 0.14, 0.4, g);
    for (let k = 0; k < 4; k++) { const ok = r() > 0.12, led = new THREE.Mesh(new THREE.BoxGeometry(0.02, 0.02, 0.01), new THREE.MeshStandardMaterial({ color: 0x000000, emissive: ok ? 0x30ff70 : 0xff3a30, emissiveIntensity: 1.8 })); led.position.set(-0.24 + k * 0.05, 0.2 + i * 0.14, 0.415); g.add(led); leds.push({ m: led.material, phase: r() * 6, ok }); }
  }
  return g;
}

export function table(rx, rz, h = 0.76) {          // an oval table (boardroom / reading)
  const g = new THREE.Group(), top = new THREE.Mesh(new THREE.CylinderGeometry(1, 1, 0.07, 40), wood()); top.scale.set(rx, 1, rz); top.position.y = h; top.castShadow = top.receiveShadow = true; g.add(top);
  cyl(0.12, 0.2, h - 0.04, metal(), 0, h / 2, 0, g, 16); cyl(0.55, 0.6, 0.04, metal(), 0, 0.02, 0, g, 24); return g;
}

export function crate(s = 0.7, c = 0x9a7a4a) { const g = new THREE.Group(); box(s, s, s, mat(c, { roughness: 0.8 }), 0, s / 2, 0, g); const b = mat(0x5a4326); box(s + 0.02, 0.05, s + 0.02, b, 0, s * 0.25, 0, g); box(s + 0.02, 0.05, s + 0.02, b, 0, s * 0.75, 0, g); return g; }

export function globe(radius = 0.6) {
  const g = new THREE.Group(), tex = canvasTexture(512, 256, (c, w, h) => {
    c.fillStyle = '#1d5d9a'; c.fillRect(0, 0, w, h); c.fillStyle = '#4c9a52'; const r = rng(9);
    for (let i = 0; i < 40; i++) { const x = r() * w, y = h * 0.15 + r() * h * 0.7; c.beginPath(); c.ellipse(x, y, 10 + r() * 40, 6 + r() * 22, r() * 3, 0, 6.3); c.fill(); }
  });
  const s = new THREE.Mesh(new THREE.SphereGeometry(radius, 32, 24), new THREE.MeshStandardMaterial({ map: tex, roughness: 0.5 })); s.position.y = radius + 0.9; s.castShadow = true; s.name = 'globe'; g.add(s);
  cyl(0.04, 0.04, 0.9, metal(), 0, 0.45, 0, g, 8); cyl(0.3, 0.34, 0.06, darkWood(), 0, 0.03, 0, g, 20); return g;
}

export function coffee() {
  const g = new THREE.Group(); box(0.5, 0.7, 0.5, metal(), 0, 0.35, 0, g); box(0.4, 0.5, 0.4, m('cof', () => mat(0xb0332a, { roughness: 0.4 })), 0, 0.95, 0, g); box(0.6, 0.04, 0.6, darkWood(), 0, 0.7, 0, g);
  const l = new THREE.Mesh(new THREE.BoxGeometry(0.05, 0.05, 0.02), new THREE.MeshStandardMaterial({ color: 0, emissive: 0x30ff70, emissiveIntensity: 2 })); l.position.set(0.1, 1.0, 0.21); g.add(l); return g;
}

export function lampCeiling(color = 0xfff2d0) {
  const g = new THREE.Group(), s = new THREE.Mesh(new THREE.CylinderGeometry(0.34, 0.34, 0.05, 20), new THREE.MeshStandardMaterial({ color: 0xffffff, emissive: color, emissiveIntensity: 1.5 }));
  g.add(s); g.userData.glow = s.material; return g;
}

export function bench(len = 2.2) {                 // a workbench with tools
  const g = new THREE.Group(); box(len, 0.08, 0.8, wood(), 0, 0.9, 0, g); box(0.06, 0.9, 0.7, metal(), -len / 2 + 0.1, 0.45, 0, g); box(0.06, 0.9, 0.7, metal(), len / 2 - 0.1, 0.45, 0, g); box(len - 0.2, 0.05, 0.6, metal(), 0, 0.3, 0, g);
  box(0.3, 0.12, 0.2, m('tb', () => mat(0xc0392b, { roughness: 0.5 })), 0.5, 1.0, 0, g); cyl(0.05, 0.05, 0.3, metal(), -0.4, 1.1, 0.1, g, 8); box(0.2, 0.04, 0.5, mat(0x99a3ad, { metalness: 0.8, roughness: 0.3 }), -0.1, 0.96, 0.05, g); return g;
}
