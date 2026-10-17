import * as THREE from 'three';
import { clamp } from './logic.js';

export function rng(seed) {                           // small deterministic generator: the same scene every load
  let s = (seed >>> 0) || 1;
  return () => { s = (s + 0x6d2b79f5) >>> 0; let t = s; t = Math.imul(t ^ (t >>> 15), t | 1); t ^= t + Math.imul(t ^ (t >>> 7), t | 61); return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };
}

const hash = (x, y, s) => { const n = Math.sin(x * 127.1 + y * 311.7 + s * 74.7) * 43758.5453; return n - Math.floor(n); };
export function noise2(x, y, s = 0) {                 // smooth value noise, 0..1
  const xi = Math.floor(x), yi = Math.floor(y), xf = x - xi, yf = y - yi, u = xf * xf * (3 - 2 * xf), v = yf * yf * (3 - 2 * yf);
  const a = hash(xi, yi, s), b = hash(xi + 1, yi, s), c = hash(xi, yi + 1, s), d = hash(xi + 1, yi + 1, s);
  return a + (b - a) * u + (c - a) * v + (a - b - c + d) * u * v;
}
export function fbm(x, y, s = 0, oct = 5) {
  let amp = 0.5, f = 1, sum = 0, norm = 0;
  for (let i = 0; i < oct; i++) { sum += amp * noise2(x * f, y * f, s + i * 7); norm += amp; amp *= 0.5; f *= 2.03; }
  return sum / norm;
}
export function ridged(x, y, s = 0, oct = 5) {        // sharp mountain ridges, 0..1
  let amp = 0.5, f = 1, sum = 0, norm = 0;
  for (let i = 0; i < oct; i++) { sum += amp * (1 - Math.abs(noise2(x * f, y * f, s + i * 5) * 2 - 1)); norm += amp; amp *= 0.5; f *= 2.1; }
  return sum / norm;
}

export function canvasTexture(w, h, draw, opts = {}) {
  const c = document.createElement('canvas'); c.width = w; c.height = h;
  draw(c.getContext('2d'), w, h);
  const t = new THREE.CanvasTexture(c);
  t.colorSpace = opts.linear ? THREE.NoColorSpace : THREE.SRGBColorSpace;
  if (opts.repeat) { t.wrapS = t.wrapT = THREE.RepeatWrapping; t.repeat.set(opts.repeat[0], opts.repeat[1]); }
  t.anisotropy = 4;
  return t;
}

export function stoneTexture(base = [196, 188, 170], course = 14, seed = 3) {   // dressed stone courses, for the tower and castles
  const r = rng(seed);
  return canvasTexture(512, 512, (g, w, h) => {
    g.fillStyle = `rgb(${base})`; g.fillRect(0, 0, w, h);
    for (let y = 0, row = 0; y < h; y += course, row++) {
      for (let x = -((row % 2) * 40); x < w; x += 80) {
        const sh = (r() - 0.5) * 34; g.fillStyle = `rgb(${base.map((v) => clamp(v + sh, 0, 255))})`; g.fillRect(x + 1, y + 1, 78, course - 2);
      }
      g.fillStyle = 'rgba(60,50,40,.35)'; g.fillRect(0, y, w, 1.5);
    }
    for (let i = 0; i < 1800; i++) { g.fillStyle = `rgba(${r() < 0.5 ? '40,34,28' : '255,255,245'},${r() * 0.07})`; g.fillRect(r() * w, r() * h, 1 + r() * 3, 1 + r() * 3); }
  }, { repeat: [3, 1] });
}

export function bumpFrom(tex) { const t = tex.clone(); t.colorSpace = THREE.NoColorSpace; t.needsUpdate = true; return t; }

const labelCache = new Map();
export function labelSprite(text, hue = 210, scale = 1) {   // a name tag that always faces the camera
  if (labelCache.size > 80) labelCache.clear();
  const key = text + '|' + hue; let tex = labelCache.get(key);
  if (!tex) {
    tex = canvasTexture(320, 72, (g, w, h) => {
      g.font = '600 30px system-ui,sans-serif'; const tw = Math.min(w - 16, g.measureText(text).width + 34);
      g.fillStyle = 'rgba(8,12,28,.86)'; g.strokeStyle = `hsl(${hue},85%,65%)`; g.lineWidth = 3;
      g.beginPath(); g.roundRect ? g.roundRect((w - tw) / 2, 8, tw, h - 16, 16) : g.rect((w - tw) / 2, 8, tw, h - 16); g.fill(); g.stroke();
      g.fillStyle = '#eef4ff'; g.textAlign = 'center'; g.textBaseline = 'middle'; g.fillText(text, w / 2, h / 2 + 1);
    });
    labelCache.set(key, tex);
  }
  const s = new THREE.Sprite(new THREE.SpriteMaterial({ map: tex, depthTest: false, transparent: true }));
  s.scale.set(1.9 * scale, 0.43 * scale, 1); s.renderOrder = 20; return s;
}

export function mat(color, o = {}) { return new THREE.MeshStandardMaterial({ color, roughness: 0.7, metalness: 0, ...o }); }
export function box(w, h, d, m, x = 0, y = 0, z = 0, parent) {
  const b = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), m); b.position.set(x, y, z); b.castShadow = b.receiveShadow = true; if (parent) parent.add(b); return b;
}
export function cyl(rt, rb, h, m, x = 0, y = 0, z = 0, parent, seg = 20) {
  const c = new THREE.Mesh(new THREE.CylinderGeometry(rt, rb, h, seg), m); c.position.set(x, y, z); c.castShadow = c.receiveShadow = true; if (parent) parent.add(c); return c;
}
export function disposeTree(o) {
  o.traverse((n) => { if (n.isInstancedMesh) n.dispose(); if (n.geometry) n.geometry.dispose(); const ms = n.material ? [].concat(n.material) : []; ms.forEach((m) => { for (const k in m) if (m[k] && m[k].isTexture && !m[k].userData.keep) m[k].dispose(); m.dispose(); }); });
}
