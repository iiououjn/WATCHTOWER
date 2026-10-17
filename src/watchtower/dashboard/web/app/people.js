import * as THREE from 'three';
import { rng, labelSprite } from './util.js';
import { clamp, shortTitle, FLOOR_HUE } from './logic.js';

const SKIN = [0xf2d3b8, 0xe0b48c, 0xc58c5f, 0x9a6540, 0x6f4429, 0xf6dcc8];
const HAIR = [0x1b1612, 0x3a2a1c, 0x6b4a2c, 0xb38a4a, 0x8c8c90, 0x101010, 0x5a1f1a];
const cache = {};
const mat = (k, c, o = {}) => cache[k + c] || (cache[k + c] = new THREE.MeshStandardMaterial({ color: c, roughness: 0.75, ...o }));

function limb(len, rad, material, parent, y = 0) {
  const g = new THREE.Group(); g.position.y = y; parent.add(g);
  const m = new THREE.Mesh(new THREE.CapsuleGeometry(rad, len - rad * 2, 4, 8), material); m.position.y = -len / 2; m.castShadow = true; g.add(m);
  return g;
}

export function createPerson(role, index) {
  const r = rng(index * 977 + 13), hue = FLOOR_HUE[role.floor] ?? 210, skin = mat('s', SKIN[Math.floor(r() * SKIN.length)]);
  const shirt = mat('sh', new THREE.Color().setHSL(hue / 360, 0.55, 0.42 + r() * 0.1).getHex()), pants = mat('p', [0x23283a, 0x3a3228, 0x2a3a3a, 0x1d1d22][Math.floor(r() * 4)]);
  const hair = mat('h', HAIR[Math.floor(r() * HAIR.length)]), root = new THREE.Group(), body = new THREE.Group(); root.add(body);
  const P = { role, group: root, body, mode: 'stand', yaw: 0, target: null, wait: 1 + r() * 4, phase: r() * 6, seat: null, sitT: 0, idleSit: false, hover: false, label: null, home: null, r };

  const pelvis = new THREE.Mesh(new THREE.BoxGeometry(0.34, 0.2, 0.2), pants); pelvis.position.y = 0.95; pelvis.castShadow = true; body.add(pelvis);
  P.torso = new THREE.Group(); P.torso.position.y = 1.02; body.add(P.torso);
  const chest = new THREE.Mesh(new THREE.BoxGeometry(0.4, 0.52, 0.22), shirt); chest.position.y = 0.26; chest.castShadow = true; P.torso.add(chest);
  const badge = new THREE.Mesh(new THREE.BoxGeometry(0.06, 0.04, 0.01), new THREE.MeshStandardMaterial({ color: 0xffffff, emissive: new THREE.Color().setHSL(hue / 360, 0.9, 0.6), emissiveIntensity: 1.2 })); badge.position.set(0.1, 0.38, 0.116); P.torso.add(badge);
  P.head = new THREE.Group(); P.head.position.y = 0.6; P.torso.add(P.head);
  const skull = new THREE.Mesh(new THREE.SphereGeometry(0.125, 16, 12), skin); skull.position.y = 0.1; skull.castShadow = true; P.head.add(skull);
  const cap = new THREE.Mesh(new THREE.SphereGeometry(0.133, 16, 10, 0, Math.PI * 2, 0, Math.PI * (0.45 + r() * 0.15)), hair); cap.position.y = 0.105; cap.rotation.x = -0.2; P.head.add(cap);
  for (const x of [-0.045, 0.045]) { const e = new THREE.Mesh(new THREE.SphereGeometry(0.014, 6, 6), mat('e', 0x111111)); e.position.set(x, 0.12, 0.115); P.head.add(e); }
  P.neckY = 0.6;
  P.shoulderL = limb(0.3, 0.05, shirt, P.torso, 0.46); P.shoulderL.position.x = -0.26; P.shoulderR = limb(0.3, 0.05, shirt, P.torso, 0.46); P.shoulderR.position.x = 0.26;
  P.elbowL = limb(0.28, 0.045, skin, P.shoulderL, -0.28); P.elbowR = limb(0.28, 0.045, skin, P.shoulderR, -0.28);
  P.hipL = limb(0.45, 0.075, pants, body, 0.92); P.hipL.position.x = -0.1; P.hipR = limb(0.45, 0.075, pants, body, 0.92); P.hipR.position.x = 0.1;
  P.kneeL = limb(0.45, 0.062, pants, P.hipL, -0.45); P.kneeR = limb(0.45, 0.062, pants, P.hipR, -0.45);
  for (const k of [P.kneeL, P.kneeR]) { const f = new THREE.Mesh(new THREE.BoxGeometry(0.1, 0.06, 0.24), mat('f', 0x181818)); f.position.set(0, -0.46, 0.05); f.castShadow = true; k.add(f); }
  const hit = new THREE.Mesh(new THREE.BoxGeometry(0.7, 1.9, 0.7), new THREE.MeshBasicMaterial({ visible: false })); hit.position.y = 0.95; hit.userData.person = P; root.add(hit); P.hit = hit;
  return P;
}

const ease = (cur, tgt, k) => cur + (tgt - cur) * k;
const angDiff = (a, b) => { let d = (b - a) % (Math.PI * 2); if (d > Math.PI) d -= Math.PI * 2; if (d < -Math.PI) d += Math.PI * 2; return d; };

// One step of a person's day. `awake`: the tower says this agent is working now.
export function updatePerson(P, dt, t, awake, points) {
  const g = P.group, k = 1 - Math.exp(-dt * 9), speed = 1.15;
  let want = null, moving = false;
  const sitHere = P.seat && (awake || P.idleSit);
  if (sitHere) want = P.seat.pos;
  else if (P.target) want = P.target;
  if (!sitHere && P.mode === 'sit') { P.mode = 'stand'; }
  if (want && !(P.mode === 'sit' && sitHere)) {
    const dx = want.x - g.position.x, dz = want.z - g.position.z, d = Math.hypot(dx, dz);
    if (d > 0.08) { const s = Math.min(d, speed * dt); g.position.x += dx / d * s; g.position.z += dz / d * s; P.yaw += angDiff(P.yaw, Math.atan2(dx, dz)) * Math.min(1, dt * 8); moving = true; P.mode = 'walk'; }
    else if (sitHere) { P.mode = 'sit'; } else { P.target = null; P.mode = 'stand'; P.wait = 2 + P.r() * 6; if (P.seat && P.r() < 0.3) { P.idleSit = true; P.wait = 6 + P.r() * 8; } }
  }
  if (P.mode === 'sit') { g.position.x = ease(g.position.x, P.seat.pos.x, k); g.position.z = ease(g.position.z, P.seat.pos.z, k); P.yaw += angDiff(P.yaw, P.seat.rot) * Math.min(1, dt * 6); }
  else if (!want) { P.wait -= dt; if (P.wait <= 0) { P.idleSit = false; const p = points[Math.floor(P.r() * points.length)]; if (p) P.target = p; P.wait = 3; } }
  g.rotation.y = P.yaw;

  const sit = P.mode === 'sit' ? 1 : 0; P.sitT = ease(P.sitT, sit, 1 - Math.exp(-dt * 7));
  const ph = (P.walkPh = (P.walkPh || P.phase) + (moving ? dt * 6.5 : 0)), sw = moving ? Math.sin(ph) : 0, bend = moving ? Math.max(0, -Math.cos(ph)) : 0;
  const typing = awake && sit, nod = Math.sin(t * 0.9 + P.phase) * 0.04, tap = typing ? Math.sin(t * 16 + P.phase) * 0.09 : 0;
  P.body.position.y = -0.43 * P.sitT + (moving ? Math.abs(Math.sin(ph)) * 0.025 : Math.sin(t * 1.6 + P.phase) * 0.004);
  const hipX = ease(sw * 0.65, -1.5, P.sitT), kneeX = ease(bend * 0.9 * (sw > 0 ? 1 : 0.4), 1.5, P.sitT);
  P.hipL.rotation.x = hipX; P.hipR.rotation.x = ease(-sw * 0.65, -1.5, P.sitT); P.kneeL.rotation.x = kneeX; P.kneeR.rotation.x = ease(bend * 0.9 * (sw < 0 ? 1 : 0.4), 1.5, P.sitT);
  const armSw = moving ? 0.55 : 0, sh = typing ? -1.05 : P.sitT * -0.6;
  P.shoulderL.rotation.x = (typing ? sh + tap : sh * P.sitT) + (-sw * armSw) * (1 - P.sitT); P.shoulderR.rotation.x = (typing ? sh - tap : sh * P.sitT) + (sw * armSw) * (1 - P.sitT);
  P.elbowL.rotation.x = typing ? -1.1 + tap : P.sitT * -0.8 - (moving ? 0.25 : 0.08); P.elbowR.rotation.x = typing ? -1.1 - tap : P.sitT * -0.8 - (moving ? 0.25 : 0.08);
  P.shoulderL.rotation.z = 0.06; P.shoulderR.rotation.z = -0.06;
  P.torso.rotation.x = typing ? 0.14 : 0; P.head.rotation.x = typing ? 0.12 + nod : P.idleSit && P.sitT > 0.9 ? 0.55 + nod : nod;
  P.head.rotation.y = typing ? Math.sin(t * 0.5 + P.phase) * 0.12 : 0;

  const show = awake || P.hover;
  if (show && !P.label) { P.label = labelSprite(shortTitle(P.role.title), FLOOR_HUE[P.role.floor] ?? 210, 0.9); P.label.position.y = 2.15; g.add(P.label); }
  if (P.label) P.label.visible = show;
}
