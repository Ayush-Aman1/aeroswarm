import * as THREE from 'three';
import { buildLut } from '../colormap.js';

// Horizontal plane showing |u| at slice_z. The float16 bits from the snapshot go straight into a HalfFloat
// DataTexture (row-major, x fastest) and are coloured with a viridis LUT in the shader.
export class WindSlice {
  constructor(areaX, areaY, vmax = 14) {
    const lut = new THREE.DataTexture(buildLut(), 256, 1, THREE.RGBAFormat);
    lut.colorSpace = THREE.SRGBColorSpace; lut.minFilter = lut.magFilter = THREE.LinearFilter; lut.needsUpdate = true;
    this.uniforms = { uTex: { value: null }, uLut: { value: lut }, uVmax: { value: vmax }, uOpacity: { value: 0.62 } };
    const mat = new THREE.ShaderMaterial({
      uniforms: this.uniforms, transparent: true, depthWrite: false, side: THREE.DoubleSide,
      vertexShader: 'varying vec2 vUv; void main(){ vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position,1.0); }',
      fragmentShader: `uniform sampler2D uTex; uniform sampler2D uLut; uniform float uVmax; uniform float uOpacity; varying vec2 vUv;
        void main(){ float v = texture2D(uTex, vUv).r / uVmax;
          vec3 c = texture2D(uLut, vec2(clamp(v, 0.0, 1.0), 0.5)).rgb;
          gl_FragColor = vec4(c, uOpacity * smoothstep(0.0, 0.03, v + 0.03));
          #include <colorspace_fragment>
        }`,
    });
    this.mesh = new THREE.Mesh(new THREE.PlaneGeometry(areaX, areaY), mat);
    this.mesh.rotation.x = -Math.PI / 2;
    this.mesh.position.set(areaX / 2, 30, -areaY / 2);
    this.mesh.renderOrder = 2;
    this.dims = [0, 0];
  }

  update(snap) {
    const { sliceNx: nx, sliceNy: ny } = snap;
    if (!nx || !ny) { this.mesh.visible = false; return; }
    if (nx !== this.dims[0] || ny !== this.dims[1]) {
      this.uniforms.uTex.value?.dispose();
      const tex = new THREE.DataTexture(new Uint16Array(nx * ny), nx, ny, THREE.RedFormat, THREE.HalfFloatType);
      tex.minFilter = tex.magFilter = THREE.LinearFilter; tex.generateMipmaps = false;
      this.uniforms.uTex.value = tex; this.dims = [nx, ny];
    }
    const tex = this.uniforms.uTex.value;
    tex.image.data.set(snap.slice); tex.needsUpdate = true;
    this.mesh.position.y = snap.sliceZ;
  }
}
