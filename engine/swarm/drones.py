"""Drone state and dynamics on xp arrays (numpy or cupy).

Per drone: cascaded PD toward the current waypoint (position error -> capped velocity command ->
acceleration command, thrust-capped), wind drag a = k (u_wind - v), Reynolds-1987 separation (only the
separation rule of "Flocks, herds and schools", SIGGRAPH '87), semi-implicit Euler, energy += |thrust| dt.
Thrust is an acceleration for a unit-mass drone, so |thrust| dt is in m/s (an energy *proxy*).
"""
from __future__ import annotations

import numpy as np

from engine.backend import is_gpu, xp
from engine.scenario.schema import SimSettings
from engine.swarm import grid as gridmod

K_POS = 1.0          # 1/s   position error -> velocity command (final approach)
K_VEL = 2.0          # 1/s   velocity error -> acceleration command
K_SEP = 6.0          # m/s^2 separation strength at zero distance
REACH_FINAL_M = 3.0


class Drones:
    def __init__(self, n: int, bounds_m, params: SimSettings | None = None, max_wp: int = 160,
                 use_grid: bool = True, use_kernel: bool | None = None):
        self.n = n
        self.p = params or SimSettings()
        self.bounds_m = tuple(bounds_m)
        self.max_wp = max_wp
        self.use_grid = use_grid
        self.use_kernel = is_gpu if use_kernel is None else use_kernel
        self.grid = gridmod.Grid(bounds_m, self.p.r_sep)
        f = xp.float32
        self.pos = xp.zeros((n, 3), f)
        self.vel = xp.zeros((n, 3), f)
        self.path = xp.zeros((n, max_wp, 3), f)
        self.path_len = xp.zeros(n, xp.int32)
        self.wp = xp.zeros(n, xp.int32)
        self.energy = xp.zeros(n, f)
        self.active = xp.zeros(n, bool)
        self.arrived = xp.zeros(n, bool)          # final waypoint reached
        self.near_flag = xp.zeros(n, bool)        # near another drone this step
        self.near_count = xp.zeros(n, xp.int32)   # near-collision events per drone
        self.near_events = 0                      # total (each pair counted once per encounter)
        self._prev_near_keys = xp.zeros(0, xp.int64)

    # ------------------------------------------------------------------ control surface
    def set_path(self, idx, waypoints) -> None:
        """Assign waypoints [K,3] to drone idx, restart at waypoint 0, mark active."""
        wps = np.asarray(waypoints, np.float32)
        if len(wps) > self.max_wp:
            raise ValueError(f"path has {len(wps)} waypoints, buffer holds {self.max_wp}")
        self.path[idx, :len(wps)] = xp.asarray(wps)
        self.path[idx, len(wps):] = xp.asarray(wps[-1])
        self.path_len[idx] = len(wps)
        self.wp[idx] = 0
        self.arrived[idx] = False
        self.active[idx] = True

    def replace_path_keep_progress(self, idx, waypoints) -> None:
        """Swap in a new path (e.g. after replanning) atomically; restart at its first waypoint."""
        self.set_path(idx, waypoints)

    def place(self, idx, pos) -> None:
        self.pos[idx] = xp.asarray(np.asarray(pos, np.float32))
        self.vel[idx] = 0

    # ------------------------------------------------------------------ dynamics
    def _separation(self, p):
        """-> (accel [m,3], near_flag [m] bool, pair keys of near pairs [int64]) for the active subset."""
        m = len(p)
        pr = self.p
        if m < 2:
            return xp.zeros((m, 3), xp.float32), xp.zeros(m, bool), xp.zeros(0, xp.int64)
        if self.use_grid and self.use_kernel and is_gpu:
            acc, near = gridmod.separation_gpu(p, self.grid, pr.r_sep, K_SEP, pr.d_near)
            # near-collision *pair events* still come from the xp pair search (cheap: only close pairs)
            i, j, d2 = gridmod.pairs_grid(p, pr.d_near, self.grid)
            return acc, near, i * m + j
        i, j, d2 = (gridmod.pairs_grid(p, pr.r_sep, self.grid) if self.use_grid
                    else gridmod.pairs_naive(p, pr.r_sep))
        d = xp.maximum(xp.sqrt(d2), 0.1)
        diff = p[i] - p[j]
        mag = (K_SEP * (1.0 - d / pr.r_sep) / d)[:, None] * diff
        acc = xp.zeros((m, 3), xp.float32)
        for k in range(3):
            acc[:, k] = (xp.bincount(i, weights=mag[:, k], minlength=m)
                         - xp.bincount(j, weights=mag[:, k], minlength=m)).astype(xp.float32)
        near_pair = d2 < pr.d_near * pr.d_near
        ni, nj = i[near_pair], j[near_pair]
        near = (xp.bincount(ni, minlength=m) + xp.bincount(nj, minlength=m)) > 0
        return acc, near, ni * m + nj

    def step(self, dt: float, wind) -> None:
        pr = self.p
        idx = xp.nonzero(self.active)[0]
        m = int(idx.size)
        self.near_flag[:] = False
        if m == 0:
            self._prev_near_keys = xp.zeros(0, xp.int64)
            return
        p, v = self.pos[idx], self.vel[idx]
        wpi, plen = self.wp[idx], self.path_len[idx]
        last = wpi >= plen - 1
        tgt = self.path[idx, wpi]
        dist = xp.linalg.norm(tgt - p, axis=1)
        # advance intermediate waypoints
        adv = (~last) & (dist < pr.reach_m)
        wpi = xp.where(adv, wpi + 1, wpi)
        last = wpi >= plen - 1
        tgt = self.path[idx, wpi]
        to = tgt - p
        dist = xp.linalg.norm(to, axis=1)
        arrived = last & (dist < REACH_FINAL_M)
        unit = to / xp.maximum(dist, 1e-6)[:, None]
        speed_cmd = xp.where(last, xp.minimum(pr.cruise_ms, K_POS * dist), pr.cruise_ms)
        a_cmd = K_VEL * (unit * speed_cmd[:, None] - v)
        a_sep, near, near_keys = self._separation(p)
        thrust = a_cmd + a_sep
        tn = xp.linalg.norm(thrust, axis=1)
        thrust = thrust * xp.minimum(1.0, pr.thrust_max / xp.maximum(tn, 1e-9))[:, None]
        u = wind.sample(p)
        acc = thrust + pr.wind_drag * (u - v)
        v = v + acc * dt                       # semi-implicit Euler: velocity first,
        p = p + v * dt                         # then position with the new velocity
        below = p[:, 2] < 0
        p[:, 2] = xp.maximum(p[:, 2], 0.0)
        v[:, 2] = xp.where(below & (v[:, 2] < 0), 0.0, v[:, 2])
        self.pos[idx], self.vel[idx] = p, v
        self.wp[idx] = wpi
        self.arrived[idx] = arrived
        self.energy[idx] += xp.linalg.norm(thrust, axis=1) * dt
        self.near_flag[idx] = near
        # near-collision events: pairs that are close now but were not close on the previous step
        gk = idx[near_keys // m] * self.n + idx[near_keys % m] if near_keys.size else near_keys
        new = gk[~xp.isin(gk, self._prev_near_keys)] if gk.size else gk
        if new.size:
            self.near_events += int(new.size)
            ids = xp.concatenate([new // self.n, new % self.n])
            self.near_count += xp.bincount(ids, minlength=self.n).astype(xp.int32)
        self._prev_near_keys = gk

    # ------------------------------------------------------------------ utilities
    def snapshot_arrays(self):
        """Host copies of pos, vel (for service/replay)."""
        from engine.backend import to_numpy
        return to_numpy(self.pos), to_numpy(self.vel)
