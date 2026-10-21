"""Tier 3 synthetic wind: log-law inflow + analytic building effects, no CFD.

Static part (rebuilt on relayout, instant): per building, in the wind-aligned frame
  * zero velocity inside the box;
  * speed-up (~1.3x) in a band beside the lateral faces;
  * upwash over the roof and a mild blockage slow-down upstream;
  * a wake 5*h long with a Gaussian velocity deficit.
Dynamic part (evaluated analytically at sample points, no grid rebuild): alternating wake vortices whose
phase advances with time at Strouhal 0.2 (f = 0.2*U/W), confined to the wake envelope, so step() makes
the wake gusty while the rest of the field stays constant.

The grid is cell-centred: cell (i, j, k) is centred at ((i+.5)dx, (j+.5)dx, (k+.5)dx).
"""
from __future__ import annotations

import time

import numpy as np

from engine.backend import ndi, to_numpy, xp
from engine.scenario.schema import Building, Inflow, Layout
from engine.wind.base import WindSourceBase

STROUHAL = 0.2
WAKE_LEN_H = 5.0        # wake length in building heights
SPEEDUP = 0.3           # +30 % beside lateral faces
WAKE_DEFICIT = 0.7      # peak velocity deficit at the lee face
VORTEX_AMP = 0.35       # lateral gust amplitude relative to U(h)
CONVECT = 0.8           # vortex convection speed relative to U(h)


def log_law(z, speed_ms: float, z0: float):
    """U(z) = U_ref * ln(z/z0) / ln(10/z0); zero at/below z0."""
    z = np.maximum(np.asarray(z, dtype=np.float64), z0)
    return speed_ms * np.log(z / z0) / np.log(10.0 / z0)


def _vz(z, h):
    """1 below roof height, smooth Gaussian drop above."""
    return np.exp(-(np.maximum(z - h, 0.0) / (0.4 * h)) ** 2)


class _Frame:
    """Wind-aligned frame of one building: s along the wind, t lateral, extents L (along) and W (across)."""

    def __init__(self, b: Building, theta: float, inflow: Inflow):
        self.b = b
        self.c, self.s_ = np.cos(theta), np.sin(theta)
        self.L = abs(b.w * self.c) + abs(b.d * self.s_)
        self.W = abs(b.w * self.s_) + abs(b.d * self.c)
        self.Uh = float(log_law(b.h, inflow.speed_ms, inflow.roughness))

    def st(self, X, Y):
        dx, dy = X - self.b.cx, Y - self.b.cy
        return dx * self.c + dy * self.s_, -dx * self.s_ + dy * self.c

    def wake_envelope(self, s, t, z):
        """0 outside the wake; (1 - sd/5h) * Gaussian(t) * vz inside."""
        b = self.b
        sd = s - self.L / 2
        sigma = 0.6 * self.W / 2 + 0.1 * np.maximum(sd, 0)
        along = np.clip(1.0 - sd / (WAKE_LEN_H * b.h), 0.0, 1.0) * (sd > 0)
        return along * np.exp(-(t / sigma) ** 2) * _vz(z, b.h)

    def region(self, dx: float, bounds) -> tuple[slice, slice]:
        """Index box (x, y) covering this building's zone of influence."""
        b = self.b
        s_lo, s_hi = -self.L / 2 - 2.5 * b.h, self.L / 2 + WAKE_LEN_H * b.h
        t_lim = self.W + 3 * (0.3 * self.W + 0.1 * WAKE_LEN_H * b.h) + 8
        corners = np.array([(s, t) for s in (s_lo, s_hi) for t in (-t_lim, t_lim)])
        wx = b.cx + corners[:, 0] * self.c - corners[:, 1] * self.s_
        wy = b.cy + corners[:, 0] * self.s_ + corners[:, 1] * self.c
        nx, ny = int(round(bounds[0] / dx)), int(round(bounds[1] / dx))
        i0, i1 = max(int(wx.min() / dx) - 1, 0), min(int(wx.max() / dx) + 2, nx)
        j0, j1 = max(int(wy.min() / dx) - 1, 0), min(int(wy.max() / dx) + 2, ny)
        return slice(i0, i1), slice(j0, j1)


class SyntheticWind(WindSourceBase):
    name = "synthetic"

    def __init__(self, dt_s: float = 0.05, dx_m: float = 2.0, **_: object) -> None:
        super().__init__(dt_s)
        self.dx_m = dx_m
        self.U = None            # xp [nx,ny,nz,3] float32 static field
        self.solid = None        # numpy bool [nx,ny,nz]
        self._frames: list[_Frame] = []
        self._bparams = None     # numpy [B,5] x,y,w,d,h
        self._theta = 0.0

    # ------------------------------------------------------------------------------ build
    def _build(self, layout: Layout, inflow: Inflow):
        dx = self.dx_m
        nx, ny, nz = (int(round(v / dx)) for v in layout.bounds_m)
        theta = np.deg2rad(inflow.direction_deg)
        e_s = np.array([np.cos(theta), np.sin(theta), 0.0])
        xs = (np.arange(nx) + 0.5) * dx
        ys = (np.arange(ny) + 0.5) * dx
        zs = (np.arange(nz) + 0.5) * dx
        prof = log_law(zs, inflow.speed_ms, inflow.roughness)            # [nz]
        mult = np.ones((nx, ny, nz), np.float64)
        w_up = np.zeros((nx, ny, nz), np.float64)
        solid = np.zeros((nx, ny, nz), bool)
        frames = [_Frame(b, theta, inflow) for b in layout.buildings]
        for fr in frames:
            b = fr.b
            si, sj = fr.region(dx, layout.bounds_m)
            X, Y, Z = np.meshgrid(xs[si], ys[sj], zs, indexing="ij")
            s, t = fr.st(X, Y)
            Lh, Wh = fr.L / 2, fr.W / 2
            vz = _vz(Z, b.h)
            # wake deficit
            m = 1.0 - WAKE_DEFICIT * fr.wake_envelope(s, t, Z)
            # lateral speed-up band
            bw = 0.5 * Wh + 4.0
            dt_ = np.maximum(np.abs(t) - Wh, 0.0)
            sfac = np.exp(-(np.maximum(np.abs(s) - Lh, 0.0) / (0.75 * Lh + 2.0)) ** 2)
            band = np.exp(-(dt_ / bw) ** 2) * (np.abs(t) >= Wh * 0.9)
            m *= 1.0 + SPEEDUP * band * sfac * vz
            # upstream blockage
            su = np.maximum(-s - Lh, 0.0) * (s < -Lh)
            m *= 1.0 - 0.3 * np.exp(-(su / (0.6 * b.h)) ** 2) * np.exp(-(t / (Wh * 1.2 + 1.0)) ** 2) * vz * (s < -Lh)
            mult[si, sj] *= m
            # roof upwash (vertical component, scaled by U(h) below)
            dz = np.maximum(Z - b.h, 0.0) * (Z > b.h)
            fp = (np.exp(-(np.maximum(np.abs(t) - Wh, 0.0) / (0.3 * Wh + 1.0)) ** 2)
                  * np.exp(-(np.maximum(np.abs(s) - Lh, 0.0) / (0.3 * Lh + 1.0)) ** 2))
            w_up[si, sj] += 0.25 * fr.Uh * np.exp(-(dz / (0.35 * b.h)) ** 2) * fp * (Z > b.h)
            # exact solid test in world coordinates
            solid[si, sj] |= ((X >= b.x) & (X <= b.x + b.w) & (Y >= b.y) & (Y <= b.y + b.d) & (Z <= b.h))
        U = np.zeros((nx, ny, nz, 3), np.float32)
        base = (mult * prof[None, None, :]).astype(np.float32)
        U[..., 0] = base * e_s[0]
        U[..., 1] = base * e_s[1]
        U[..., 2] = w_up.astype(np.float32)
        U[solid] = 0.0
        bp = np.array([[b.x, b.y, b.w, b.d, b.h] for b in layout.buildings], np.float64).reshape(-1, 5)
        return dict(U=U, solid=solid, frames=frames, bparams=bp, theta=theta, layout=layout, inflow=inflow)

    def _install(self, built: dict) -> None:
        self.U = xp.asarray(built["U"])
        self.solid = built["solid"]
        self._frames = built["frames"]
        self._bparams = built["bparams"]
        self._theta = built["theta"]
        self.layout, self.inflow = built["layout"], built["inflow"]

    # ------------------------------------------------------------------------------ interface
    def reset(self, layout: Layout, inflow: Inflow) -> None:
        self._install(self._build(layout, inflow))
        self._pending = None
        self.time_s = 0.0

    def begin_relayout(self, layout: Layout, inflow: Inflow) -> None:
        self._pending = (layout, inflow)
        self._pending_built = self._build(layout, inflow)    # instant (tens of ms)

    def relayout_ready(self) -> bool:
        return self._pending is not None

    def commit_relayout(self) -> None:
        if self._pending is None:
            return
        self._install(self._pending_built)
        self._pending = self._pending_built = None

    def step(self, n: int = 1) -> None:
        t0 = time.perf_counter()
        self.time_s += n * self.dt_s
        ms = (time.perf_counter() - t0) * 1e3 / max(n, 1)
        self._stats = {"mlups": 0.0, "step_ms": ms}

    # ------------------------------------------------------------------------------ evaluation
    def _dynamic(self, P: np.ndarray) -> np.ndarray:
        """Time-varying wake gust at points P [N,3] (numpy float64) -> [N,3]."""
        out = np.zeros_like(P)
        for fr in self._frames:
            b = fr.b
            s, t = fr.st(P[:, 0], P[:, 1])
            sd = s - fr.L / 2
            sel = (sd > 0) & (sd < WAKE_LEN_H * b.h) & (np.abs(t) < fr.W + 10) & (P[:, 2] < 1.6 * b.h)
            if not sel.any():
                continue
            env = fr.wake_envelope(s[sel], t[sel], P[sel, 2])
            f = STROUHAL * fr.Uh / fr.W
            lam = CONVECT * fr.Uh / f
            phase = 2 * np.pi * (f * self.time_s - sd[sel] / lam)
            v_t = VORTEX_AMP * fr.Uh * env * np.sin(phase)
            v_s = 0.1 * fr.Uh * env * np.cos(phase)
            out[sel, 0] += v_s * fr.c - v_t * fr.s_
            out[sel, 1] += v_s * fr.s_ + v_t * fr.c
        return out

    def _inside(self, P: np.ndarray) -> np.ndarray:
        bp = self._bparams
        if len(bp) == 0:
            return np.zeros(len(P), bool)
        x, y, z = P[:, 0:1], P[:, 1:2], P[:, 2:3]
        return ((x >= bp[:, 0]) & (x <= bp[:, 0] + bp[:, 2]) & (y >= bp[:, 1]) & (y <= bp[:, 1] + bp[:, 3])
                & (z <= bp[:, 4])).any(axis=1)

    def sample(self, pos):
        P = to_numpy(pos).astype(np.float64).reshape(-1, 3)
        dx = self.dx_m
        n = np.array(self.U.shape[:3], np.float64)
        co = np.clip(P / dx - 0.5, 0.0, n - 1.0)
        c = xp.asarray(co.T.astype(np.float32))
        vel = np.stack([to_numpy(ndi.map_coordinates(self.U[..., k], c, order=1, mode="nearest"))
                        for k in range(3)], axis=1).astype(np.float64)
        vel += self._dynamic(P)
        vel[self._inside(P)] = 0.0
        return xp.asarray(vel.astype(np.float32))

    def slice_z(self, z_m: float):
        k = int(np.clip(round(z_m / self.dx_m - 0.5), 0, self.U.shape[2] - 1))
        nx, ny = self.U.shape[:2]
        z = (k + 0.5) * self.dx_m
        xs = (np.arange(nx) + 0.5) * self.dx_m
        ys = (np.arange(ny) + 0.5) * self.dx_m
        X, Y = np.meshgrid(xs, ys, indexing="ij")
        P = np.stack([X.ravel(), Y.ravel(), np.full(X.size, z)], axis=1)
        dyn = self._dynamic(P).reshape(nx, ny, 3)
        dyn[self.solid[:, :, k]] = 0.0
        return self.U[:, :, k, :] + xp.asarray(dyn.astype(np.float32))
