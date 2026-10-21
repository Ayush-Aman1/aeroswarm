"""Wind tracers: advected by WindSource.sample with RK2, respawned at the upstream (inflow) boundary."""
from __future__ import annotations

import numpy as np

from engine.backend import to_numpy, xp


class Tracers:
    def __init__(self, n: int, bounds_m, seed: int = 0, lifetime_s=(25.0, 70.0)):
        self.n = n
        self.bounds = np.asarray(bounds_m, np.float32)
        self.rng = np.random.default_rng(seed)
        self.life_range = lifetime_s
        self.pos = np.zeros((n, 3), np.float32)
        self.age = np.zeros(n, np.float32)
        self.life = np.zeros(n, np.float32)
        self.direction_deg = 0.0
        self.reseed_all()

    def set_direction(self, deg: float) -> None:
        self.direction_deg = deg

    def _upstream_points(self, m: int) -> np.ndarray:
        """m random points on the upstream boundary for the current wind direction."""
        th = np.deg2rad(self.direction_deg)
        e = np.array([np.cos(th), np.sin(th)])
        q = self.rng.uniform(0, 1, (m, 2)) * self.bounds[:2]
        t = np.full(m, np.inf)
        for ax in range(2):
            if abs(e[ax]) > 1e-9:
                tx = q[:, ax] / e[ax] if e[ax] > 0 else (q[:, ax] - self.bounds[ax]) / e[ax]
                t = np.minimum(t, tx)
        p = q - e[None, :] * t[:, None] + e[None, :] * 0.5          # just inside the upstream edge
        z = 2.0 + 90.0 * self.rng.uniform(0, 1, m) ** 1.5
        return np.column_stack([p, z]).astype(np.float32)

    def reseed_all(self) -> None:
        self.pos = (self.rng.uniform(0, 1, (self.n, 3)) * self.bounds * [1, 1, 0.8] + [0, 0, 2]).astype(np.float32)
        self.age[:] = 0
        self.life[:] = self.rng.uniform(*self.life_range, self.n)

    def step(self, wind, dt: float) -> None:
        p = xp.asarray(self.pos)
        k1 = wind.sample(p)
        k2 = wind.sample(p + dt * k1)
        p = p + 0.5 * dt * (k1 + k2)
        self.pos = to_numpy(p).astype(np.float32)
        speed = np.linalg.norm(to_numpy(k1), axis=1)
        self.age += dt
        out = ((self.pos[:, 0] < 0) | (self.pos[:, 0] > self.bounds[0]) | (self.pos[:, 1] < 0)
               | (self.pos[:, 1] > self.bounds[1]) | (self.pos[:, 2] < 0.5) | (self.pos[:, 2] > self.bounds[2]))
        dead = out | (speed < 1e-6) | (self.age > self.life)
        m = int(dead.sum())
        if m:
            self.pos[dead] = self._upstream_points(m)
            self.age[dead] = 0
            self.life[dead] = self.rng.uniform(*self.life_range, m)
