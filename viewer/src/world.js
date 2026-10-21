import * as THREE from 'three';
import { buildingToTransform } from './editor-logic.js';
import { simToThree } from './coords.js';

// Static scene content: ground, buildings (one mesh each, origin at the base centre), depot/target markers.
export class World {
  constructor(scene) {
    this.scene = scene;
    this.group = new THREE.Group();
    scene.add(this.group);
    this.buildings = new Map();       // id -> mesh
    this.layout = null;
    this.bGeo = new THREE.BoxGeometry(1, 1, 1); this.bGeo.translate(0, 0.5, 0);
    this.edgeGeo = new THREE.EdgesGeometry(this.bGeo);
    this.bMat = new THREE.MeshStandardMaterial({ color: 0x8a97a8, roughness: 0.85, metalness: 0.05 });
    this.selMat = new THREE.MeshStandardMaterial({ color: 0xffd479, roughness: 0.7, emissive: 0x332200 });
    this.buildingGroup = new THREE.Group();
    this.markerGroup = new THREE.Group();
    this.groundGroup = new THREE.Group();
    this.group.add(this.groundGroup, this.buildingGroup, this.markerGroup);
  }

  setHello(h) {
    this.area = h.layout.area_m;
    this._buildGround(this.area);
    this.setLayout(h.layout);
    this._buildMarkers(h.depots, h.targets);
  }

  _buildGround([ax, ay]) {
    this.groundGroup.clear();
    const g = new THREE.Mesh(new THREE.PlaneGeometry(ax, ay), new THREE.MeshStandardMaterial({ color: 0x1b2430, roughness: 1 }));
    g.rotation.x = -Math.PI / 2; g.position.set(ax / 2, -0.05, -ay / 2);
    const grid = new THREE.GridHelper(Math.max(ax, ay), Math.max(ax, ay) / 20, 0x2d3a4b, 0x222c3a);
    grid.scale.set(ax / Math.max(ax, ay), 1, ay / Math.max(ax, ay));
    grid.position.set(ax / 2, 0, -ay / 2);
    this.groundGroup.add(g, grid);
  }

  setLayout(layout) {
    this.layout = layout;
    const seen = new Set();
    for (const b of layout.buildings) {
      seen.add(b.id);
      let m = this.buildings.get(b.id);
      if (!m) {
        m = new THREE.Mesh(this.bGeo, this.bMat);
        m.add(new THREE.LineSegments(this.edgeGeo, new THREE.LineBasicMaterial({ color: 0xcfd8e3 })));
        m.userData.id = b.id;
        this.buildingGroup.add(m); this.buildings.set(b.id, m);
      }
      this.applyBuilding(m, b);
    }
    for (const [id, m] of [...this.buildings]) if (!seen.has(id)) { this.buildingGroup.remove(m); this.buildings.delete(id); }
  }

  applyBuilding(mesh, b) {
    const t = buildingToTransform(b);
    mesh.position.set(...t.position); mesh.scale.set(...t.scale);
    mesh.rotation.set(0, 0, 0);
    mesh.updateMatrixWorld(true);
  }

  serverBuilding(id) { return this.layout.buildings.find((b) => b.id === id); }

  select(id) {
    for (const [bid, m] of this.buildings) m.material = bid === id ? this.selMat : this.bMat;
  }

  _buildMarkers(depots, targets) {
    this.markerGroup.clear();
    const dm = new THREE.InstancedMesh(new THREE.CylinderGeometry(6, 6, 0.6, 24), new THREE.MeshBasicMaterial({ color: 0x35d0ff }), depots.length);
    depots.forEach((d, i) => { const m = new THREE.Matrix4().setPosition(...simToThree(d.x, d.y, 0.3)); dm.setMatrixAt(i, m); });
    const tm = new THREE.InstancedMesh(new THREE.ConeGeometry(1.6, 5, 8), new THREE.MeshBasicMaterial({ color: 0x3ddc84 }), targets.length);
    targets.forEach((t, i) => { const m = new THREE.Matrix4().setPosition(...simToThree(t.x, t.y, 2.5)); tm.setMatrixAt(i, m); });
    this.markerGroup.add(dm, tm);
  }

  get meshes() { return [...this.buildings.values()]; }
}
