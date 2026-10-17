import * as THREE from 'three';
import { Sky } from 'three/addons/objects/Sky.js';
import { daylight, sunElevation, sunAzimuth, lerp, clamp, smooth } from './logic.js';
import { rng, canvasTexture } from './util.js';

const CLOUD_VERT = `varying vec3 vP; void main(){ vP = (modelMatrix * vec4(position,1.)).xyz; gl_Position = projectionMatrix * viewMatrix * vec4(vP,1.); }`;
const CLOUD_FRAG = `
uniform float uTime, uCover, uSoft; uniform vec3 uLit, uShade, uCam; uniform vec3 uSun;
varying vec3 vP;
float h(vec2 p){ return fract(sin(dot(p, vec2(127.1,311.7))) * 43758.5453); }
float n(vec2 p){ vec2 i = floor(p), f = fract(p); f = f*f*(3.-2.*f); return mix(mix(h(i),h(i+vec2(1,0)),f.x), mix(h(i+vec2(0,1)),h(i+vec2(1,1)),f.x), f.y); }
float fbm(vec2 p){ float a = .5, s = 0.; for(int i=0;i<6;i++){ s += a*n(p); p = p*2.02 + 11.7; a *= .5; } return s; }
void main(){
  vec3 d = vP - uCam; float dist = length(d.xz); vec2 uv = vP.xz * 0.00028 + vec2(uTime * 0.004, uTime * 0.0016);
  float base = fbm(uv * 1.3), detail = fbm(uv * 5.5 + base * 2.);
  float th = .92 - uCover * .62; float c = smoothstep(th, th + uSoft, base * .75 + detail * .45);
  float fade = 1. - smoothstep(2500., 13000., dist);                       // thin out toward the horizon
  vec2 off = uSun.xz * 0.0009; float lit = fbm((uv + off) * 5.5 + base * 2.);   // sun-side edges are brighter
  float shade = clamp((detail - lit) * 3. + .5, 0., 1.);
  vec3 col = mix(uLit, uShade, shade * .85);
  gl_FragColor = vec4(col, c * fade * .92);
}`;

export function createSky(scene, renderer) {
  const sky = new Sky(); sky.scale.setScalar(30000); scene.add(sky);
  sky.material.onBeforeCompile = (sh) => { sh.fragmentShader = sh.fragmentShader.replace('gl_FragColor = vec4( texColor, 1.0 );', 'gl_FragColor = vec4( min( texColor * 0.38, vec3( 1.8 ) ), 1.0 );'); };   // keep the sky out of the bloom
  const su = sky.material.uniforms;
  const sunDir = new THREE.Vector3(), moonDir = new THREE.Vector3();

  const clouds = new THREE.Mesh(new THREE.PlaneGeometry(60000, 60000, 1, 1).rotateX(-Math.PI / 2), new THREE.ShaderMaterial({
    vertexShader: CLOUD_VERT, fragmentShader: CLOUD_FRAG, transparent: true, depthWrite: false, fog: false,
    uniforms: { uTime: { value: 0 }, uCover: { value: 0.5 }, uSoft: { value: 0.3 }, uLit: { value: new THREE.Color(1, 1, 1) }, uShade: { value: new THREE.Color(0.55, 0.6, 0.72) }, uSun: { value: new THREE.Vector3() }, uCam: { value: new THREE.Vector3() } },
  }));
  clouds.position.y = 2600; clouds.renderOrder = -1; scene.add(clouds);

  const r = rng(11), sp = new Float32Array(2600 * 3), sc = new Float32Array(2600 * 3);
  for (let i = 0; i < 2600; i++) {
    const u = r() * 2 - 1, th = r() * Math.PI * 2, rr = Math.sqrt(1 - u * u), b = 0.45 + r() * 0.55;
    sp.set([rr * Math.cos(th) * 20000, Math.abs(u) * 20000 + 200, rr * Math.sin(th) * 20000], i * 3); sc.set([b, b, b * (0.9 + r() * 0.1)], i * 3);
  }
  const sg = new THREE.BufferGeometry(); sg.setAttribute('position', new THREE.BufferAttribute(sp, 3)); sg.setAttribute('color', new THREE.BufferAttribute(sc, 3));
  const stars = new THREE.Points(sg, new THREE.PointsMaterial({ size: 2.6, sizeAttenuation: false, vertexColors: true, transparent: true, depthWrite: false, fog: false }));
  scene.add(stars);

  const moonTex = canvasTexture(256, 256, (g, w, h) => {
    const gr = g.createRadialGradient(w / 2, h / 2, 10, w / 2, h / 2, w / 2); gr.addColorStop(0, 'rgba(255,250,235,1)'); gr.addColorStop(0.28, 'rgba(255,248,225,1)'); gr.addColorStop(0.3, 'rgba(255,248,225,.35)'); gr.addColorStop(1, 'rgba(255,248,225,0)');
    g.fillStyle = gr; g.fillRect(0, 0, w, h); g.fillStyle = 'rgba(170,160,140,.35)'; [[-18, -10, 14], [14, 12, 10], [8, -22, 8], [-6, 20, 9]].forEach(([x, y, rad]) => { g.beginPath(); g.arc(w / 2 + x, h / 2 + y, rad, 0, 6.3); g.fill(); });
  });
  const moon = new THREE.Sprite(new THREE.SpriteMaterial({ map: moonTex, transparent: true, depthWrite: false, fog: false })); moon.scale.set(2400, 2400, 1); scene.add(moon);

  const pm = new THREE.PMREMGenerator(renderer), envScene = new THREE.Scene(), sky2 = new Sky(); sky2.scale.setScalar(30000); envScene.add(sky2); sky2.material.onBeforeCompile = sky.material.onBeforeCompile;
  let envRT = null, envKey = ''; scene.environmentIntensity = 0.6;
  function refreshEnv(sunPos, p, hour) {      // image-based light from the sky itself, so stone, wood and water pick up its colour
    const key = [Math.round(hour * 5), p.turbidity, p.rayleigh].join('|'); if (key === envKey) return; envKey = key;
    const u = sky2.material.uniforms; u.sunPosition.value.copy(sunPos); u.turbidity.value = su.turbidity.value; u.rayleigh.value = su.rayleigh.value; u.mieCoefficient.value = su.mieCoefficient.value; u.mieDirectionalG.value = su.mieDirectionalG.value;
    const old = envRT; envRT = pm.fromScene(envScene, 0, 1, 100000); if (!scene.userData.photo) scene.environment = envRT.texture; if (old) old.dispose();
  }
  const dir = new THREE.DirectionalLight(0xfff2dc, 3); dir.castShadow = true; dir.shadow.mapSize.set(2048, 2048);
  Object.assign(dir.shadow.camera, { left: -34, right: 34, top: 40, bottom: -22, near: 1, far: 300 }); dir.shadow.bias = -0.0004; dir.shadow.normalBias = 0.04;
  const moonLight = new THREE.DirectionalLight(0x8aa4ff, 0.3), hemi = new THREE.HemisphereLight(0xbcd6ff, 0x4a4032, 0.6);
  scene.add(dir, dir.target, moonLight, hemi); dir.target.position.set(0, 12, 0);
  scene.fog = new THREE.FogExp2(0x9fb8d6, 0.00045);

  const tmp = new THREE.Color(), warm = new THREE.Color(1, 0.55, 0.32), cA = new THREE.Color(), cB = new THREE.Color(), CP = [new THREE.Color(0xffc9a0), new THREE.Color(1, 0.62, 0.45), new THREE.Color(0.55, 0.35, 0.45), new THREE.Color(0xa6bfdc)];
  function update(hour, p, time, camPos) {
    const el = sunElevation(hour), az = sunAzimuth(hour), dl = daylight(hour), low = 1 - smooth(0, 22, Math.abs(el));
    sunDir.setFromSphericalCoords(1, THREE.MathUtils.degToRad(90 - el), THREE.MathUtils.degToRad(az));
    moonDir.copy(sunDir).multiplyScalar(-1); if (moonDir.y < 0.12) moonDir.y = 0.12 + (0.12 - moonDir.y) * 0.2; moonDir.normalize();
    su.sunPosition.value.copy(sunDir); su.turbidity.value = p.turbidity; su.rayleigh.value = p.rayleigh * (0.35 + 0.65 * dl) + 0.05; su.mieCoefficient.value = p.mie; su.mieDirectionalG.value = 0.82;
    dir.position.copy(sunDir).multiplyScalar(120).add(dir.target.position); dir.intensity = 2.4 * smooth(-4, 14, el); dir.color.copy(tmp.set(0xfff4e0).lerp(warm, low * 0.8));
    moonLight.position.copy(moonDir).multiplyScalar(100); moonLight.intensity = 0.3 * (1 - dl); if (!scene.userData.photo) scene.environmentIntensity = lerp(0.1, 0.6, dl);
    hemi.intensity = lerp(0.2, 0.6, dl); hemi.color.set(0x9ec0ff).lerp(CP[0], low * 0.5); hemi.groundColor.set(0x3a342c);
    stars.material.opacity = clamp(1.2 - dl * 1.8, 0, 1); stars.visible = stars.material.opacity > 0.01 && !scene.userData.photo; stars.rotation.y = time * 0.002;
    moon.position.copy(moonDir).multiplyScalar(18000); moon.material.opacity = clamp(1.4 - dl * 2.2, 0, 1); moon.visible = moon.material.opacity > 0.01 && !scene.userData.photo;
    const cu = clouds.material.uniforms; cu.uTime.value = time; cu.uCover.value = p.cover; cu.uSoft.value = p.soft; cu.uSun.value.copy(sunDir); cu.uCam.value.copy(camPos);
    cu.uLit.value.set(1, 1, 1).lerp(CP[1], low * 0.85).multiplyScalar(lerp(0.07, 1, dl));
    cu.uShade.value.set(0.52, 0.58, 0.72).lerp(CP[2], low * 0.7).multiplyScalar(lerp(0.05, 0.9, dl));
    clouds.position.x = camPos.x; clouds.position.z = camPos.z;
    const fog = scene.fog; fog.color.set(0x07091a).lerp(CP[3], smooth(-6, 14, el)).lerp(warm, low * 0.45 * smooth(-4, 8, el)).lerp(tmp.set(p.fog), 0.45); fog.density = p.fogDensity;
    refreshEnv(sunDir, p, hour);
    renderer.toneMappingExposure = lerp(0.95, 0.8, dl) * p.exposure;
    return { dl, el, sunDir, fogColor: fog.color };
  }
  return { update, sky, clouds, dir, hemi, sunDir, stars, moon, restoreEnv() { if (envRT) scene.environment = envRT.texture; } };
}
