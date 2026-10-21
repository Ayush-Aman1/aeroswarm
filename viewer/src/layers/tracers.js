import * as THREE from 'three';
import { buildLut } from '../colormap.js';
import { simToThree } from '../coords.js';

// 8k tracers: a Points head plus a fading trail made of the last K snapshot positions (LineSegments).
// The trail shader fades alpha with age and colours by speed through the viridis LUT. Idea after the
// fading particle trails of https://github.com/mapbox/webgl-wind (ISC); the implementation is original.
const K = 8, JUMP_M = 15, VMAX = 14;

export class Tracers {
  constructor() {
    this.group = new THREE.Group();
    const lut = new THREE.DataTexture(buildLut(), 256, 1, THREE.RGBAFormat);
    lut.colorSpace = THREE.SRGBColorSpace; lut.minFilter = lut.magFilter = THREE.LinearFilter; lut.needsUpdate = true;
    this.lut = lut;
    this.n = 0; this.lastTime = null;
  }

  _alloc(n) {
    this.group.clear();
    this.n = n;
    this.hist = new Float32Array(K * n * 3);
    this.speed = new Float32Array(n);
    this.initialised = false;
    const uniforms = { uLut: { value: this.lut }, uVmax: { value: VMAX }, uSize: { value: 2.2 }, uScale: { value: 400 } };
    this.uniforms = uniforms;
    const common = `uniform sampler2D uLut; uniform float uVmax;`;
    // trail
    const segs = n * (K - 1) * 2;
    this.linePos = new Float32Array(segs * 3);
    this.lineAge = new Float32Array(segs);
    this.lineSpeed = new Float32Array(segs);
    for (let k = 0; k < K - 1; k++) for (let i = 0; i < n; i++) {
      const v = (k * n + i) * 2;
      this.lineAge[v] = k / (K - 1); this.lineAge[v + 1] = (k + 1) / (K - 1);
    }
    const lg = new THREE.BufferGeometry();
    lg.setAttribute('position', new THREE.BufferAttribute(this.linePos, 3).setUsage(THREE.DynamicDrawUsage));
    lg.setAttribute('age', new THREE.BufferAttribute(this.lineAge, 1));
    lg.setAttribute('speed', new THREE.BufferAttribute(this.lineSpeed, 1).setUsage(THREE.DynamicDrawUsage));
    const lm = new THREE.ShaderMaterial({
      uniforms, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
      vertexShader: `attribute float age; attribute float speed; varying float vAge; varying float vSpeed;
        void main(){ vAge = age; vSpeed = speed; gl_Position = projectionMatrix * modelViewMatrix * vec4(position,1.0); }`,
      fragmentShader: `${common} varying float vAge; varying float vSpeed;
        void main(){ vec3 c = texture2D(uLut, vec2(clamp(vSpeed / uVmax, 0.0, 1.0), 0.5)).rgb;
          gl_FragColor = vec4(c, 0.55 * pow(1.0 - vAge, 1.6));
          #include <colorspace_fragment>
        }`,
    });
    this.trail = new THREE.LineSegments(lg, lm);
    this.trail.frustumCulled = false;
    // heads
    this.headPos = new Float32Array(n * 3);
    const pg = new THREE.BufferGeometry();
    pg.setAttribute('position', new THREE.BufferAttribute(this.headPos, 3).setUsage(THREE.DynamicDrawUsage));
    pg.setAttribute('speed', new THREE.BufferAttribute(this.speed, 1).setUsage(THREE.DynamicDrawUsage));
    const pm = new THREE.ShaderMaterial({
      uniforms, transparent: true, depthWrite: false,
      vertexShader: `attribute float speed; uniform float uSize; uniform float uScale; varying float vSpeed;
        void main(){ vSpeed = speed; vec4 mv = modelViewMatrix * vec4(position,1.0);
          gl_PointSize = clamp(uSize * uScale / -mv.z, 1.0, 5.0); gl_Position = projectionMatrix * mv; }`,
      fragmentShader: `${common} varying float vSpeed;
        void main(){ vec2 d = gl_PointCoord - 0.5; if (dot(d,d) > 0.25) discard;
          vec3 c = texture2D(uLut, vec2(clamp(vSpeed / uVmax, 0.0, 1.0), 0.5)).rgb;
          gl_FragColor = vec4(c, 0.95);
          #include <colorspace_fragment>
        }`,
    });
    this.points = new THREE.Points(pg, pm);
    this.points.frustumCulled = false;
    this.group.add(this.trail, this.points);
  }

  setTrailsVisible(v) { if (this.trail) this.trail.visible = v; }

  update(snap) {
    const n = snap.nTracers;
    if (n === 0) { this.group.visible = false; return; }
    if (n !== this.n) this._alloc(n);
    const dt = this.lastTime == null ? 0 : snap.simTime - this.lastTime;
    this.lastTime = snap.simTime;
    const row = n * 3;
    this.hist.copyWithin(row, 0, row * (K - 1));            // shift history by one frame
    const h = this.hist, src = snap.tracers;
    for (let i = 0; i < n; i++) {
      const [x, y, z] = simToThree(src[i * 3], src[i * 3 + 1], src[i * 3 + 2]);
      const a = i * 3;
      let jumped = !this.initialised;
      if (!jumped) {
        const dx = x - h[row + a], dy = y - h[row + a + 1], dz = z - h[row + a + 2];
        const d = Math.hypot(dx, dy, dz);
        if (d > JUMP_M) jumped = true;
        else if (dt > 0) this.speed[i] += (d / dt - this.speed[i]) * 0.3;       // smoothed ground speed
      }
      h[a] = x; h[a + 1] = y; h[a + 2] = z;
      if (jumped) { for (let k = 1; k < K; k++) { const b = k * row + a; h[b] = x; h[b + 1] = y; h[b + 2] = z; } this.speed[i] = 0; }
      this.headPos[a] = x; this.headPos[a + 1] = y; this.headPos[a + 2] = z;
    }
    this.initialised = true;
    for (let k = 0; k < K - 1; k++) for (let i = 0; i < n; i++) {
      const v = (k * n + i) * 2;
      const p0 = k * row + i * 3, p1 = (k + 1) * row + i * 3;
      const o = v * 3;
      this.linePos[o] = h[p0]; this.linePos[o + 1] = h[p0 + 1]; this.linePos[o + 2] = h[p0 + 2];
      this.linePos[o + 3] = h[p1]; this.linePos[o + 4] = h[p1 + 1]; this.linePos[o + 5] = h[p1 + 2];
      this.lineSpeed[v] = this.lineSpeed[v + 1] = this.speed[i];
    }
    for (const g of [this.trail.geometry, this.points.geometry]) for (const a of Object.values(g.attributes)) a.needsUpdate = true;
    this.group.visible = true;
  }
}
