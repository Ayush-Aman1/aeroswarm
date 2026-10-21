"""Tier 1 wind: live lattice-Boltzmann solver generated with lbmpy (D3Q19, SRT or TRT, Smagorinsky LES).

lbmpy / pystencils are *pip dependencies* (copyleft licences: GPL-3 / AGPL-3), never vendored. The API used was
read from the installed lbmpy 2.0 / pystencils 2.0 sources (LatticeBoltzmannStep, LBMConfig, boundaries.*,
BoundaryDataSetter), not from memory.

Setup per solver
  * cell-centred grid over the scenario bounds at `dx_m` (default 2 m -> 200 x 150 x 60 for block_small);
  * wind direction: UBB inflow with the log-law profile on the faces the wind enters through (one face for axis
    aligned winds, two for diagonal ones), `FixedDensity(1)` outflow on the opposite faces, free-slip on side
    faces parallel to the wind and on the top, no-slip ground and buildings (box masks);
  * units: lattice speed of the 10 m reference wind chosen so the fastest inflow cell <= 0.07 (guide rule: <= 0.08),
    dt_lat = dx * u_lat / U_ref, relaxation time floored so tau >= 0.5105 (> 0.51), Smagorinsky constant 0.12.
Relayout: a second solver is built with the new geometry (initialised from the live velocity field), stepped in
chunks between live steps until the residual of mean |u| is below a threshold, then swapped in at a step boundary.

Targets: Target.CPU (tested on the Mac with small grids) and Target.GPU via cupy (written for the NVIDIA laptop,
tests marked `gpu`). The GPU path keeps the velocity field on the device (`compute_velocity_in_every_step`) so
sample() reads it without a host copy.
"""
from __future__ import annotations

import logging
import shutil
import time

import numpy as np

from engine import backend
from engine.backend import ndi, to_numpy, xp
from engine.scenario.schema import Inflow, Layout
from engine.wind import jitfix
from engine.wind.base import WindSourceBase
from engine.wind.synthetic import log_law

jitfix.apply()          # macOS: keep pystencils' extension modules from linking a second libpython

log = logging.getLogger("aeroswarm.wind.lbmpy")
SI_NU = 1.48e-5          # kinematic viscosity of air, m^2/s
LBM_U_CAP = 0.07         # fastest lattice inflow speed we allow (guide: <= 0.08)
PEAK_HEADROOM = 1.25     # building speed-up allowance
TAU_MIN = 0.5105         # guide: tau > 0.51
SMAGORINSKY_C = 0.12


class Units:
    """One helper for all lattice <-> SI conversions."""

    def __init__(self, dx_m: float, inflow: Inflow, ceiling_m: float, tau_min: float = TAU_MIN):
        top = float(log_law(ceiling_m, 1.0, inflow.roughness)) / float(log_law(10.0, 1.0, inflow.roughness))
        self.dx_m = dx_m
        self.u_ref_lat = LBM_U_CAP / (top * PEAK_HEADROOM)       # lattice speed of the 10 m reference wind
        self.u_ref_si = inflow.speed_ms
        self.u_scale = inflow.speed_ms / self.u_ref_lat            # m/s per lattice speed unit
        self.dt_lat_s = dx_m * self.u_ref_lat / inflow.speed_ms    # seconds per lattice step
        nu_lat = SI_NU * self.dt_lat_s / dx_m ** 2
        self.tau = max(0.5 + 3.0 * nu_lat, tau_min)
        self.omega = 1.0 / self.tau
        self.max_inflow_lat = LBM_U_CAP                            # by construction (incl. headroom)

    def check(self) -> None:
        assert self.u_ref_lat * 1.0 <= 0.08 and self.tau > 0.51, (self.u_ref_lat, self.tau)


def faces_for(direction_deg: float):
    """-> (inflow faces, outflow faces, side faces) as slice_from_direction letters for a 3D box."""
    c, s = np.cos(np.deg2rad(direction_deg)), np.sin(np.deg2rad(direction_deg))
    tol = 1e-6
    inflow, outflow, sides = [], [], []
    for comp, lo, hi in ((c, "W", "E"), (s, "S", "N")):
        if comp > tol:
            inflow.append(lo); outflow.append(hi)
        elif comp < -tol:
            inflow.append(hi); outflow.append(lo)
        else:
            sides += [lo, hi]
    return inflow, outflow, sides


def solid_mask(layout: Layout, shape, dx_m: float) -> np.ndarray:
    """Cell-centre box test on the interior grid [nx,ny,nz]."""
    xs, ys, zs = ((np.arange(n) + 0.5) * dx_m for n in shape)
    X, Y, Z = np.meshgrid(xs, ys, zs, indexing="ij")
    m = np.zeros(shape, bool)
    for b in layout.buildings:
        m |= (X >= b.x) & (X <= b.x + b.w) & (Y >= b.y) & (Y <= b.y + b.d) & (Z <= b.h)
    return m


def zero_pdf_fields(lbs) -> None:
    """Give the PDF arrays defined contents before the first step.

    pystencils allocates them with np.empty / cupy.empty, i.e. uninitialised memory. Ghost-layer populations that no
    initialisation kernel writes then hold whatever the heap contained: harmless in a fresh process (zero pages), NaN in a
    process that has recycled memory (seen as NaN winds when Tier 1 ran after other work in the same process).
    """
    dh = lbs.data_handling
    for name in (lbs.pdf_array_name, lbs._tmp_arr_name):
        if name in dh.cpu_arrays:
            dh.cpu_arrays[name][...] = 0.0
        if name in getattr(dh, "gpu_arrays", {}):
            dh.gpu_arrays[name].fill(0.0)


class _Core:
    """One lbmpy LatticeBoltzmannStep for a (layout, inflow) pair."""

    def __init__(self, layout: Layout, inflow: Inflow, dx_m: float, target: str, method: str, shape=None,
                 init_velocity_si: np.ndarray | None = None):
        from lbmpy import LBMConfig, LBStencil, Method, Stencil, SubgridScaleModel
        from lbmpy.boundaries import UBB, FixedDensity, FreeSlip, NoSlip
        from lbmpy.lbstep import LatticeBoltzmannStep
        from pystencils import CreateKernelConfig, Target
        from pystencils.slicing import slice_from_direction

        self.layout, self.inflow, self.dx_m = layout, inflow, dx_m
        self.shape = tuple(shape) if shape else tuple(int(round(v / dx_m)) for v in layout.bounds_m)
        self.units = Units(dx_m, inflow, layout.ceiling_m)
        self.units.check()
        u = self.units
        log.info("lbmpy: grid %s dx=%.2f m, lattice inflow u_ref=%.4f (cap %.2f), tau=%.4f, dt_lat=%.2f ms",
                 self.shape, dx_m, u.u_ref_lat, LBM_U_CAP, u.tau, u.dt_lat_s * 1e3)
        self.gpu = target == "gpu"
        stencil = LBStencil(Stencil.D3Q19)
        cfg = LBMConfig(stencil=stencil, method={"srt": Method.SRT, "trt": Method.TRT}[method],
                        relaxation_rate=u.omega, compressible=False,
                        subgrid_scale_model=(SubgridScaleModel.SMAGORINSKY, SMAGORINSKY_C))
        kc = CreateKernelConfig(target=Target.GPU if self.gpu else Target.CPU)
        if not self.gpu and not _openmp_available():
            kc.cpu.openmp.enable = False
        self.lbs = LatticeBoltzmannStep(domain_size=self.shape, lbm_config=cfg, config=kc,
                                        compute_velocity_in_every_step=True, name="aeroswarm")
        self.dh = self.lbs.data_handling
        zero_pdf_fields(self.lbs)
        self._set_boundaries(layout, inflow, stencil, UBB, FixedDensity, FreeSlip, NoSlip, slice_from_direction)
        self.solid = solid_mask(layout, self.shape, dx_m)
        self._init_field(init_velocity_si)
        self.lbs.pre_run()                   # allocate / upload device arrays once (GPU); no-op on CPU
        self.steps = 0

    # ------------------------------------------------------------------ setup
    def _profile_lat(self, z_cells):
        z_m = np.maximum(z_cells * self.dx_m, 1e-3)
        return self.units.u_ref_lat * log_law(z_m, 1.0, self.inflow.roughness) / float(log_law(10.0, 1.0, self.inflow.roughness))

    def _set_boundaries(self, layout, inflow, stencil, UBB, FixedDensity, FreeSlip, NoSlip, sfd):
        bh = self.lbs.boundary_handling
        c, s = np.cos(np.deg2rad(inflow.direction_deg)), np.sin(np.deg2rad(inflow.direction_deg))
        ins, outs, sides = faces_for(inflow.direction_deg)

        def vel_callback(bd, **_):               # log-law profile on the inflow link cells (lattice units)
            prof = self._profile_lat(bd.non_boundary_cell_positions(2))
            bd["vel_0"], bd["vel_1"], bd["vel_2"] = prof * c, prof * s, 0.0

        free = {"T": (0, 0, -1), "W": (1, 0, 0), "E": (-1, 0, 0), "S": (0, 1, 0), "N": (0, -1, 0)}
        for f in sides + ["T"]:                  # sides parallel to the wind + top: free slip (normal into the fluid)
            bh.set_boundary(FreeSlip(stencil, free[f]), sfd(f, 3))
        for f in outs:
            bh.set_boundary(FixedDensity(1.0), sfd(f, 3))
        ubb = UBB(vel_callback, dim=3)           # one boundary object (one flag) for every inflow face
        for f in ins:
            bh.set_boundary(ubb, sfd(f, 3))
        bh.set_boundary(NoSlip(), sfd("B", 3))
        dx = self.dx_m
        bh.set_boundary(NoSlip(), mask_callback=lambda x, y, z: self._mask_cb(layout, x, y, z, dx))

    @staticmethod
    def _mask_cb(layout, x, y, z, dx):
        m = np.zeros(np.broadcast(x, y, z).shape, bool)
        for b in layout.buildings:              # x, y, z: cell-midpoint coordinates in cell units
            m |= (x * dx >= b.x) & (x * dx <= b.x + b.w) & (y * dx >= b.y) & (y * dx <= b.y + b.d) & (z * dx <= b.h)
        return m

    def _init_field(self, init_velocity_si):
        nx, ny, nz = self.shape
        if init_velocity_si is not None:
            vel = (init_velocity_si / self.units.u_scale).astype(np.float64)
        else:
            c, s = np.cos(np.deg2rad(self.inflow.direction_deg)), np.sin(np.deg2rad(self.inflow.direction_deg))
            prof = self._profile_lat(np.arange(nz) + 0.5)
            vel = np.zeros((nx, ny, nz, 3))
            vel[..., 0], vel[..., 1] = prof[None, None, :] * c, prof[None, None, :] * s
        vel[self.solid] = 0.0
        arr = self.dh.cpu_arrays[self.lbs.velocity_data_name]
        arr[...] = 0.0
        arr[1:-1, 1:-1, 1:-1, :] = vel.astype(arr.dtype)
        self.lbs.set_pdf_fields_from_macroscopic_values()

    # ------------------------------------------------------------------ running
    def step(self, n: int) -> None:
        for _ in range(n):
            self.lbs.time_step()
        self.steps += n

    def sync(self) -> None:
        if self.gpu:
            xp.cuda.Stream.null.synchronize()

    def velocity_si(self):
        """Interior velocity [nx,ny,nz,3] in m/s as an xp array (device array on GPU)."""
        name = self.lbs.velocity_data_name
        arr = self.dh.gpu_arrays[name] if self.gpu else self.dh.cpu_arrays[name]
        return arr[1:-1, 1:-1, 1:-1, :] * self.units.u_scale

    def mean_speed(self) -> float:
        v = to_numpy(self.velocity_si())
        sp = np.linalg.norm(v, axis=-1)
        return float(sp[~self.solid].mean())


def _openmp_available() -> bool:
    """AppleClang needs libomp for OpenMP; Linux/Windows toolchains have it."""
    import sys
    if sys.platform != "darwin":
        return True
    from pathlib import Path
    return any(Path(p).exists() for p in ("/opt/homebrew/lib/libomp.dylib", "/usr/local/lib/libomp.dylib",
                                          "/opt/local/lib/libomp/libomp.dylib"))


class LbmpySolver(WindSourceBase):
    name = "lbmpy"

    def __init__(self, dt_s: float = 0.05, dx_m: float = 2.0, target: str = "auto", method: str = "srt",
                 relayout_chunk_steps: int = 50, settle_tol: float = 1e-4, settle_consecutive: int = 3,
                 settle_min_steps: int = 300, settle_max_steps: int = 20000, **_: object) -> None:
        super().__init__(dt_s)
        reason = self.unavailable_reason()
        if reason:
            raise RuntimeError(f"Tier 1 (lbmpy) cannot run here: {reason}")
        self.dx_m = dx_m
        self.target = ("gpu" if backend.is_gpu else "cpu") if target == "auto" else target
        if self.target == "gpu" and not backend.is_gpu:
            raise RuntimeError("lbmpy target 'gpu' requested but no CUDA device/cupy is available - failing loudly, "
                               "not falling back silently (use target='cpu' to run the CPU kernels)")
        self.method = method
        self.chunk, self.tol, self.consec = relayout_chunk_steps, settle_tol, settle_consecutive
        self.min_steps, self.max_steps = settle_min_steps, settle_max_steps
        self.core: _Core | None = None
        self._next: _Core | None = None
        self._settle = None
        self._frac = 0.0
        self._win = [0, 0.0]            # lattice steps / seconds in the current MLUPS window

    @classmethod
    def unavailable_reason(cls) -> str:
        """'' if Tier 1 can run here, else why not."""
        import sys
        try:
            import lbmpy  # noqa: F401
            import pystencils  # noqa: F401
        except ImportError:
            return "lbmpy / pystencils are not installed"
        if sys.platform == "win32":
            return ("pystencils 2.0's CPU JIT supports only Linux and macOS compilers (no MSVC), and lbmpy compiles its "
                    "macroscopic-value kernels on the CPU even for the GPU target: run Tier 1 under WSL2/Ubuntu "
                    "(docs/LINKING_GUIDE.md, HANDOFF_WINDOWS.md section 'Tier 1 needs Linux')")
        if not any(shutil.which(c) for c in ("clang++", "g++")):
            return "no C++ compiler (clang++/g++) on PATH"
        return ""

    @classmethod
    def available(cls, *_a, **_k) -> bool:
        return cls.unavailable_reason() == ""

    # ------------------------------------------------------------------ interface
    def reset(self, layout: Layout, inflow: Inflow) -> None:
        self.core = _Core(layout, inflow, self.dx_m, self.target, self.method)
        self.layout, self.inflow = layout, inflow
        self._next = self._settle = None
        self.time_s = 0.0
        self._bp = np.array([[b.x, b.y, b.w, b.d, b.h] for b in layout.buildings], float).reshape(-1, 5)
        self._win = [0, 0.0]

    def begin_relayout(self, layout: Layout, inflow: Inflow) -> None:
        init = to_numpy(self.core.velocity_si()).copy()
        self._pending = (layout, inflow)
        self._next = _Core(layout, inflow, self.dx_m, self.target, self.method, init_velocity_si=init)
        self._settle = dict(prev=None, ok=0)

    def relayout_ready(self) -> bool:
        return self._next is not None and self._settle is not None and self._settle.get("ready", False)

    def commit_relayout(self) -> None:
        if not self.relayout_ready():
            return
        self.core = self._next
        self.layout, self.inflow = self._pending
        self._bp = np.array([[b.x, b.y, b.w, b.d, b.h] for b in self.layout.buildings], float).reshape(-1, 5)
        self._next = self._settle = self._pending = None

    def step(self, n: int = 1) -> None:
        """Advance n sim steps (dt_s each): the matching number of lattice steps, then one settling chunk."""
        t0 = time.perf_counter()
        want = n * self.dt_s / self.core.units.dt_lat_s + self._frac
        k = int(want)
        self._frac = want - k
        self.core.step(k)
        self.core.sync()
        dt = time.perf_counter() - t0
        self.time_s += n * self.dt_s
        self._win[0] += k
        self._win[1] += dt
        if self._win[0] >= 100:                       # MLUPS over >= 100 lattice steps
            cells = int(np.prod(self.core.shape))
            self._stats["mlups"] = cells * self._win[0] / max(self._win[1], 1e-9) * 1e-6
            self._win = [0, 0.0]
        self._stats["step_ms"] = dt * 1e3 / max(n, 1)
        if self._next is not None and not self._settle.get("ready"):
            self._settle_chunk()

    def _settle_chunk(self):
        nxt, st = self._next, self._settle
        nxt.step(self.chunk)
        nxt.sync()
        mean = nxt.mean_speed()
        if st["prev"] is not None and np.isfinite(mean) and mean > 0:
            res = abs(mean - st["prev"]) / mean
            st["ok"] = st["ok"] + 1 if res < self.tol else 0
            st["residual"] = res
        st["prev"] = mean
        if (st["ok"] >= self.consec and nxt.steps >= self.min_steps) or nxt.steps >= self.max_steps:
            if nxt.steps >= self.max_steps:
                log.warning("lbmpy relayout hit the settle step cap (%d) - swapping anyway", self.max_steps)
            st["ready"] = True

    def sample(self, pos):
        P = to_numpy(pos).astype(np.float64).reshape(-1, 3)
        shape = np.array(self.core.shape, float)
        co = np.clip(P / self.dx_m - 0.5, 0.0, shape - 1.0)
        c = xp.asarray(co.T.astype(np.float32))
        vel_field = self.core.velocity_si()
        v = np.stack([to_numpy(ndi.map_coordinates(vel_field[..., k], c, order=1, mode="nearest"))
                      for k in range(3)], axis=1).astype(np.float64)
        bp = self._bp
        if len(bp):
            x, y, z = P[:, 0:1], P[:, 1:2], P[:, 2:3]
            v[((x >= bp[:, 0]) & (x <= bp[:, 0] + bp[:, 2]) & (y >= bp[:, 1]) & (y <= bp[:, 1] + bp[:, 3])
               & (z <= bp[:, 4])).any(axis=1)] = 0.0
        return xp.asarray(v.astype(np.float32))

    def slice_z(self, z_m: float):
        k = int(np.clip(round(z_m / self.dx_m - 0.5), 0, self.core.shape[2] - 1))
        sl = self.core.velocity_si()[:, :, k, :]
        mask = xp.asarray((~self.core.solid[:, :, k])[..., None].astype(np.float32))
        return sl * mask

    def stats(self) -> dict:
        s = super().stats()
        s.update(target=self.target, relayout_pending=self._next is not None,
                 tau=self.core.units.tau if self.core else 0.0, lattice_u_ref=self.core.units.u_ref_lat if self.core else 0.0)
        return s
