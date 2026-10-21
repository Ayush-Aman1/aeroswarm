import * as THREE from 'three';
import { mergeGeometries } from 'three/addons/utils/BufferGeometryUtils.js';
import { simToThree } from '../coords.js';
import { NEAR_BIT } from '../protocol.js';

// Two InstancedMesh (detailed near the camera, simple far away): one draw call per LOD level.
const LOD_DIST = 140;          // metres
const SCALE = 4.0;             // drones are drawn 4x life size so they are visible on a 400 m map
const STATE_COLORS = ['#8b98a8', '#4aa8ff', '#3ddc84', '#ffb340', '#4a5360'].map((c) => new THREE.Color(c));
const NEAR_COLOR = new THREE.Color('#ff3b3b');

function detailedGeometry() {
  const parts = [new THREE.BoxGeometry(0.7, 0.25, 0.7)];
  for (const ry of [Math.PI / 4, -Math.PI / 4]) {
    const arm = new THREE.BoxGeometry(2.0, 0.08, 0.14); arm.rotateY(ry); parts.push(arm);
  }
  for (const [x, z] of [[0.7, 0.7], [-0.7, 0.7], [0.7, -0.7], [-0.7, -0.7]]) {
    const r = new THREE.CylinderGeometry(0.42, 0.42, 0.04, 12); r.translate(x, 0.12, z); parts.push(r);
  }
  const nose = new THREE.ConeGeometry(0.15, 0.4, 6); nose.rotateX(-Math.PI / 2); nose.translate(0, 0, -0.55); parts.push(nose);
  return mergeGeometries(parts.map((g) => g.toNonIndexed()));
}

export class Drones {
  constructor(maxN = 20000) {
    this.group = new THREE.Group();
    this.mat = new THREE.MeshStandardMaterial({ roughness: 0.5, metalness: 0.2 });
    this.near = new THREE.InstancedMesh(detailedGeometry(), this.mat, maxN);
    this.far = new THREE.InstancedMesh(new THREE.OctahedronGeometry(1.1), this.mat, maxN);
    for (const m of [this.near, this.far]) {
      m.instanceMatrix.setUsage(THREE.DynamicDrawUsage);
      m.instanceColor = new THREE.InstancedBufferAttribute(new Float32Array(maxN * 3), 3);
      m.instanceColor.setUsage(THREE.DynamicDrawUsage);
      m.frustumCulled = false; m.count = 0;
      this.group.add(m);
    }
    this.maxN = maxN;
    this._m = new THREE.Matrix4(); this._q = new THREE.Quaternion(); this._qp = new THREE.Quaternion();
    this._p = new THREE.Vector3(); this._s = new THREE.Vector3(SCALE, SCALE, SCALE);
    this._yAxis = new THREE.Vector3(0, 1, 0); this._xAxis = new THREE.Vector3(1, 0, 0);
    this.counts = { near: 0, far: 0 };
  }

  // snap: decoded snapshot; ageS: seconds since it arrived (dead-reckoning with the sent velocity).
  update(snap, ageS, camPos, nowS) {
    if (!snap) return;
    const n = Math.min(snap.nDrones, this.maxN);
    const a = Math.min(ageS, 0.12);
    let nn = 0, nf = 0;
    const blink = Math.floor(nowS * 8) % 2 === 0;
    for (let i = 0; i < n; i++) {
      const o = i * 6, st = snap.droneState[i], phase = st & 7;
      const [px, py, pz] = simToThree(snap.dronePV[o] + snap.dronePV[o + 3] * a, snap.dronePV[o + 1] + snap.dronePV[o + 4] * a,
                                       snap.dronePV[o + 2] + snap.dronePV[o + 5] * a);
      const [vx, vy, vz] = simToThree(snap.dronePV[o + 3], snap.dronePV[o + 4], snap.dronePV[o + 5]);
      const near = Math.hypot(px - camPos.x, py - camPos.y, pz - camPos.z) < LOD_DIST;
      const sp = Math.hypot(vx, vz);
      this._p.set(px, py + 0.5, pz);
      this._q.setFromAxisAngle(this._yAxis, sp > 0.5 ? Math.atan2(-vx, -vz) : 0);
      this._qp.setFromAxisAngle(this._xAxis, -Math.min(sp / 12, 1.2) * 0.25);
      this._q.multiply(this._qp);
      this._m.compose(this._p, this._q, this._s);
      const mesh = near ? this.near : this.far;
      const idx = near ? nn++ : nf++;
      mesh.setMatrixAt(idx, this._m);
      const c = ((st & NEAR_BIT) && blink) ? NEAR_COLOR : STATE_COLORS[Math.min(phase, 4)];
      mesh.setColorAt(idx, c);
    }
    this.near.count = nn; this.far.count = nf;
    this.counts = { near: nn, far: nf };
    for (const m of [this.near, this.far]) { m.instanceMatrix.needsUpdate = true; m.instanceColor.needsUpdate = true; }
  }

  // world position of drone i in three.js coordinates (for the XR rig)
  position(snap, i, ageS = 0) {
    const o = i * 6, a = Math.min(ageS, 0.12);
    return simToThree(snap.dronePV[o] + snap.dronePV[o + 3] * a, snap.dronePV[o + 1] + snap.dronePV[o + 4] * a,
                      snap.dronePV[o + 2] + snap.dronePV[o + 5] * a);
  }

  velocity(snap, i) {
    const o = i * 6;
    return simToThree(snap.dronePV[o + 3], snap.dronePV[o + 4], snap.dronePV[o + 5]);
  }
}
