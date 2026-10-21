"""The P2 cylinder Strouhal test run on lbmpy (D2Q9, SRT) instead of the numpy baseline - same case, same
analysis (tests/validation/lbm2d.strouhal). Periodic in y, UBB inflow, FixedDensity outflow, cylinder = NoSlip."""
from __future__ import annotations

import numpy as np

from engine.wind import jitfix
from tests.validation.lbm2d import strouhal

jitfix.apply()


def run_lbmpy_cylinder(nx=320, ny=128, diameter=16, u_in=0.08, reynolds=120.0, steps=20000, probe_from=8000,
                       target="cpu", seed=0):
    from lbmpy import LBMConfig, LBStencil, Method, Stencil
    from lbmpy.boundaries import UBB, FixedDensity, NoSlip
    from lbmpy.lbstep import LatticeBoltzmannStep
    from pystencils import CreateKernelConfig, Target
    from pystencils.slicing import slice_from_direction

    nu = u_in * diameter / reynolds
    tau = 3 * nu + 0.5
    assert tau > 0.51 and u_in <= 0.08 + 1e-12
    cfg = LBMConfig(stencil=LBStencil(Stencil.D2Q9), method=Method.SRT, relaxation_rate=1.0 / tau)
    kc = CreateKernelConfig(target=Target.GPU if target == "gpu" else Target.CPU)
    kc.cpu.openmp.enable = False
    lbs = LatticeBoltzmannStep(domain_size=(nx, ny), periodicity=(False, True), lbm_config=cfg, config=kc,
                               compute_velocity_in_every_step=True, name="cyl")
    from engine.wind.lbmpy_solver import zero_pdf_fields
    zero_pdf_fields(lbs)
    bh = lbs.boundary_handling
    bh.set_boundary(UBB((u_in, 0.0)), slice_from_direction("W", 2))
    bh.set_boundary(FixedDensity(1.0), slice_from_direction("E", 2))
    cx, cy = nx // 4, ny // 2
    bh.set_boundary(NoSlip(), mask_callback=lambda x, y: (x - cx - 0.5) ** 2 + (y - cy - 0.5) ** 2 <= (diameter / 2) ** 2)
    rng = np.random.default_rng(seed)
    vel = lbs.data_handling.cpu_arrays[lbs.velocity_data_name]
    vel[...] = 0.0
    vel[1:-1, 1:-1, 0] = u_in
    vel[1:-1, 1:-1, 1] = 1e-3 * u_in * rng.standard_normal((nx, ny))      # seeds the instability deterministically
    lbs.set_pdf_fields_from_macroscopic_values()
    lbs.pre_run()
    px, py = cx + 4 * diameter, cy + diameter // 2
    sig = []
    for it in range(steps):
        lbs.time_step()
        if it >= probe_from:
            v = lbs.data_handling.cpu_arrays[lbs.velocity_data_name] if target != "gpu" else \
                lbs.data_handling.gpu_arrays[lbs.velocity_data_name].get()
            sig.append(float(v[px + 1, py + 1, 1]))
    return dict(signal=np.array(sig), tau=tau, diameter=diameter, u_in=u_in, strouhal=strouhal(sig, diameter, u_in))
