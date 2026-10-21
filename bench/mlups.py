#!/usr/bin/env python3
"""Wind-solver throughput: MLUPS for Tier 1 (lbmpy D3Q19 SRT + Smagorinsky) at 64^3, 128^3, 256x128x128 and
percentage of the memory-bandwidth ceiling (GPU bandwidth / bytes per cell update).

    python -m bench.mlups [--sizes 64 128 256x128x128] [--steps 100] [--bandwidth-gbs 336] [--out dir]

Runs on whatever target is active: lbmpy CPU kernels on a Mac, CUDA kernels (cupy) on the NVIDIA laptop.
Same harness, unchanged, on both. A periodic box (no boundaries) isolates the kernel cost.
Bytes per cell update (lbmpy float64, pull-stream-collide, velocity written every step):
  19 pdf reads + 19 pdf writes + 3 velocity writes = 41 doubles = 328 B.   (float32 halves it)
"""
from __future__ import annotations

import argparse
import csv
import json
import platform
import subprocess
import sys
import time
from pathlib import Path

from engine import backend
from engine.wind import jitfix

jitfix.apply()

BYTES_PER_CELL_F64 = (19 + 19 + 3) * 8
KNOWN_BANDWIDTH_GBS = {"Apple M1 Pro": 200.0, "NVIDIA GeForce RTX 3060 Laptop GPU": 336.0}


def parse_size(s: str):
    return tuple(int(v) for v in s.split("x")) * (3 if "x" not in s else 1)


def device_info():
    if backend.is_gpu:
        import cupy
        p = cupy.cuda.runtime.getDeviceProperties(0)
        name = p["name"].decode() if isinstance(p["name"], bytes) else str(p["name"])
        bw = 2.0 * p["memoryClockRate"] * 1e3 * (p["memoryBusWidth"] / 8) / 1e9      # DDR: x2, kHz -> Hz
        return name, bw, "gpu"
    name = "cpu"
    if sys.platform == "darwin":
        try:
            name = subprocess.check_output(["sysctl", "-n", "machdep.cpu.brand_string"]).decode().strip()
        except Exception:  # noqa: BLE001
            name = platform.processor()
    else:
        name = platform.processor() or platform.machine()
    return name, KNOWN_BANDWIDTH_GBS.get(name, 0.0), "cpu"


def bench_size(shape, steps: int, target: str):
    from lbmpy import LBMConfig, LBStencil, Method, Stencil, SubgridScaleModel
    from lbmpy.lbstep import LatticeBoltzmannStep
    from pystencils import CreateKernelConfig, Target
    cfg = LBMConfig(stencil=LBStencil(Stencil.D3Q19), method=Method.SRT, relaxation_rate=1.9, compressible=False,
                    subgrid_scale_model=(SubgridScaleModel.SMAGORINSKY, 0.12))
    kc = CreateKernelConfig(target=Target.GPU if target == "gpu" else Target.CPU)
    kc.cpu.openmp.enable = False if target != "gpu" and not _omp() else kc.cpu.openmp.enable
    lbs = LatticeBoltzmannStep(domain_size=shape, periodicity=(True, True, True), lbm_config=cfg, config=kc,
                               compute_velocity_in_every_step=True, name="bench")
    from engine.wind.lbmpy_solver import zero_pdf_fields
    zero_pdf_fields(lbs)
    lbs.pre_run()
    for _ in range(3):
        lbs.time_step()                     # warm-up
    if target == "gpu":
        backend.xp.cuda.Stream.null.synchronize()
    t0 = time.perf_counter()
    for _ in range(steps):
        lbs.time_step()
    if target == "gpu":
        backend.xp.cuda.Stream.null.synchronize()
    dt = time.perf_counter() - t0
    cells = shape[0] * shape[1] * shape[2]
    return cells * steps / dt * 1e-6


def _omp():
    from engine.wind.lbmpy_solver import _openmp_available
    return _openmp_available()


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sizes", nargs="+", default=["64", "128", "256x128x128"])
    ap.add_argument("--steps", type=int, default=100)
    ap.add_argument("--bandwidth-gbs", type=float, default=None, help="override the device memory bandwidth")
    ap.add_argument("--out", default=None)
    a = ap.parse_args(argv)
    name, bw, target = device_info()
    bw = a.bandwidth_gbs or bw
    out = Path(a.out or f"experiments/results/{'gpu' if target == 'gpu' else 'mac'}")
    out.mkdir(parents=True, exist_ok=True)
    ceiling = bw * 1e9 / BYTES_PER_CELL_F64 * 1e-6 if bw else float("nan")
    rows = []
    print(f"device: {name} ({target}), bandwidth {bw:g} GB/s, ceiling {ceiling:.0f} MLUPS at {BYTES_PER_CELL_F64} B/cell")
    for s in a.sizes:
        shape = parse_size(s)
        steps = a.steps if shape[0] * shape[1] * shape[2] <= 2_200_000 else max(20, a.steps // 3)
        m = bench_size(shape, steps, target)
        row = dict(tier="1-lbmpy", device=name, target=target, grid="x".join(map(str, shape)), steps=steps,
                   mlups=round(m, 2), ceiling_mlups=round(ceiling, 1), pct_of_ceiling=round(100 * m / ceiling, 2) if ceiling == ceiling else "")
        rows.append(row)
        print(f"  {row['grid']:>12}: {m:8.2f} MLUPS  ({row['pct_of_ceiling']} % of ceiling)", flush=True)
    with open(out / "mlups_lbmpy.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
    (out / "mlups_lbmpy.json").write_text(json.dumps(rows, indent=1))
    return rows


if __name__ == "__main__":
    main()
