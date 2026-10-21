// Drone's-eye-view rig logic (P11), pure maths so it is tested without a headset.
export function nextDrone(current, n, dir, active) {
  // step to the next/previous drone, preferring active ones; falls back to any drone
  if (n === 0) return -1;
  for (let k = 1; k <= n; k++) {
    const i = (((current + dir * k) % n) + n) % n;
    if (!active || active[i]) return i;
  }
  return (((current + dir) % n) + n) % n;
}

export class DroneRig {
  constructor({ tau = 0.25, eye = [0, 1.2, 0], headingTau = 0.6 } = {}) {
    this.tau = tau; this.headingTau = headingTau; this.eye = eye;
    this.index = 0; this.pos = [0, 0, 0]; this.heading = 0; this.initialised = false;
  }

  select(i) { this.index = i; this.initialised = false; }

  // dronePos/droneVel are in three.js coordinates. Returns {position, heading} for the rig group.
  update(dt, dronePos, droneVel) {
    const target = [dronePos[0] + this.eye[0], dronePos[1] + this.eye[1], dronePos[2] + this.eye[2]];
    const speedXZ = Math.hypot(droneVel[0], droneVel[2]);
    const wantHeading = speedXZ > 0.5 ? Math.atan2(-droneVel[0], -droneVel[2]) : this.heading;
    if (!this.initialised) {
      this.pos = target.slice(); this.heading = wantHeading; this.initialised = true;
    } else {
      const a = 1 - Math.exp(-dt / this.tau), b = 1 - Math.exp(-dt / this.headingTau);
      for (let k = 0; k < 3; k++) this.pos[k] += (target[k] - this.pos[k]) * a;
      let d = wantHeading - this.heading;
      d = Math.atan2(Math.sin(d), Math.cos(d));          // shortest way round
      this.heading += d * b;
    }
    return { position: this.pos.slice(), heading: this.heading };
  }
}
