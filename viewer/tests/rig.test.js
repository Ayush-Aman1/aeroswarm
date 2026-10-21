import { describe, it, expect } from 'vitest';
import { DroneRig, nextDrone } from '../src/rig.js';

describe('nextDrone', () => {
  it('wraps and prefers active drones', () => {
    const active = [false, true, false, true];
    expect(nextDrone(1, 4, +1, active)).toBe(3);
    expect(nextDrone(3, 4, +1, active)).toBe(1);
    expect(nextDrone(1, 4, -1, active)).toBe(3);
    expect(nextDrone(0, 4, -1, null)).toBe(3);
    expect(nextDrone(0, 3, +1, [false, false, false])).toBe(1);   // none active: still moves
    expect(nextDrone(0, 0, +1, null)).toBe(-1);
  });
});

describe('DroneRig', () => {
  it('snaps on first update then follows smoothly without overshoot', () => {
    const rig = new DroneRig({ tau: 0.25 });
    const a = rig.update(1 / 60, [0, 30, 0], [0, 0, 0]);
    expect(a.position).toEqual([0, 31.2, 0]);
    let p = a.position;
    for (let i = 0; i < 120; i++) {
      const r = rig.update(1 / 60, [20, 30, 0], [0, 0, 0]);
      expect(r.position[0]).toBeGreaterThanOrEqual(p[0] - 1e-9);   // monotone approach
      expect(r.position[0]).toBeLessThanOrEqual(20 + 1e-9);        // no overshoot
      p = r.position;
    }
    expect(p[0]).toBeGreaterThan(19.9);
  });
  it('heading follows velocity and takes the short way round', () => {
    const rig = new DroneRig({ headingTau: 0.1 });
    rig.update(0.01, [0, 0, 0], [0, 0, -5]);            // flying "forward" (-z): heading 0
    expect(rig.heading).toBeCloseTo(0, 6);
    for (let i = 0; i < 200; i++) rig.update(0.02, [0, 0, 0], [-5, 0, 0.2]);   // now heading ~ +90 deg
    expect(rig.heading).toBeGreaterThan(1.3);
    expect(rig.heading).toBeLessThan(1.7);
    const r2 = new DroneRig({ headingTau: 0.05 }); r2.update(0.01, [0, 0, 0], [0.1, 0, 5]);   // heading ~ ±pi
    const before = r2.heading;
    for (let i = 0; i < 100; i++) r2.update(0.02, [0, 0, 0], [-0.1, 0, 5]);
    expect(Math.abs(Math.abs(r2.heading) - Math.PI)).toBeLessThan(0.2);   // no spin through 0
    expect(Number.isFinite(before)).toBe(true);
  });
  it('ignores heading noise when nearly stationary', () => {
    const rig = new DroneRig(); rig.update(0.01, [0, 0, 0], [0, 0, -5]);
    const h = rig.heading;
    rig.update(0.5, [0, 0, 0], [0.1, 0, 0.1]);
    expect(rig.heading).toBeCloseTo(h, 9);
  });
});
