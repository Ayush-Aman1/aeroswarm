import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { decodeSnapshot, halfToFloat } from '../src/protocol.js';

const fx = JSON.parse(readFileSync(new URL('./fixtures/snapshot.json', import.meta.url)));
const raw = readFileSync(new URL('./fixtures/snapshot.bin', import.meta.url));
const ab = () => raw.buffer.slice(raw.byteOffset, raw.byteOffset + raw.byteLength);

describe('snapshot decode (bytes written by engine/protocol.py)', () => {
  it('matches header fields', () => {
    const s = decodeSnapshot(ab());
    expect(s.step).toBe(fx.step); expect(s.layoutVersion).toBe(fx.layoutVersion);
    expect([s.nDrones, s.nTracers, s.sliceNx, s.sliceNy]).toEqual([fx.nDrones, fx.nTracers, fx.sliceNx, fx.sliceNy]);
    expect(s.sliceZ).toBe(30); expect(s.paused).toBe(true);
    expect(s.simTime).toBeCloseTo(fx.simTime, 5);
  });
  it('matches body arrays exactly', () => {
    const s = decodeSnapshot(ab());
    expect(Array.from(s.dronePV)).toEqual(fx.dronePV);
    expect(Array.from(s.droneState)).toEqual(fx.droneState);
    expect(Array.from(s.tracers)).toEqual(fx.tracers);
    expect(Array.from(s.slice, halfToFloat)).toEqual(fx.slice);
  });
  it('rejects garbage', () => {
    expect(() => decodeSnapshot(new ArrayBuffer(10))).toThrow();
    const bad = ab(); new Uint8Array(bad)[0] = 0x58;
    expect(() => decodeSnapshot(bad)).toThrow(/magic/);
    expect(() => decodeSnapshot(ab().slice(0, 100))).toThrow();
  });
  it('float16 conversion', () => {
    expect(halfToFloat(0x3c00)).toBe(1); expect(halfToFloat(0xc000)).toBe(-2); expect(halfToFloat(0)).toBe(0);
  });
});
