import { describe, it, expect } from 'vitest';
import { buildingToTransform, transformToBuilding, sameBuilding, grabToBuilding, MIN_SIZE } from '../src/editor-logic.js';
import { simToThree, threeToSim } from '../src/coords.js';

const b = { id: 3, x: 280, y: 200, w: 40, d: 30, h: 25 };

describe('editor maths', () => {
  it('round-trips a building through its mesh transform', () => {
    const t = buildingToTransform(b);
    expect(t.position).toEqual([300, 0, -215]);
    expect(t.scale).toEqual([40, 25, 30]);
    expect(sameBuilding(transformToBuilding(3, t.position, t.scale), b)).toBe(true);
  });
  it('moves on x/y only and snaps to 1 m', () => {
    const t = buildingToTransform(b);
    const moved = transformToBuilding(3, [t.position[0] + 10.4, 0, t.position[2] - 5.6], t.scale);
    expect(moved).toMatchObject({ x: 290, y: 206, w: 40, d: 30, h: 25 });
  });
  it('scales about the centre and clamps to the minimum size', () => {
    const t = buildingToTransform(b);
    const big = transformToBuilding(3, t.position, [60, 25, 30]);
    expect(big.x).toBe(270); expect(big.w).toBe(60);
    const tiny = transformToBuilding(3, t.position, [1, 0.2, -3]);
    expect([tiny.w, tiny.h, tiny.d]).toEqual([MIN_SIZE, MIN_SIZE, MIN_SIZE]);
  });
  it('grab release keeps the size', () => {
    expect(grabToBuilding(b, [310.2, 7, -240.7])).toEqual({ id: 3, x: 290, y: 226, w: 40, d: 30, h: 25 });
  });
  it('coordinate maps are inverse', () => {
    expect(threeToSim(...simToThree(1, 2, 3))).toEqual([1, 2, 3]);
    expect(simToThree(10, 20, 30)).toEqual([10, 30, -20]);
  });
});
