import * as THREE from 'three';
import { Water } from 'three/addons/objects/Water.js';
import { canvasTexture, fbm } from './util.js';

export function createWater(scene) {
  const normals = canvasTexture(512, 512, (g, w, h) => {      // tileable wave normal map made from noise heights
    const img = g.createImageData(w, h), H = (x, y) => fbm((x / w) * 8 + 0.5, (y / h) * 8 + 0.5, 3, 4) + 0.5 * fbm((x / w) * 24, (y / h) * 24, 9, 3);
    for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
      const dx = H(x + 1, y) - H(x - 1, y), dy = H(x, y + 1) - H(x, y - 1), nx = -dx * 5, ny = -dy * 5, l = Math.hypot(nx, ny, 1), i = (y * w + x) * 4;
      img.data[i] = (nx / l * 0.5 + 0.5) * 255; img.data[i + 1] = (ny / l * 0.5 + 0.5) * 255; img.data[i + 2] = (1 / l * 0.5 + 0.5) * 255; img.data[i + 3] = 255;
    }
    g.putImageData(img, 0, 0);
  }, { linear: true });
  normals.wrapS = normals.wrapT = THREE.RepeatWrapping;
  const water = new Water(new THREE.PlaneGeometry(40000, 40000), {
    textureWidth: 512, textureHeight: 512, waterNormals: normals, sunDirection: new THREE.Vector3(0, 1, 0), sunColor: 0xffffff, waterColor: 0x0a3a52, distortionScale: 1.6, fog: true, alpha: 1,
  });
  water.rotation.x = -Math.PI / 2; water.position.y = 0; water.material.uniforms.size.value = 0.9; scene.add(water);
  return {
    mesh: water,
    update(t, sunDir, color, dl) {
      const u = water.material.uniforms; u.time.value = t * 0.55; u.sunDirection.value.copy(sunDir); u.waterColor.value.set(color).multiplyScalar(0.25 + 0.75 * dl);
      u.sunColor.value.setScalar(0.25 + 0.9 * dl);
    },
  };
}
