import * as THREE from 'three';
import { canvasTexture, rng, fbm, ridged, noise2, stoneTexture } from './util.js';
import { clamp } from './logic.js';

// One draw call for a whole skyline: boxes appended to a single geometry, window texture scaled by building size.
export class Batch {
  constructor() { this.p = []; this.n = []; this.uv = []; this.c = []; this.i = []; }
  box(cx, cy, cz, w, h, d, color, rotY = 0, litCols = true) {
    const col = new THREE.Color(color), s = Math.sin(rotY), c = Math.cos(rotY), hw = w / 2, hd = d / 2, base = this.p.length / 3;
    const faces = [[[hw, 0, hd], [hw, 0, -hd], [hw, h, -hd], [hw, h, hd], [1, 0, 0], d, h], [[-hw, 0, -hd], [-hw, 0, hd], [-hw, h, hd], [-hw, h, -hd], [-1, 0, 0], d, h],
      [[-hw, 0, hd], [hw, 0, hd], [hw, h, hd], [-hw, h, hd], [0, 0, 1], w, h], [[hw, 0, -hd], [-hw, 0, -hd], [-hw, h, -hd], [hw, h, -hd], [0, 0, -1], w, h]];
    let k = 0;
    for (const f of faces) {
      for (let q = 0; q < 4; q++) { const [x, y, z] = f[q]; this.p.push(cx + x * c + z * s, cy + y, cz - x * s + z * c); const nx = f[4][0], nz = f[4][2]; this.n.push(nx * c + nz * s, 0, -nx * s + nz * c); this.c.push(col.r, col.g, col.b); }
      const uw = f[5] / 12.8, vh = f[6] / 14.4, u0 = (cx * 0.37 + cz * 0.11) % 1; this.uv.push(u0, 0, u0 + uw, 0, u0 + uw, vh, u0, vh);
      this.i.push(base + k, base + k + 1, base + k + 2, base + k, base + k + 2, base + k + 3); k += 4;
    }
    const top = [[-hw, h, hd], [hw, h, hd], [hw, h, -hd], [-hw, h, -hd]]; for (const [x, y, z] of top) { this.p.push(cx + x * c + z * s, cy + y, cz - x * s + z * c); this.n.push(0, 1, 0); this.c.push(col.r * 0.8, col.g * 0.8, col.b * 0.8); }
    this.uv.push(0.02, 0.02, 0.03, 0.02, 0.03, 0.03, 0.02, 0.03); this.i.push(base + k, base + k + 1, base + k + 2, base + k, base + k + 2, base + k + 3);
  }
  mesh(material) {
    const g = new THREE.BufferGeometry(); g.setAttribute('position', new THREE.Float32BufferAttribute(this.p, 3)); g.setAttribute('normal', new THREE.Float32BufferAttribute(this.n, 3));
    g.setAttribute('uv', new THREE.Float32BufferAttribute(this.uv, 2)); g.setAttribute('color', new THREE.Float32BufferAttribute(this.c, 3)); g.setIndex(this.i);
    const m = new THREE.Mesh(g, material); m.castShadow = false; m.receiveShadow = false; m.frustumCulled = false; return m;
  }
}

export function windowMaterials(wall = 0xcfd6de, glass = [30, 44, 66]) {   // tile of 4x4 windows; some lit at night
  const r = rng(77);
  const map = canvasTexture(256, 256, (g, w, h) => { g.fillStyle = '#fff'; g.fillRect(0, 0, w, h); for (let y = 0; y < 4; y++) for (let x = 0; x < 4; x++) { g.fillStyle = `rgb(${glass.map((v) => v + r() * 30)})`; g.fillRect(x * 64 + 10, y * 64 + 12, 44, 40); } }, { repeat: [1, 1] });
  const em = canvasTexture(256, 256, (g, w, h) => { g.fillStyle = '#000'; g.fillRect(0, 0, w, h); for (let y = 0; y < 4; y++) for (let x = 0; x < 4; x++) if (r() > 0.45) { g.fillStyle = r() > 0.2 ? '#ffd58a' : '#bfe0ff'; g.fillRect(x * 64 + 10, y * 64 + 12, 44, 40); } });
  for (const t of [map, em]) { t.wrapS = t.wrapT = THREE.RepeatWrapping; }
  const m = new THREE.MeshStandardMaterial({ map, vertexColors: true, roughness: 0.55, metalness: 0.15, emissive: 0xffffff, emissiveMap: em, emissiveIntensity: 0 });
  return { material: m, night(n) { m.emissiveIntensity = n * 2.4; } };
}

export function terrain({ size = 9000, seg = 200, hole = 700, height, color }) {
  const g = new THREE.PlaneGeometry(size, size, seg, seg).rotateX(-Math.PI / 2), pos = g.attributes.position, col = new Float32Array(pos.count * 3), c = new THREE.Color();
  for (let i = 0; i < pos.count; i++) {
    const x = pos.getX(i), z = pos.getZ(i), r = Math.hypot(x, z), h = r < hole ? -30 : height(x, z, r) * clamp((r - hole) / 400, 0, 1) - 12 * (1 - clamp((r - hole) / 400, 0, 1));
    pos.setY(i, h); color(c, x, z, h, r); col.set([c.r, c.g, c.b], i * 3);
  }
  g.setAttribute('color', new THREE.BufferAttribute(col, 3)); g.computeVertexNormals();
  const m = new THREE.Mesh(g, new THREE.MeshStandardMaterial({ vertexColors: true, roughness: 0.95 })); m.receiveShadow = false; m.frustumCulled = false; return m;
}

export function trees(count, place, { color = 0x2f5a2a, size = [6, 14], kind = 'cone', seed = 5 } = {}) {   // place(i, rand) -> [x,y,z] or null
  const r = rng(seed), geo = kind === 'cone' ? new THREE.ConeGeometry(1, 3, 7) : new THREE.IcosahedronGeometry(1, 1), mesh = new THREE.InstancedMesh(geo, new THREE.MeshStandardMaterial({ roughness: 1, vertexColors: false }), count), m = new THREE.Matrix4(), q = new THREE.Quaternion(), col = new THREE.Color();
  let n = 0;
  for (let i = 0; i < count; i++) {
    const p = place(i, r); if (!p) continue; const s = size[0] + r() * (size[1] - size[0]);
    m.compose(new THREE.Vector3(p[0], p[1] + s * (kind === 'cone' ? 0.9 : 0.8), p[2]), q, new THREE.Vector3(s * 0.38, s * (kind === 'cone' ? 0.6 : 0.5), s * 0.38)); mesh.setMatrixAt(n, m);
    col.set(typeof color === 'function' ? color(r) : color).offsetHSL((r() - 0.5) * 0.03, 0, (r() - 0.5) * 0.08); mesh.setColorAt(n, col); n++;
  }
  mesh.count = n; mesh.frustumCulled = false; return mesh;
}

export function bridgeDeck(len, w, color, y = 18) { const g = new THREE.Group(); const m = new THREE.Mesh(new THREE.BoxGeometry(len, 3, w), new THREE.MeshStandardMaterial({ color, roughness: 0.6 })); m.position.y = y; g.add(m); return g; }

export function cableTower(h, color, spread = 12) {   // an H pylon with a few cables, used by suspension / cable-stayed bridges
  const g = new THREE.Group(), mt = new THREE.MeshStandardMaterial({ color, roughness: 0.7 });
  for (const s of [-1, 1]) { const l = new THREE.Mesh(new THREE.BoxGeometry(6, h, 6), mt); l.position.set(0, h / 2, s * spread); g.add(l); }
  for (const y of [h * 0.55, h * 0.92]) { const b = new THREE.Mesh(new THREE.BoxGeometry(5, 4, spread * 2 + 6), mt); b.position.y = y; g.add(b); } return g;
}

export function cables(a, b, n, color = 0xdddddd) {   // fan of lines between two points (a: deck, b: pylon top)
  const pts = []; for (let i = 0; i < n; i++) { const t = i / (n - 1); pts.push(new THREE.Vector3(a.x + (b.x - a.x) * 0.0 + (t - 0.5) * 220, a.y, a.z), new THREE.Vector3(b.x, b.y - t * 20, b.z)); }
  return new THREE.LineSegments(new THREE.BufferGeometry().setFromPoints(pts), new THREE.LineBasicMaterial({ color }));
}

export function rainFx() {
  const N = 1400, pos = new Float32Array(N * 6), r = rng(4), g = new THREE.BufferGeometry();
  for (let i = 0; i < N; i++) { const x = (r() - 0.5) * 90, y = r() * 60, z = (r() - 0.5) * 90; pos.set([x, y, z, x, y - 1.2, z], i * 6); }
  g.setAttribute('position', new THREE.BufferAttribute(pos, 3));
  const m = new THREE.LineSegments(g, new THREE.LineBasicMaterial({ color: 0xbcc8dc, transparent: true, opacity: 0.35, depthWrite: false })); m.frustumCulled = false;
  return { object: m, update(dt, cam, on) { m.visible = on; if (!on) return; m.position.set(cam.x, Math.max(0, cam.y - 20), cam.z); const a = g.attributes.position; for (let i = 0; i < N; i++) { let y = a.getY(i * 2) - dt * 38; if (y < -6) y += 66; a.setY(i * 2, y); a.setY(i * 2 + 1, y - 1.3); } a.needsUpdate = true; } };
}

export function petalFx(color = 0xffc6d8) {
  const N = 500, pos = new Float32Array(N * 3), r = rng(8), g = new THREE.BufferGeometry();
  for (let i = 0; i < N; i++) pos.set([(r() - 0.5) * 80, r() * 40, (r() - 0.5) * 80], i * 3);
  g.setAttribute('position', new THREE.BufferAttribute(pos, 3));
  const m = new THREE.Points(g, new THREE.PointsMaterial({ color, size: 0.5, transparent: true, opacity: 0.9, depthWrite: false })); m.frustumCulled = false;
  return { object: m, update(dt, cam, on, t) { m.visible = on; if (!on) return; m.position.set(cam.x, Math.max(0, cam.y - 18), cam.z); const a = g.attributes.position; for (let i = 0; i < N; i++) { let y = a.getY(i) - dt * 1.6, x = a.getX(i) + Math.sin(t * 0.7 + i) * dt * 2.2; if (y < -2) y += 42; a.setXYZ(i, x, y, a.getZ(i) + Math.cos(t * 0.5 + i * 1.3) * dt * 1.5); } a.needsUpdate = true; } };
}

export function ring(angle, rad, y = 0) { return [Math.sin(angle) * rad, y, Math.cos(angle) * rad]; }
export { noise2, fbm, ridged, stoneTexture };
