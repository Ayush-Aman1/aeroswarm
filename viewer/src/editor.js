import * as THREE from 'three';
import { TransformControls } from 'three/addons/controls/TransformControls.js';
import { transformToBuilding, sameBuilding } from './editor-logic.js';

// Click a building, drag the gizmo (move x,y or scale w,d,h), release -> edit_building. On rejection the
// building snaps back to the server's layout and a toast shows the reason.
export class Editor {
  constructor({ camera, dom, scene, world, orbit, net, toast, onPending }) {
    this.world = world; this.net = net; this.toast = toast; this.orbit = orbit; this.dom = dom; this.camera = camera;
    this.onPending = onPending || (() => {});
    this.enabled = false; this.selected = null; this.pending = false; this.mode = 'translate';
    this.raycaster = new THREE.Raycaster(); this.pointer = new THREE.Vector2();
    this.tc = new TransformControls(camera, dom);
    this.tc.setTranslationSnap(1); this.tc.setScaleSnap(1);
    this.tc.showY = false;                                  // move on the ground plane only
    this.helper = this.tc.getHelper(); this.helper.visible = false;
    scene.add(this.helper);
    this.tc.addEventListener('dragging-changed', (e) => { orbit.enabled = !e.value; this.dragging = e.value; });
    this.tc.addEventListener('mouseUp', () => this.commit());
    this.tc.addEventListener('objectChange', () => this._clampWhileDragging());
    this._down = null;
    dom.addEventListener('pointerdown', (e) => { this._down = [e.clientX, e.clientY]; });
    dom.addEventListener('pointerup', (e) => {
      if (!this.enabled || !this._down || this.dragging) return;
      if (Math.hypot(e.clientX - this._down[0], e.clientY - this._down[1]) > 4) return;   // was an orbit drag
      this.pick(e);
    });
  }

  setEnabled(on) {
    this.enabled = on;
    if (!on) this.deselect();
  }

  setMode(mode) {                                           // 'translate' | 'scale'
    this.mode = mode; this.tc.setMode(mode);
    this.tc.showY = mode === 'scale';
  }

  pick(ev) {
    const r = this.dom.getBoundingClientRect();
    this.pointer.set(((ev.clientX - r.left) / r.width) * 2 - 1, -((ev.clientY - r.top) / r.height) * 2 + 1);
    this.raycaster.setFromCamera(this.pointer, this.camera);
    const hit = this.raycaster.intersectObjects(this.world.meshes, false)[0];
    if (hit && !this.pending) this.select(hit.object); else if (!hit) this.deselect();
  }

  select(mesh) {
    this.selected = mesh; this.world.select(mesh.userData.id);
    this.tc.attach(mesh); this.helper.visible = true;
  }

  deselect() {
    this.selected = null; this.tc.detach(); this.helper.visible = false; this.world.select(-1);
  }

  _clampWhileDragging() {
    const m = this.selected; if (!m) return;
    m.position.y = 0; m.rotation.set(0, 0, 0);
    for (const k of ['x', 'y', 'z']) m.scale[k] = Math.max(5, m.scale[k]);
  }

  async commit() {
    const m = this.selected; if (!m || this.pending) return;
    const id = m.userData.id;
    const next = transformToBuilding(id, m.position.toArray(), m.scale.toArray());
    const cur = this.world.serverBuilding(id);
    if (sameBuilding(next, cur)) { this.world.applyBuilding(m, cur); return; }
    this.pending = true; this.onPending(true);
    const ack = await this.net.send('edit_building', { building: next });
    if (!ack.ok) {
      this.toast(`Edit rejected: ${ack.reason}`, 'error');
      this.world.applyBuilding(m, cur);                      // snap back
      this.pending = false; this.onPending(false);
    } else {
      this.world.applyBuilding(m, next);                     // show it where it will be; layout msg confirms
      // pending stays true until the server reports `settling: false` / a new layout
    }
  }

  settled() { this.pending = false; this.onPending(false); }
}
