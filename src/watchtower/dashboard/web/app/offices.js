import * as THREE from 'three';
import { mat, box, cyl, canvasTexture } from './util.js';
import { FLOOR_HUE, clamp } from './logic.js';
import * as F from './furniture.js';

export const FLOOR_H = 3.7, CEIL = 3.4;
const polar = (a, rad) => new THREE.Vector3(Math.sin(a) * rad, 0, Math.cos(a) * rad);

function place(parent, obj, p, rotY = 0) { obj.position.copy(p); obj.rotation.y = rotY; parent.add(obj); return obj; }

// Desks around the wall facing the middle; the worker's chair is on the wall side. Returns seats in desk order.
function ringDesks(room, n, rd, opts, ctx) {
  const step = (Math.PI * 2) / n, off = opts.offset ?? 0.5;
  for (let i = 0; i < n; i++) {
    const a = i * step + off, d = F.desk({ ...opts, seed: i + 1 }, ctx.screens);
    place(room, d, polar(a, rd), a);
    const cp = polar(a, rd + 0.9), c = F.chair(opts.chair || 0x2a3550); place(room, c, cp, a + Math.PI);
    ctx.seats.push({ pos: cp.clone(), rot: a + Math.PI });
    ctx.points.push(polar(a + step / 2, rd + 0.35));
  }
}

function ceilingLights(room, R, n, color, ctx) {
  for (let i = 0; i < n; i++) { const l = F.lampCeiling(color); l.position.copy(i === 0 && n > 3 ? new THREE.Vector3() : polar(i * (Math.PI * 2 / (n - (n > 3 ? 1 : 0))), R * 0.5)); l.position.y = CEIL - 0.03; room.add(l); ctx.glow.push(l.userData.glow); }
}

function wallProps(room, R, items, ctx) {   // shelves / plants / boards standing against the wall at the given angles
  items.forEach(([kind, a, extra]) => {
    const p = polar(a, R - 0.55); let o;
    if (kind === 'shelf') o = F.shelf(1.7, 2.3, Math.round(a * 10)); else if (kind === 'plant') o = F.plant(1.4 + (extra || 0), Math.round(a * 7)); else if (kind === 'board') o = F.whiteboard(1.8, 1.1);
    else if (kind === 'rack') o = F.rack(Math.round(a * 5), ctx.leds); else if (kind === 'coffee') o = F.coffee(); else if (kind === 'crate') o = F.crate(0.6 + (extra || 0)); else return;
    place(room, o, p, a + Math.PI);
  });
}

const THEMES = {
  csuite(room, R, ctx) {
    const t = F.table(1.9, 1.15); room.add(t); room.add(F.rug(2.8, '#4a1e2a', '#c9a24a')); ctx.rugIndex = room.children.length - 1;
    const n = 6; for (let i = 0; i < n; i++) { const a = (i / n) * Math.PI * 2 + 0.3, cp = new THREE.Vector3(Math.sin(a) * 2.35, 0, Math.cos(a) * 1.6); const c = F.chair(0x6a2a3a); place(room, c, cp, a + Math.PI); ctx.seats.push({ pos: cp.clone(), rot: a + Math.PI }); ctx.points.push(polar(a + 0.5, R - 1.6)); }
    wallProps(room, R, [['plant', 0.4, 0.3], ['plant', 3.5], ['shelf', 1.9], ['coffee', 5.0], ['plant', 5.7, 0.2]], ctx);
    const cap = new THREE.Mesh(new THREE.CylinderGeometry(0.5, 0.5, 0.02, 24), new THREE.MeshStandardMaterial({ color: 0xffffff, emissive: 0xffd78a, emissiveIntensity: 0.6 })); cap.position.y = 0.86; room.add(cap);
  },
  f5(room, R, ctx) {
    ringDesks(room, 5, R - 2.1, { monitors: 2, hue: 285, chair: 0x3a2a55 }, ctx);
    const pill = cyl(0.25, 0.25, 2.4, new THREE.MeshStandardMaterial({ color: 0x220a33, emissive: 0xb050ff, emissiveIntensity: 1.1, transparent: true, opacity: 0.85 }), 0, 1.2, 0, room, 24); ctx.spin.push(pill);
    const ring = new THREE.Mesh(new THREE.TorusGeometry(0.7, 0.04, 8, 40), new THREE.MeshStandardMaterial({ color: 0x000000, emissive: 0x30ff70, emissiveIntensity: 2 })); ring.rotation.x = Math.PI / 2; ring.position.y = 1.3; room.add(ring); ctx.spin.push(ring); ctx.pulse.push(ring.material);
    box(1.2, 0.08, 1.2, mat(0x2a2038, { metalness: 0.5, roughness: 0.4 }), 0, 0.04, 0, room); room.add(F.rug(2.2, '#251a38', '#7a4fc0'));
    wallProps(room, R, [['plant', 0.2], ['shelf', 1.7], ['plant', 3.3, 0.3], ['board', 4.6], ['shelf', 5.9]], ctx);
  },
  f4(room, R, ctx) {
    ringDesks(room, 5, R - 2.1, { monitors: 2, hue: 160, chair: 0x1f4a3a, lamp: true }, ctx);
    wallProps(room, R, [['rack', 0.15], ['rack', 0.55], ['coffee', 2.1], ['plant', 3.4], ['board', 4.7], ['rack', 5.9]], ctx);
    room.add(F.rug(1.9, '#12302a', '#34c08a'));
    const pad = cyl(0.8, 0.9, 0.12, mat(0x203a30, { metalness: 0.6, roughness: 0.3 }), 0, 0.06, 0, room, 28); const btn = cyl(0.14, 0.14, 0.06, new THREE.MeshStandardMaterial({ color: 0x000000, emissive: 0x30ff70, emissiveIntensity: 2 }), 0, 0.15, 0, room, 16); ctx.pulse.push(btn.material);
  },
  f3(room, R, ctx) {
    ringDesks(room, 4, R - 2.1, { monitors: 1, hue: 24, chair: 0x5a3a1c, offset: 0.9 }, ctx);
    const b1 = F.bench(2.4), b2 = F.bench(2.0); place(room, b1, new THREE.Vector3(-0.2, 0, -0.9), 0.1); place(room, b2, new THREE.Vector3(0.3, 0, 1.0), -0.15);
    const belt = box(3.2, 0.25, 0.7, mat(0x1a1c20, { roughness: 0.6 }), 0, 0.5, 0.05, room); belt.rotation.y = 0.35;
    wallProps(room, R, [['crate', 0.2, 0.2], ['crate', 0.45], ['shelf', 1.8], ['crate', 3.2, 0.3], ['plant', 4.4], ['shelf', 5.5], ['crate', 6.0]], ctx);
  },
  f2(room, R, ctx) {
    ringDesks(room, 6, R - 2.0, { monitors: 2, hue: 205, chair: 0x1f3a66, lamp: true }, ctx);
    wallProps(room, R, [['board', 0.1], ['coffee', 1.6], ['plant', 2.7, 0.2], ['board', 3.8], ['plant', 4.9], ['shelf', 5.6]], ctx);
    const bag = new THREE.Mesh(new THREE.SphereGeometry(0.5, 16, 12), mat(0xc0502f, { roughness: 0.95 })); bag.scale.y = 0.55; bag.position.set(0.6, 0.28, 0.4); bag.castShadow = true; room.add(bag);
    room.add(F.rug(2.0, '#16263e', '#4a8ad8'));
  },
  f1(room, R, ctx) {
    ringDesks(room, 3, R - 2.1, { monitors: 1, hue: 120, chair: 0x2a4a2a, lamp: true, offset: 1.0 }, ctx);
    for (let i = 0; i < 5; i++) { const a = 2.4 + i * 0.74, s = F.shelf(1.7, 2.4, i + 3); place(room, s, polar(a, R - 0.55), a + Math.PI); }
    const g = F.globe(0.55); g.position.set(0.1, 0, 0.1); room.add(g); ctx.spin.push(g.getObjectByName('globe'));
    const t = F.table(0.9, 0.55, 0.74); t.position.set(-0.4, 0, 1.7); room.add(t);
    wallProps(room, R, [['plant', 0.15], ['plant', 1.9, 0.3]], ctx);
    room.add(F.rug(2.4, '#1f3a22', '#8ac060'));
  },
};

export function buildOffice(key, R) {
  const room = new THREE.Group(), ctx = { seats: [], points: [], screens: [], leds: [], glow: [], spin: [], pulse: [] };
  (THEMES[key] || THEMES.f2)(room, R, ctx);
  ceilingLights(room, R, 4, 0xfff0d0, ctx);
  const L = new THREE.PointLight(new THREE.Color().setHSL(FLOOR_HUE[key] / 360, 0.6, 0.78), 0, 14, 1.3); L.position.set(0, CEIL - 0.9, 0); room.add(L);
  return { group: room, ...ctx, light: L };
}

export function animateOffice(o, t, lit, awakeCount) {
  const on = lit ? 1 : 0;
  o.light.intensity += ((8 + 18 * on) - o.light.intensity) * 0.08;
  o.glow.forEach((g) => { g.emissiveIntensity += ((1.6 + 3.2 * on) - g.emissiveIntensity) * 0.08; });
  o.screens.forEach((s, i) => { s.tex.offset.y = (t * (0.02 + 0.03 * on) + i * 0.13) % 1; s.mat.emissiveIntensity += ((0.5 + 2.8 * on) - s.mat.emissiveIntensity) * 0.06; });
  o.leds.forEach((l) => { l.m.emissiveIntensity = l.ok ? 1.2 + 0.9 * Math.sin(t * 3 + l.phase) : 1.6 + 1.4 * Math.sin(t * 9 + l.phase); });
  o.spin.forEach((s, i) => { s.rotation.y = t * (0.6 + i * 0.3) * (awakeCount ? 2 : 1); });
  o.pulse.forEach((p) => { p.emissiveIntensity = 1.2 + 1.4 * (0.5 + 0.5 * Math.sin(t * 4)); });
}
