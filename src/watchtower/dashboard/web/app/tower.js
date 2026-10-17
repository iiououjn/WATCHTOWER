import * as THREE from 'three';
import { mat, box, cyl, stoneTexture, canvasTexture, labelSprite, fbm, noise2, rng } from './util.js';
import { FLOORS, FLOOR_NAMES, FLOOR_HUE, lerp, clamp } from './logic.js';
import { FLOOR_H } from './offices.js';

export const BASE_Y = 0.9, PLINTH_H = 3.4, R_BASE = 6.4, R_TOP = 4.7, OPEN = 2.15, WALL = 0.45;
export const TOP_Y = BASE_Y + PLINTH_H + FLOOR_H * FLOORS.length;
export const floorY = (k) => BASE_Y + PLINTH_H + (FLOORS.length - 1 - k) * FLOOR_H;     // floor surface of room k (0 = penthouse)
export const radiusAt = (y) => lerp(R_BASE, R_TOP, clamp((y - BASE_Y) / (TOP_Y - BASE_Y), 0, 1));

function cutWall(r0, r1, h, y, material, inner) {
  const g = new THREE.CylinderGeometry(r1, r0, h, 72, 1, true, OPEN / 2, Math.PI * 2 - OPEN);
  const m = new THREE.Mesh(g, material); m.position.y = y + h / 2; m.castShadow = m.receiveShadow = true; if (inner) m.scale.set(0.93, 1, 0.93);
  return m;
}

export function buildIsland() {
  const g = new THREE.Group(), geo = new THREE.CylinderGeometry(14, 24, 7, 96, 18, false), pos = geo.attributes.position, col = new Float32Array(pos.count * 3), c = new THREE.Color();
  for (let i = 0; i < pos.count; i++) {
    const x = pos.getX(i), y = pos.getY(i), z = pos.getZ(i), r = Math.hypot(x, z), a = Math.atan2(z, x), top = y > 3.4;
    const lump = fbm(x * 0.18, z * 0.18, 4, 4), edge = fbm(Math.cos(a) * 3 + 5, Math.sin(a) * 3 + 5, 9, 3);
    let ny = y, nr = r;
    if (top) { nr = r * (0.9 + 0.2 * edge); ny = 3.5 + lump * 0.9 * (r / 14) ; } else { nr = r * (0.88 + 0.28 * edge) + lump * 2.5 * (1 - (y + 3.5) / 7); ny = y + (lump - 0.5) * 1.6; }
    pos.setXYZ(i, Math.cos(a) * nr, ny, Math.sin(a) * nr);
    if (top) c.setHSL(0.27 + (lump - 0.5) * 0.06, 0.45, 0.28 + lump * 0.14); else c.setHSL(0.08, 0.12 + lump * 0.1, 0.22 + lump * 0.16 + (y > 1 ? 0.05 : 0));
    col.set([c.r, c.g, c.b], i * 3);
  }
  geo.setAttribute('color', new THREE.BufferAttribute(col, 3)); geo.computeVertexNormals();
  const isl = new THREE.Mesh(geo, new THREE.MeshStandardMaterial({ vertexColors: true, roughness: 0.95, flatShading: false })); isl.position.y = BASE_Y - 3.5; isl.receiveShadow = isl.castShadow = true; g.add(isl);
  const r = rng(21), rockM = mat(0x5a5750, { roughness: 1 });
  for (let i = 0; i < 26; i++) { const a = r() * 6.28, rad = 12 + r() * 11, s = 0.5 + r() * 1.8, rk = new THREE.Mesh(new THREE.DodecahedronGeometry(s, 0), rockM); rk.position.set(Math.cos(a) * rad, BASE_Y + (rad > 17 ? -1.2 : 0.1), Math.sin(a) * rad); rk.rotation.set(r() * 3, r() * 3, r() * 3); rk.scale.y = 0.6 + r() * 0.5; rk.castShadow = rk.receiveShadow = true; g.add(rk); }
  const grassM = mat(0x4f7a38, { roughness: 1 });
  for (let i = 0; i < 90; i++) { const a = r() * 6.28, rad = 8 + r() * 4.5, t = new THREE.Mesh(new THREE.ConeGeometry(0.1, 0.5 + r() * 0.4, 5), grassM); t.position.set(Math.cos(a) * rad, BASE_Y + 0.3, Math.sin(a) * rad); g.add(t); }
  return g;
}

export function buildCottage() {
  const g = new THREE.Group(), tex = stoneTexture([150, 140, 126], 12, 8); tex.repeat.set(2, 1);
  box(3.6, 2.2, 2.8, new THREE.MeshStandardMaterial({ map: tex, roughness: 0.95 }), 0, 1.1, 0, g);
  const shape = new THREE.Shape(); shape.moveTo(-2.2, 0); shape.lineTo(2.2, 0); shape.lineTo(0, 1.5); shape.closePath();
  const roofM = new THREE.MeshStandardMaterial({ map: canvasTexture(256, 256, (c, w, h) => { c.fillStyle = '#9a7c42'; c.fillRect(0, 0, w, h); for (let i = 0; i < 1400; i++) { c.fillStyle = `rgba(${60 + Math.random() * 90},${45 + Math.random() * 60},20,${Math.random() * 0.5})`; c.fillRect(Math.random() * w, Math.random() * h, 2, 14 + Math.random() * 14); } }), roughness: 1 });
  for (const s of [-1, 1]) { const p = box(2.55, 0.28, 3.4, roofM, 0, 2.5, s * 0.92, g); p.rotation.x = s * 0.98; p.position.y = 2.45; }
  const ch = box(0.55, 1.3, 0.55, mat(0x6a655c), 1.2, 2.9, -0.4, g);
  const door = box(0.8, 1.5, 0.06, mat(0x7a3a4a, { roughness: 0.7 }), -0.6, 0.75, 1.42, g);
  const win = box(0.6, 0.5, 0.05, new THREE.MeshStandardMaterial({ color: 0x1a1a22, emissive: 0xffc070, emissiveIntensity: 1.1 }), 0.9, 1.3, 1.42, g);
  const wheel = new THREE.Group(); wheel.position.set(-1.95, 1.2, 0); g.add(wheel);
  const rim = new THREE.Mesh(new THREE.TorusGeometry(0.85, 0.09, 8, 28), mat(0x8a6a2c, { metalness: 0.7, roughness: 0.4 })); rim.rotation.y = Math.PI / 2; wheel.add(rim);
  for (let i = 0; i < 6; i++) { const s = box(0.07, 1.7, 0.07, mat(0x8a6a2c, { metalness: 0.7, roughness: 0.4 }), 0, 0, 0, wheel); s.rotation.x = (i / 6) * Math.PI; }
  const smoke = []; const smokeTex = canvasTexture(64, 64, (c, w, h) => { const gr = c.createRadialGradient(w / 2, h / 2, 2, w / 2, h / 2, w / 2); gr.addColorStop(0, 'rgba(210,210,215,.9)'); gr.addColorStop(1, 'rgba(210,210,215,0)'); c.fillStyle = gr; c.fillRect(0, 0, w, h); });
  for (let i = 0; i < 14; i++) { const s = new THREE.Sprite(new THREE.SpriteMaterial({ map: smokeTex, transparent: true, depthWrite: false, opacity: 0 })); s.userData.t = i / 14; g.add(s); smoke.push(s); }
  const glow = new THREE.PointLight(0xffb060, 0, 9, 1.6); glow.position.set(0.9, 1.3, 2.3); g.add(glow);
  g.userData.update = (dt, t, working) => {
    wheel.rotation.x += dt * (working ? 2.4 : 0.15); glow.intensity += ((working ? 9 : 2) - glow.intensity) * 0.05; win.material.emissiveIntensity = working ? 2 : 0.8;
    smoke.forEach((s) => { s.userData.t = (s.userData.t + dt * 0.22) % 1; const u = s.userData.t; s.position.set(1.2 + Math.sin(u * 5 + s.id) * 0.3 + u * 0.8, 3.6 + u * 3.4, -0.4); s.scale.setScalar(0.5 + u * 1.7); s.material.opacity = (working ? 0.55 : 0.18) * Math.sin(u * Math.PI); });
  };
  return g;
}

export function buildTower(state) {
  const g = new THREE.Group(), interior = new THREE.Group(), walls = new THREE.Group(); g.add(interior, walls);
  const tex = stoneTexture(), outer = new THREE.MeshStandardMaterial({ map: tex, roughness: 0.92, bumpMap: tex, bumpScale: 0.8 });
  const plaster = new THREE.MeshStandardMaterial({ color: 0xe6dccb, roughness: 0.95, side: THREE.BackSide }), edgeM = mat(0xcfc5b0, { roughness: 0.9 }), dark = mat(0x34312f, { roughness: 0.9 });
  const granite = new THREE.MeshStandardMaterial({ map: stoneTexture([98, 94, 92], 18, 5), roughness: 0.95 });
  const plinth = cyl(R_BASE + 0.1, R_BASE + 0.9, PLINTH_H, granite, 0, BASE_Y + PLINTH_H / 2, 0, g, 72); plinth.material.map.repeat.set(4, 1);
  const door = new THREE.Mesh(new THREE.BoxGeometry(1.3, 2.3, 0.3), new THREE.MeshStandardMaterial({ color: 0x3a1f26, roughness: 0.7 })); door.position.set(0, BASE_Y + 1.15, R_BASE + 0.82); g.add(door);
  const arch = new THREE.Mesh(new THREE.TorusGeometry(0.65, 0.12, 8, 16, Math.PI), edgeM); arch.position.set(0, BASE_Y + 2.3, R_BASE + 0.9); g.add(arch);
  for (let i = 0; i < 4; i++) box(2.6 - i * 0.2, 0.2, 1.0 - i * 0.05, granite, 0, BASE_Y + 0.1 + i * 0.2, R_BASE + 1.25 - i * 0.2, g);
  const floors = FLOORS.map((key, k) => {
    const y0 = floorY(k), r0 = radiusAt(y0), r1 = radiusAt(y0 + FLOOR_H);
    const slab = cyl(r0 - 0.15, r0 - 0.15, 0.3, mat(0x6b5a48, { roughness: 0.7 }), 0, y0 - 0.15, 0, interior, 72);
    const rimGlow = new THREE.Mesh(new THREE.TorusGeometry(r0 - 0.1, 0.045, 6, 96), new THREE.MeshStandardMaterial({ color: 0, emissive: new THREE.Color().setHSL(FLOOR_HUE[key] / 360, 1, 0.6), emissiveIntensity: 0 })); rimGlow.rotation.x = Math.PI / 2; rimGlow.position.y = y0 + 0.02; interior.add(rimGlow);
    walls.add(cutWall(r0, r1, FLOOR_H, y0, outer)); walls.add(cutWall(r0 - WALL, r1 - WALL, FLOOR_H, y0, plaster, true));
    for (const s of [-1, 1]) { const a = s * (OPEN / 2), jamb = new THREE.Mesh(new THREE.PlaneGeometry(WALL + 0.02, FLOOR_H), edgeM); jamb.material.side = THREE.DoubleSide; const rm = (r0 + r1) / 2 - WALL / 2; jamb.position.set(Math.sin(a) * rm, y0 + FLOOR_H / 2, Math.cos(a) * rm); jamb.rotation.y = a - Math.PI / 2; walls.add(jamb); }
    const windows = [];   // arched windows on the far wall: dark glass that glows when that floor has live work
    for (let i = 0; i < 5; i++) { const a = Math.PI + (i - 2) * 0.62, rr = radiusAt(y0 + 1.9) + 0.02, w = new THREE.Mesh(new THREE.BoxGeometry(0.75, 1.5, 0.12), new THREE.MeshStandardMaterial({ color: 0x1d2330, roughness: 0.2, emissive: 0xffc47a, emissiveIntensity: 0 })); w.position.set(Math.sin(a) * rr, y0 + 1.9, Math.cos(a) * rr); w.rotation.y = a; walls.add(w); windows.push(w.material); }
    const sign = labelSprite(FLOOR_NAMES[key], FLOOR_HUE[key], 1.5); const sa = (k % 2 ? 1 : -1) * (OPEN / 2 + 0.16); sign.position.set(Math.sin(sa) * (r0 + 1.6), y0 + 1.7, Math.cos(sa) * (r0 + 1.6)); walls.add(sign);
    return { key, y0, slab, rimGlow, windows };
  });
  const topY = TOP_Y;
  cyl(radiusAt(topY) - 0.1, radiusAt(topY) - 0.1, 0.35, mat(0x6b5a48), 0, topY - 0.17, 0, interior, 72);
  const gal = cyl(R_TOP + 1.25, R_TOP + 0.6, 0.45, granite, 0, topY - 0.05, 0, g, 72), deck = cyl(R_TOP + 1.25, R_TOP + 1.25, 0.12, dark, 0, topY + 0.2, 0, g, 72);
  const posts = new THREE.InstancedMesh(new THREE.CylinderGeometry(0.035, 0.035, 1.05, 6), dark, 72), pm = new THREE.Matrix4();
  for (let i = 0; i < 72; i++) { const a = (i / 72) * Math.PI * 2; pm.setPosition(Math.sin(a) * (R_TOP + 1.12), topY + 0.78, Math.cos(a) * (R_TOP + 1.12)); posts.setMatrixAt(i, pm); } g.add(posts);
  const rail = new THREE.Mesh(new THREE.TorusGeometry(R_TOP + 1.12, 0.05, 6, 96), dark); rail.rotation.x = Math.PI / 2; rail.position.y = topY + 1.3; g.add(rail);
  const LR = 2.3, LY = topY + 0.26, glass = new THREE.MeshPhysicalMaterial({ color: 0xbfe4ff, transparent: true, opacity: 0.16, roughness: 0.05, metalness: 0, side: THREE.DoubleSide, depthWrite: false });
  cyl(LR, LR, 3, glass, 0, LY + 1.5, 0, g, 36); cyl(LR + 0.1, LR + 0.1, 0.25, dark, 0, LY + 0.1, 0, g, 36); cyl(LR + 0.12, LR + 0.12, 0.2, dark, 0, LY + 3.0, 0, g, 36);
  for (let i = 0; i < 16; i++) { const a = (i / 16) * Math.PI * 2, bar = box(0.07, 3, 0.07, dark, Math.sin(a) * LR, LY + 1.5, Math.cos(a) * LR, g); for (const s of [-1, 1]) { const d = box(0.04, 3.3, 0.04, dark, Math.sin(a) * LR, LY + 1.5, Math.cos(a) * LR, g); d.rotation.set(0, 0, 0); d.rotation.z = 0; d.rotation.y = a; d.rotateX(0); d.rotateOnWorldAxis(new THREE.Vector3(Math.sin(a + Math.PI / 2), 0, Math.cos(a + Math.PI / 2)), s * 0.55); } }
  const roof = new THREE.Mesh(new THREE.ConeGeometry(LR + 0.45, 1.5, 36), mat(0x2a3a3a, { metalness: 0.6, roughness: 0.35 })); roof.position.y = LY + 3.95; roof.castShadow = true; g.add(roof);
  const ball = new THREE.Mesh(new THREE.SphereGeometry(0.28, 16, 12), mat(0x2a3a3a, { metalness: 0.6, roughness: 0.3 })); ball.position.y = LY + 4.85; g.add(ball);
  const vane = new THREE.Group(); vane.position.y = LY + 5.3; g.add(vane); box(0.04, 0.9, 0.04, dark, 0, 0, 0, vane);
  const flag = new THREE.Mesh(new THREE.PlaneGeometry(0.9, 0.42), new THREE.MeshBasicMaterial({ color: 0x4ade80, side: THREE.DoubleSide })); flag.position.set(0.45, 0.28, 0); vane.add(flag);
  const lampMat = new THREE.MeshStandardMaterial({ color: 0xffffff, emissive: 0xffe3a0, emissiveIntensity: 3 }), lamp = new THREE.Mesh(new THREE.SphereGeometry(0.45, 20, 16), lampMat); lamp.position.y = LY + 1.4; g.add(lamp);
  for (let i = 0; i < 5; i++) { const ring = new THREE.Mesh(new THREE.TorusGeometry(0.75, 0.035, 6, 36), new THREE.MeshStandardMaterial({ color: 0xcfeaff, transparent: true, opacity: 0.5, emissive: 0x6a8aa8, emissiveIntensity: 0.3 })); ring.rotation.x = Math.PI / 2; ring.position.y = LY + 0.7 + i * 0.35; g.add(ring); }
  const lampLight = new THREE.PointLight(0xffe3a0, 30, 40, 1.6); lampLight.position.y = LY + 1.4; g.add(lampLight);

  const beam = new THREE.Group(); beam.position.y = LY + 1.4; g.add(beam);
  const beamMat = new THREE.ShaderMaterial({ transparent: true, depthWrite: false, blending: THREE.AdditiveBlending, side: THREE.DoubleSide, fog: false, uniforms: { uI: { value: 0.3 }, uC: { value: new THREE.Color(1, 0.92, 0.65) } },
    vertexShader: 'varying float vK; varying vec3 vN, vV; void main(){ vK = clamp(abs(position.z) / 140., 0., 1.); vN = normalize(normalMatrix * normal); vec4 mv = modelViewMatrix * vec4(position,1.); vV = normalize(-mv.xyz); gl_Position = projectionMatrix * mv; }',
    fragmentShader: 'uniform float uI; uniform vec3 uC; varying float vK; varying vec3 vN, vV; void main(){ float f = pow(abs(dot(vN, vV)), 1.6); gl_FragColor = vec4(uC, f * (1. - vK) * uI); }' });
  for (const s of [1, -1]) { const cone = new THREE.Mesh(new THREE.ConeGeometry(11, 140, 28, 1, true), beamMat); cone.geometry.translate(0, -70, 0); cone.geometry.rotateX(Math.PI / 2 * s * -1); cone.scale.set(1, 1, 1); beam.add(cone);
    const spot = new THREE.SpotLight(0xfff0c0, 0, 160, 0.16, 0.6, 1.2); spot.position.set(0, 0, 0); spot.target.position.set(0, 0, 60 * s); beam.add(spot, spot.target); beam.userData['spot' + s] = spot; }
  const orb = new THREE.Mesh(new THREE.SphereGeometry(0.28, 14, 10), new THREE.MeshBasicMaterial({ color: 0xfff1b0 })), orbLight = new THREE.PointLight(0xffe9a0, 0, 7, 1.5); orb.visible = false; orb.add(orbLight); g.add(orb);
  return { group: g, interior, walls, floors, beam, beamMat, lampMat, lampLight, vane, flag, orb, orbLight, plinth };
}
