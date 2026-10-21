import * as THREE from 'three';
import { VRButton } from 'three/addons/webxr/VRButton.js';
import { DroneRig, nextDrone } from './rig.js';
import { grabToBuilding } from './editor-logic.js';
import { threeToSim } from './coords.js';

// WebXR mode (P11): enter VR, ride any drone (smoothed rig), grab and move buildings with a controller.
// The controller-grab pattern follows the three.js example `webxr_xr_dragging` (MIT):
// raycast from the controller on selectstart, controller.attach(object), scene.attach(object) on selectend.
export function setupXR({ renderer, scene, camera, world, drones, net, toast, getSnapshot, slot, onRide }) {
  renderer.xr.enabled = true;
  renderer.xr.setReferenceSpaceType('local-floor');
  const button = VRButton.createButton(renderer);
  slot.appendChild(button);

  const rig = new THREE.Group();            // dolly: the camera lives inside it (identity on desktop)
  rig.add(camera); scene.add(rig);
  const droneRig = new DroneRig();
  const state = { inXR: false, index: 0, controllers: [] };
  const raycaster = new THREE.Raycaster(); const tmpM = new THREE.Matrix4();

  renderer.xr.addEventListener('sessionstart', () => { state.inXR = true; droneRig.select(state.index); onRide?.(state.index); });
  renderer.xr.addEventListener('sessionend', () => {
    state.inXR = false; rig.position.set(0, 0, 0); rig.rotation.set(0, 0, 0); camera.position.set(0, 0, 0);
  });

  const ray = new THREE.Line(new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(), new THREE.Vector3(0, 0, -1)]),
                             new THREE.LineBasicMaterial({ color: 0x4aa8ff }));
  ray.scale.z = 30;

  const cycle = (dir) => {
    const s = getSnapshot(); if (!s) return;
    const active = Array.from(s.droneState, (v) => (v & 7) === 1 || (v & 7) === 3 || (v & 7) === 2);
    state.index = nextDrone(state.index, s.nDrones, dir, active);
    droneRig.select(state.index); onRide?.(state.index);
  };

  for (let i = 0; i < 2; i++) {
    const c = renderer.xr.getController(i);
    c.add(ray.clone());
    c.addEventListener('connected', (e) => { c.userData.handedness = e.data.handedness; });
    c.addEventListener('squeezestart', () => cycle(c.userData.handedness === 'left' ? -1 : +1));
    c.addEventListener('selectstart', () => {
      tmpM.identity().extractRotation(c.matrixWorld);
      raycaster.ray.origin.setFromMatrixPosition(c.matrixWorld);
      raycaster.ray.direction.set(0, 0, -1).applyMatrix4(tmpM);
      const hit = raycaster.intersectObjects(world.meshes, false)[0];
      if (hit) { c.attach(hit.object); c.userData.selected = hit.object; }
    });
    c.addEventListener('selectend', async () => {
      const obj = c.userData.selected; if (!obj) return;
      scene.attach(obj); c.userData.selected = undefined;
      obj.position.y = 0; obj.rotation.set(0, 0, 0); obj.updateMatrixWorld(true);
      const cur = world.serverBuilding(obj.userData.id);
      const next = grabToBuilding(cur, obj.position.toArray());
      const ack = await net.send('edit_building', { building: next });
      if (!ack.ok) { toast(`Edit rejected: ${ack.reason}`, 'error'); world.applyBuilding(obj, cur); }
      else world.applyBuilding(obj, next);
    });
    rig.add(c);                             // controllers move with the rig
    state.controllers.push(c);
  }

  // called every frame from the render loop
  function update(dt, nowS, snapAgeS) {
    if (!state.inXR) return;
    const s = getSnapshot(); if (!s || s.nDrones === 0) return;
    const i = Math.min(state.index, s.nDrones - 1);
    const out = droneRig.update(dt, drones.position(s, i, snapAgeS), drones.velocity(s, i));
    rig.position.set(...out.position); rig.rotation.set(0, out.heading, 0);
  }

  return { rig, state, update, cycle, button, simPos: (obj) => threeToSim(...obj.position.toArray()) };
}
