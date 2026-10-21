"""Minimal D2Q9 BGK lattice-Boltzmann core used as the validation baseline (P2).

Written from the standard algorithm (Qian, d'Humieres & Lallemand 1992). The structure of the cylinder
case (equilibrium inlet, zero-gradient outlet, bounce-back mask, probe FFT) follows the idea of
https://github.com/pmocz/latticeboltzmann-python (GPL-3.0) but NO code was copied; see CREDITS.md.
These same helpers later validate Tier 1 (lbmpy) and the team's own kernels.
"""
from __future__ import annotations

import numpy as np

C = np.array([[0, 0], [1, 0], [0, 1], [-1, 0], [0, -1], [1, 1], [-1, 1], [-1, -1], [1, -1]])
W = np.array([4 / 9] + [1 / 9] * 4 + [1 / 36] * 4)
OPP = np.array([0, 3, 4, 1, 2, 7, 8, 5, 6])
CS2 = 1.0 / 3.0


def equilibrium(rho, ux, uy, dtype=np.float32):
    cu = C[:, 0, None, None] * ux[None] + C[:, 1, None, None] * uy[None]
    usq = ux ** 2 + uy ** 2
    return (W[:, None, None] * rho[None] * (1 + 3 * cu + 4.5 * cu ** 2 - 1.5 * usq[None])).astype(dtype)


def macroscopic(f):
    rho = f.sum(0)
    ux = (C[:, 0, None, None] * f).sum(0) / rho
    uy = (C[:, 1, None, None] * f).sum(0) / rho
    return rho, ux, uy


def bgk_collide(f, omega):
    rho, ux, uy = macroscopic(f.astype(np.float64))
    feq = equilibrium(rho, ux, uy, np.float64)
    return (f + omega * (feq - f)).astype(f.dtype)


def stream(f):
    out = np.empty_like(f)
    for i, (cx, cy) in enumerate(C):
        out[i] = np.roll(np.roll(f[i], cx, axis=0), cy, axis=1)
    return out


def run_cylinder(nx=320, ny=128, diameter=16, u_in=0.08, reynolds=120.0, steps=16000, probe_from=4000,
                 probe=None, seed=0, snapshot_cb=None):
    """Flow past a cylinder; returns dict(signal=v_y at the probe, tau, St...). Periodic in y."""
    nu = u_in * diameter / reynolds
    tau = 3 * nu + 0.5
    assert tau > 0.51 and u_in <= 0.08 + 1e-12, (tau, u_in)
    omega = 1.0 / tau
    cx, cy = nx // 4, ny // 2
    X, Y = np.meshgrid(np.arange(nx), np.arange(ny), indexing="ij")
    solid = (X - cx) ** 2 + (Y - cy) ** 2 <= (diameter / 2) ** 2
    rng = np.random.default_rng(seed)
    ux = np.full((nx, ny), u_in)
    uy = 1e-3 * u_in * rng.standard_normal((nx, ny))     # seeds the instability deterministically
    f = equilibrium(np.ones((nx, ny)), ux, uy)
    feq_in = equilibrium(np.ones((1, ny)), np.full((1, ny), u_in), np.zeros((1, ny)))[:, 0, :]
    px, py = probe if probe else (cx + 4 * diameter, cy + diameter // 2)
    sig = []
    for it in range(steps):
        fpre = f[:, solid]
        f = bgk_collide(f, omega)
        f[:, solid] = fpre[OPP]               # full-way bounce-back: reverse what arrived at solid cells
        f = stream(f)
        ramp = min(1.0, (it + 1) / 500.0)     # ramp inflow over 500 steps (guide troubleshooting row)
        f[:, 0, :] = equilibrium(np.ones((1, ny)), np.full((1, ny), u_in * ramp), np.zeros((1, ny)))[:, 0, :] \
            if ramp < 1 else feq_in
        f[:, -1, :] = f[:, -2, :]
        if it >= probe_from:
            _, _, uy_ = macroscopic(f[:, px:px + 1, py:py + 1].astype(np.float64))
            sig.append(float(uy_[0, 0]))
        if snapshot_cb and it == steps - 1:
            snapshot_cb(f, solid)
    return dict(signal=np.array(sig), tau=tau, nu=nu, diameter=diameter, u_in=u_in, reynolds=reynolds)


def strouhal(signal, diameter, u_in, dt=1.0):
    """St = f D / U from the dominant FFT peak (Hann window, parabolic peak interpolation)."""
    s = np.asarray(signal, float)
    s = s - s.mean()
    n = len(s)
    spec = np.abs(np.fft.rfft(s * np.hanning(n), n=8 * n))
    k = int(np.argmax(spec[1:])) + 1
    if 1 <= k < len(spec) - 1:
        a, b, c = np.log(spec[k - 1] + 1e-30), np.log(spec[k] + 1e-30), np.log(spec[k + 1] + 1e-30)
        k = k + 0.5 * (a - c) / (a - 2 * b + c)
    f = k / (8 * n * dt)
    return f * diameter / u_in


def vorticity(f):
    _, ux, uy = macroscopic(f.astype(np.float64))
    return np.gradient(uy, axis=0) - np.gradient(ux, axis=1)
