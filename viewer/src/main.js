import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { Net } from './net.js';
import { World } from './world.js';
import { Drones } from './layers/drones.js';
import { Tracers } from './layers/tracers.js';
import { WindSlice } from './layers/slice.js';
import { Editor } from './editor.js';
import { setupXR } from './xr.js';
import { toast, setConn, setBanner, updateHud, fillSelect } from './hud.js';

const $ = (id) => document.getElementById(id);
const canvas = $('view');
const renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
renderer.setClearColor(0x0e1116);
const scene = new THREE.Scene();
scene.fog = new THREE.Fog(0x0e1116, 900, 2600);
const camera = new THREE.PerspectiveCamera(55, 1, 1, 4000);
camera.position.set(200, 230, 330);
scene.add(new THREE.HemisphereLight(0xcfe3ff, 0x1b2430, 1.2));
const sun = new THREE.DirectionalLight(0xffffff, 1.6); sun.position.set(150, 300, 100); scene.add(sun);
const orbit = new OrbitControls(camera, canvas);
orbit.target.set(200, 0, -150); orbit.maxPolarAngle = Math.PI * 0.49; orbit.update();

const world = new World(scene);
const drones = new Drones();
const tracers = new Tracers();
let slice = null;
scene.add(drones.group, tracers.group);

let hello = null, snap = null, snapAt = 0, stats = null, snapCount = 0;
const viewFps = { v: 60, last: performance.now() };

const net = new Net({
  onStatus: (s) => setConn(s === 'connected', s),
  onMessage: (m) => {
    if (m.type === 'hello') onHello(m);
    else if (m.type === 'stats') { stats = m; setBanner(m.settling); if (!m.settling) editor.settled(); }
    else if (m.type === 'layout') { world.setLayout(m); hello.layout = m; hello.inflow = m.inflow; editor.settled(); setBanner(false); }
    else if (m.type === 'settling') setBanner(m.pending);
    else if (m.type === 'toast') toast(m.text, m.level);
  },
  onSnapshot: (s) => {
    snap = s; snapAt = performance.now() / 1000; snapCount++;
    slice?.update(s); tracers.update(s);
  },
});

const editor = new Editor({ camera, dom: canvas, scene, world, orbit, net, toast, onPending: (p) => { setBanner(p); } });
const xr = setupXR({ renderer, scene, camera, world, drones, net, toast, getSnapshot: () => snap, slot: $('xr-slot'),
                     onRide: (i) => toast(`riding drone ${i}`, 'info', 1500) });

function onHello(h) {
  hello = h;
  world.setHello(h);
  const [ax, ay] = h.layout.area_m;
  if (slice) scene.remove(slice.mesh);
  slice = new WindSlice(ax, ay); scene.add(slice.mesh); slice.mesh.visible = $('t-slice').checked;
  $('scn').textContent = `· ${h.scenario}`;
  fillSelect('tier', h.tiers_available, h.tier);
  fillSelect('scenario', h.scenarios, h.scenario);
  $('slice-z').value = h.slice_z; $('slice-val').textContent = `${h.slice_z} m`;
  orbit.target.set(ax / 2, 0, -ay / 2);
}

// ----- HUD wiring
$('route-naive').onclick = () => net.send('set_routing', { mode: 'naive' });
$('route-aware').onclick = () => net.send('set_routing', { mode: 'aware' });
$('tier').onchange = async (e) => { const a = await net.send('set_tier', { tier: e.target.value }); if (!a.ok) { toast(a.reason, 'error'); e.target.value = stats?.tier ?? 'synthetic'; } };
$('scenario').onchange = async (e) => { const a = await net.send('load_scenario', { name: e.target.value }); if (!a.ok) toast(a.reason, 'error'); };
$('btn-rotate').onclick = async () => {
  const cur = (stats?.inflow ?? hello?.inflow)?.direction_deg ?? 0;
  const a = await net.send('set_inflow', { direction_deg: (cur + 45) % 360 }); if (!a.ok) toast(a.reason, 'error');
};
$('btn-pause').onclick = () => net.send(stats?.paused ? 'resume' : 'pause');
let sliceTimer = null;
$('slice-z').oninput = (e) => {
  const z = Number(e.target.value); $('slice-val').textContent = `${z} m`;
  if (slice) slice.mesh.position.y = z;
  clearTimeout(sliceTimer); sliceTimer = setTimeout(() => net.send('set_slice_z', { z }), 80);
};
const toggle = (id, fn) => { const el = $(id); el.onchange = () => fn(el.checked); };
toggle('t-buildings', (v) => { world.buildingGroup.visible = v; });
toggle('t-drones', (v) => { drones.group.visible = v; });
toggle('t-tracers', (v) => { tracers.points.visible = v; if (tracers.trail) tracers.trail.visible = v && $('t-trails').checked; });
toggle('t-trails', (v) => tracers.setTrailsVisible(v && $('t-tracers').checked));
toggle('t-slice', (v) => { if (slice) slice.mesh.visible = v; });
toggle('t-markers', (v) => { world.markerGroup.visible = v; });
$('btn-edit').onclick = () => {
  const on = !editor.enabled; editor.setEnabled(on);
  $('btn-edit').classList.toggle('on', on); $('btn-move').disabled = $('btn-scale').disabled = !on;
};
$('btn-move').onclick = () => { editor.setMode('translate'); $('btn-move').classList.add('on'); $('btn-scale').classList.remove('on'); };
$('btn-scale').onclick = () => { editor.setMode('scale'); $('btn-scale').classList.add('on'); $('btn-move').classList.remove('on'); };

// ----- render loop (setAnimationLoop so it also drives XR frames)
function resize() {
  const w = canvas.clientWidth, h = canvas.clientHeight;
  if (canvas.width !== Math.floor(w * renderer.getPixelRatio()) || canvas.height !== Math.floor(h * renderer.getPixelRatio())) {
    renderer.setSize(w, h, false); camera.aspect = w / h; camera.updateProjectionMatrix();
  }
}
let last = performance.now(), hudT = 0;
renderer.setAnimationLoop(() => {
  const now = performance.now(), dt = Math.min((now - last) / 1000, 0.1); last = now;
  viewFps.v += (1 / Math.max(dt, 1e-4) - viewFps.v) * 0.05;
  resize();
  const age = snap ? now / 1000 - snapAt : 0;
  xr.update(dt, now / 1000, age);
  const camPos = new THREE.Vector3(); camera.getWorldPosition(camPos);
  drones.update(snap, age, camPos, now / 1000);
  if (!xr.state.inXR) orbit.update();
  renderer.render(scene, camera);
  hudT += dt;
  if (hudT > 0.25) { hudT = 0; updateHud({ stats, fpsView: viewFps.v, bytes: snap?.bytes, snap }); }
});

$('hud').querySelector('h1').onclick = () => $('hud').classList.toggle('collapsed');   // click the title to fold the panel

// debugging / headless checks
window.__aeroswarm = {
  get snapshots() { return snapCount; }, get fps() { return viewFps.v; }, get hello() { return hello; },
  get lod() { return drones.counts; }, get stats() { return stats; },
  get info() { return renderer.info.render; }, world, editor, net, xr, camera, orbit, drones,
};
