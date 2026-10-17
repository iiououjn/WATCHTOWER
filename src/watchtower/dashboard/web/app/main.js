import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { EffectComposer } from 'three/addons/postprocessing/EffectComposer.js';
import { RenderPass } from 'three/addons/postprocessing/RenderPass.js';
import { UnrealBloomPass } from 'three/addons/postprocessing/UnrealBloomPass.js';
import { OutputPass } from 'three/addons/postprocessing/OutputPass.js';
import { FLOORS, PLACE_HOUR, PLACE_VIEW, activity, rosterByFloor, addressOf, daylight, lerp, clamp } from './logic.js';
import { labelSprite, disposeTree } from './util.js';
import { createSky } from './sky.js';
import { createWater } from './water.js';
import { buildTower, buildIsland, buildCottage, floorY, radiusAt, TOP_Y, BASE_Y, WALL } from './tower.js';
import { buildOffice, animateOffice, FLOOR_H } from './offices.js';
import { createPerson, updatePerson } from './people.js';
import { createEnv } from './envs.js';
import { createHud } from './hud.js';

const WT = window.WT, root = document.getElementById('stage'), hudRoot = document.getElementById('hud');
let renderer;
try { renderer = new THREE.WebGLRenderer({ antialias: true, powerPreference: 'high-performance' }); } catch (e) { renderer = null; }
if (!renderer) { hudRoot.textContent = '3D view needs WebGL, which this browser has turned off. The ledger (top right) still works.'; throw new Error('no webgl'); }
renderer.setPixelRatio(Math.min(devicePixelRatio || 1, 1.5)); renderer.setSize(innerWidth, innerHeight);
renderer.toneMapping = THREE.ACESFilmicToneMapping; renderer.shadowMap.enabled = true; renderer.shadowMap.type = THREE.PCFSoftShadowMap; renderer.outputColorSpace = THREE.SRGBColorSpace;
root.append(renderer.domElement);

const scene = new THREE.Scene(), camera = new THREE.PerspectiveCamera(52, innerWidth / innerHeight, 0.4, 70000);
camera.position.set(30, 12, 40);
const controls = new OrbitControls(camera, renderer.domElement);
Object.assign(controls, { enableDamping: true, dampingFactor: 0.07, minDistance: 7, maxDistance: 190, maxPolarAngle: 1.66, autoRotateSpeed: 0.8, rotateSpeed: 0.7, zoomSpeed: 0.8 });
controls.target.set(0, 18, 0);
const composer = new EffectComposer(renderer), bloom = new UnrealBloomPass(new THREE.Vector2(innerWidth, innerHeight), 0.55, 0.6, 2.4);
composer.addPass(new RenderPass(scene, camera)); composer.addPass(bloom); composer.addPass(new OutputPass());

const sky = createSky(scene, renderer), water = createWater(scene);
const island = buildIsland(), tower = buildTower(), cottage = buildCottage(); cottage.position.set(Math.sin(2.35) * 10.4, BASE_Y, Math.cos(2.35) * 10.4); cottage.rotation.y = 2.35 + Math.PI;
scene.add(island, tower.group, cottage);

// ---- the staff and their offices
const byFloor = rosterByFloor(WT.roster), offices = [], people = [], hits = [];
FLOORS.forEach((key, k) => {
  const y0 = floorY(k), ri = radiusAt(y0 + 1.5) - WALL - 0.55, off = buildOffice(key, ri); off.group.position.y = y0; off.group.userData.floor = k; tower.interior.add(off.group); offices.push(off);
  byFloor[key].forEach((role, i) => {
    const P = createPerson(role, k * 7 + i), seat = off.seats[i % off.seats.length]; P.seat = seat; P.floorIndex = k;
    const start = off.points[(i * 3) % off.points.length] || seat.pos; P.group.position.copy(start); off.group.add(P.group); people.push({ P, off }); hits.push(P.hit);
  });
});

// ---- boats for deployed apps
const boats = new Map();
function syncBoats(deps) {
  const keep = new Set();
  deps.slice(0, 8).forEach((d) => {
    const key = d.name + ':' + d.port; keep.add(key); if (boats.has(key)) return;
    const used = new Set([...boats.values()].map((x) => x.userData.slot)); let slot = 0; while (used.has(slot)) slot++;   // the first free mooring, so a new boat never sits on an old one
    const b = new THREE.Group(), hull = new THREE.Mesh(new THREE.BoxGeometry(2.6, 0.8, 1.1), new THREE.MeshStandardMaterial({ color: 0x3b2a22, roughness: 0.7 }));
    hull.position.y = 0.2; hull.castShadow = true; b.add(hull);
    const bow = new THREE.Mesh(new THREE.ConeGeometry(0.55, 1.2, 4), hull.material); bow.rotation.z = -Math.PI / 2; bow.rotation.x = Math.PI / 4; bow.position.set(1.8, 0.2, 0); b.add(bow);
    const mast = new THREE.Mesh(new THREE.CylinderGeometry(0.04, 0.05, 3.6, 6), new THREE.MeshStandardMaterial({ color: 0x2a2018 })); mast.position.y = 2.3; b.add(mast);
    const sail = new THREE.Mesh(new THREE.PlaneGeometry(1.8, 2.8), new THREE.MeshStandardMaterial({ color: 0xece5d4, side: THREE.DoubleSide, roughness: 0.9 })); sail.position.set(0.1, 2.2, 0); sail.rotation.y = Math.PI / 2; sail.castShadow = true; b.add(sail);
    const lamp = new THREE.Mesh(new THREE.SphereGeometry(0.16, 8, 6), new THREE.MeshBasicMaterial({ color: new THREE.Color(5, 3.4, 1.4) })); lamp.position.set(-1.2, 1.3, 0); b.add(lamp);   // a glowing bulb, not a real light: lights are costly and changing their count rebuilds every shader
    const n = labelSprite(d.name.slice(0, 16), 44, 1.1), a = labelSprite(addressOf(d), 205, 1.1); n.position.y = 5.4; a.position.y = 4.7; b.add(n, a);
    const ang = 0.55 + slot * 0.62, rad = 36 + (slot % 3) * 7; b.position.set(Math.sin(ang) * rad, 0, Math.cos(ang) * rad); b.userData = { ang, rad, lamp, slot, phase: slot * 1.7 }; scene.add(b); boats.set(key, b);
  });
  for (const [k, b] of boats) if (!keep.has(k)) { scene.remove(b); disposeTree(b); boats.delete(k); }
}

// ---- state, places, time
let photoLoad = 0, swing = null, env = null, place = 'ocean', manual = null, live = true, wasLit = new Map(), packet = null, running = false, focus = null, floorSel = -1;
let act = { awake: new Set(), lit: new Set(), floorOf: new Map() }, photoTex = null, photoName = '';
const hud = createHud(hudRoot, {
  place: (id) => setPlace(id), hour: (h) => { manual = h; live = false; hud.setHour(h, false); },
  floor: (k) => focusFloor(k), toggle: (key, on) => { if (key === 'spin') controls.autoRotate = on; if (key === 'bloom') bloom.enabled = on; if (key === 'live') { if (on) { live = true; manual = null; } else { manual = hourNow(); live = false; hud.setHour(manual, false); } } if (key === 'fx') fx = on; },
});
let fx = true, awakeBy = FLOORS.map(() => 0);
const hourNow = () => { if (manual !== null) return manual; const d = new Date(); return d.getHours() + d.getMinutes() / 60; };

function setPlace(id) {
  if (env) { scene.remove(env.group); env.dispose && env.dispose(); disposeTree(env.group); env = null; }
  photoLoad++; if (photoTex) { photoTex.dispose(); photoTex = null; }
  scene.background = null; scene.userData.photo = false; sky.restoreEnv(); sky.sky.visible = sky.clouds.visible = true; place = id; hud.setPlace(id);
  if (id.startsWith('photo:')) {
    const mine = photoLoad; photoName = id.slice(6); env = createEnv('ocean', { scene }); scene.add(env.group);
    new THREE.TextureLoader().load('backdrops/' + encodeURIComponent(photoName), (t) => {
      if (place !== id || mine !== photoLoad) { t.dispose(); return; }
      if (t.image && t.image.width > 8192) { t.dispose(); hud.note('that photo is wider than 8192 px; please use a smaller one'); return; }
      t.mapping = THREE.EquirectangularReflectionMapping; t.colorSpace = THREE.SRGBColorSpace; scene.background = t; scene.environment = t; scene.userData.photo = true; sky.sky.visible = sky.clouds.visible = sky.stars.visible = sky.moon.visible = false; photoTex = t;
    }, undefined, () => hud.note('could not load that photo'));
  } else { env = createEnv(id, { scene }); scene.add(env.group); }
  const off = camera.position.clone().sub(controls.target), az0 = Math.atan2(off.x, off.z), want = (PLACE_VIEW[id] ?? 0) + Math.PI;
  swing = { t0: performance.now(), from: az0, delta: Math.atan2(Math.sin(want - az0), Math.cos(want - az0)) };
  if (live === false && manual === null) { manual = PLACE_HOUR[id] ?? 17.5; hud.setHour(manual, false); }
}
function focusFloor(k) {
  floorSel = k; hud.setFloor(k);
  const from = { t: controls.target.clone(), d: camera.position.distanceTo(controls.target), p: camera.position.clone() }, y = k < 0 ? 15 : floorY(k) + 1.7, dist = k < 0 ? 52 : 15.5;
  focus = { t0: performance.now(), from, to: new THREE.Vector3(0, y, 0), dist };
}
if (!window.WT_DEMO_STATE) fetch('api/backdrops', { headers: { 'X-Watchtower': '1' }, cache: 'no-store' }).then((r) => r.json()).then((n) => hud.setBackdrops(n)).catch(() => {});

function onState(s) {
  act = activity(s); running = s.jobs.some((j) => j.status === 'running'); hud.setState(s, act.awake.size);
  act.floorOf.forEach((fl, id) => { const was = wasLit.get(id); if (was && was !== fl) packet = { from: FLOORS.indexOf(was), to: FLOORS.indexOf(fl), t: 0 }; wasLit.set(id, fl); });
  awakeBy = FLOORS.map((f) => { const pre = f === 'csuite' ? ['ceo', 'cto', 'cpo'] : [f + '.']; return [...act.awake].filter((id) => pre.some((p) => id === p || id.startsWith(p))).length; });
  syncBoats(s.deployments || []);
}
WT.listeners.push(onState); if (WT.state) onState(WT.state);
setPlace('ocean'); hud.setHour(hourNow(), true);

// ---- pointer: hover a person, click a floor
const ray = new THREE.Raycaster(), ptr = new THREE.Vector2(); let ptrXY = { x: -1, y: -1 }, hover = null, downAt = null;
renderer.domElement.addEventListener('pointermove', (e) => { ptrXY = { x: e.clientX, y: e.clientY }; });
renderer.domElement.addEventListener('pointerleave', () => { ptrXY = { x: -1, y: -1 }; });
renderer.domElement.addEventListener('pointerdown', (e) => { downAt = { x: e.clientX, y: e.clientY }; });
renderer.domElement.addEventListener('pointerup', (e) => {
  if (!downAt || Math.hypot(e.clientX - downAt.x, e.clientY - downAt.y) > 4) return;
  ptr.set((e.clientX / innerWidth) * 2 - 1, -(e.clientY / innerHeight) * 2 + 1); ray.setFromCamera(ptr, camera);
  const hit = ray.intersectObjects([tower.interior, tower.walls], true)[0]; if (!hit) return;
  let o = hit.object, k = -1; while (o && k < 0) { if (o.userData && o.userData.floor !== undefined) k = o.userData.floor; o = o.parent; }
  if (k < 0) k = FLOORS.findIndex((f, i) => hit.point.y >= floorY(i) - 0.3 && hit.point.y < floorY(i) + FLOOR_H - 0.3);
  if (k >= 0) focusFloor(k);
});
addEventListener('resize', () => { camera.aspect = innerWidth / innerHeight; camera.updateProjectionMatrix(); renderer.setSize(innerWidth, innerHeight); composer.setSize(innerWidth, innerHeight); });

// ---- the loop
const clock = new THREE.Clock(); let T = 0; const tmpV = new THREE.Vector3();
function frame() {
  requestAnimationFrame(frame);
  const dt = Math.min(0.05, clock.getDelta()); T += dt;
  try {
    const hour = hourNow(); if (live) hud.setHour(hour, true);
    if (focus) { const u = clamp((performance.now() - focus.t0) / 900, 0, 1), e = u * u * (3 - 2 * u); controls.target.lerpVectors(focus.from.t, focus.to, e); const dir = tmpV.copy(focus.from.p).sub(focus.from.t).setLength(lerp(focus.from.d, focus.dist, e)); camera.position.copy(controls.target).add(dir); if (u >= 1) focus = null; }
    if (swing) { const u = clamp((performance.now() - swing.t0) / 1400, 0, 1), e = u * u * (3 - 2 * u), off = camera.position.clone().sub(controls.target), hd = Math.hypot(off.x, off.z), az = swing.from + swing.delta * e; camera.position.set(controls.target.x + Math.sin(az) * hd, camera.position.y, controls.target.z + Math.cos(az) * hd); if (u >= 1) swing = null; }
    controls.update();
    const p = env ? env.params : { turbidity: 6, rayleigh: 1.2, mie: 0.005, cover: 0.5, soft: 0.3, fog: 0xa6bfdc, fogDensity: 0.00045, exposure: 1, water: 0x0a3a52 };
    const s = sky.update(hour, p, T, camera.position); const dl = s.dl;
    water.update(T, s.sunDir, p.water, dl); if (env && env.update) env.update(dt, T, { dl, sunDir: s.sunDir, el: s.el, fx, running, awake: act.awake.size, cam: camera.position });
    tower.walls.rotation.y = Math.atan2(camera.position.x, camera.position.z);
    tower.beam.rotation.y += dt * (running ? 0.9 : 0.35); const night = 1 - dl;
    tower.beamMat.uniforms.uI.value = (0.06 + 0.5 * night) * (running ? 1.25 : 0.7); tower.beam.userData.spot1.intensity = tower.beam.userData['spot-1'].intensity = night * (running ? 900 : 380);
    tower.lampMat.emissiveIntensity = (running ? 4.2 : 2.2) * (0.7 + 0.3 * Math.sin(T * 5)); tower.lampLight.intensity = 14 + 60 * night; tower.vane.rotation.y = Math.sin(T * 0.4) * 0.6 + 0.8;
    tower.flag.material.color.set(window.WT.state && window.WT.state.chain_ok === false ? 0xf87171 : 0x4ade80);
    tower.floors.forEach((fl, k) => { const on = act.lit.has(fl.key); fl.rimGlow.material.emissiveIntensity += ((on ? 3 : 0) - fl.rimGlow.material.emissiveIntensity) * 0.08; fl.windows.forEach((m) => { m.emissiveIntensity += (((on ? 3.6 : 0.4) * (0.35 + 0.65 * night)) - m.emissiveIntensity) * 0.06; }); });
    offices.forEach((o, k) => animateOffice(o, T, act.lit.has(FLOORS[k]), awakeBy[k]));
    people.forEach(({ P, off }) => updatePerson(P, dt, T, act.awake.has(P.role.id), off.points));
    cottage.userData.update(dt, T, act.awake.size > 0);
    for (const b of boats.values()) { const u = b.userData; b.position.y = Math.sin(T * 1.2 + u.phase) * 0.18 - 0.05; b.rotation.z = Math.sin(T * 0.9 + u.phase) * 0.04; b.rotation.y = u.ang + Math.PI / 2 + Math.sin(T * 0.2 + u.phase) * 0.1; u.lamp.visible = night > 0.25; }
    if (packet) { packet.t += dt * 0.55; const a = floorY(packet.from) + 1.6, c = floorY(packet.to) + 1.6, e = clamp(packet.t, 0, 1), k = e * e * (3 - 2 * e); tower.orb.visible = true; tower.orb.position.set(0, a + (c - a) * k + Math.sin(T * 9) * 0.05, 0); tower.orbLight.intensity = 12; if (packet.t > 1.25) { packet = null; tower.orb.visible = false; } }
    ray.setFromCamera(ptr.set((ptrXY.x / innerWidth) * 2 - 1, -(ptrXY.y / innerHeight) * 2 + 1), camera);
    const h = ptrXY.x < 0 ? null : (ray.intersectObjects(hits, false)[0] || {}).object; const hp = h ? h.userData.person : null;
    if (hp !== hover) { if (hover) hover.hover = false; hover = hp; if (hover) hover.hover = true; }
    hud.tooltip(ptrXY.x, ptrXY.y, hover, hover && act.awake.has(hover.role.id));
    composer.render();
  } catch (e) { WT.errors = (WT.errors || 0) + 1; if (!frame.failed) { frame.failed = true; console.error('watchtower 3d:', e); hud.note('3D view error: ' + (e && e.message)); } }
}
frame();
window.WT.debug = { scene, camera, controls, setPlace, focusFloor, renderer, bloom, sky, tower, water, people, offices };
