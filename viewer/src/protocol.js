// Binary snapshot decoder. Spec: ../docs/protocol.md (header 36 bytes, little-endian, 4-byte aligned blocks).
export const MAGIC = 'AERO';
export const HEADER_BYTES = 36;
export const STATE_NAMES = ['idle', 'outbound', 'delivering', 'returning', 'done'];
export const NEAR_BIT = 8;

const pad4 = (n) => (4 - (n % 4)) % 4;

export function decodeSnapshot(buf) {
  if (buf.byteLength < HEADER_BYTES) throw new Error('snapshot too short');
  const dv = new DataView(buf);
  const magic = String.fromCharCode(dv.getUint8(0), dv.getUint8(1), dv.getUint8(2), dv.getUint8(3));
  if (magic !== MAGIC) throw new Error(`bad magic ${magic}`);
  const version = dv.getUint16(4, true);
  if (version !== 1) throw new Error(`unsupported protocol version ${version}`);
  const h = {
    version,
    flags: dv.getUint16(6, true),
    step: dv.getUint32(8, true),
    layoutVersion: dv.getUint32(12, true),
    nDrones: dv.getUint32(16, true),
    nTracers: dv.getUint32(20, true),
    sliceNx: dv.getUint16(24, true),
    sliceNy: dv.getUint16(26, true),
    sliceZ: dv.getFloat32(28, true),
    simTime: dv.getFloat32(32, true),
  };
  let off = HEADER_BYTES;
  const n = h.nDrones, m = h.nTracers, ns = h.sliceNx * h.sliceNy;
  const dronePV = new Float32Array(buf, off, n * 6); off += n * 24;      // pos xyz, vel xyz per drone
  const droneState = new Uint8Array(buf, off, n); off += n + pad4(n);
  const tracers = new Float32Array(buf, off, m * 3); off += m * 12;
  const slice = new Uint16Array(buf, off, ns); off += ns * 2 + pad4(ns * 2);   // raw float16 bits
  if (off !== buf.byteLength) throw new Error(`size mismatch: parsed ${off}, got ${buf.byteLength}`);
  return { ...h, paused: (h.flags & 1) === 1, dronePV, droneState, tracers, slice, bytes: buf.byteLength };
}

// float16 bits -> number (for tests and the HUD; the GPU reads the raw bits via a HalfFloat texture).
export function halfToFloat(bits) {
  const s = (bits & 0x8000) ? -1 : 1, e = (bits >> 10) & 0x1f, f = bits & 0x3ff;
  if (e === 0) return s * 2 ** -14 * (f / 1024);
  if (e === 31) return f ? NaN : s * Infinity;
  return s * 2 ** (e - 15) * (1 + f / 1024);
}
