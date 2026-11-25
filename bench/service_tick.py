"""Time the live service's tick (Service.tick(): swarm step + tracers + snapshot packing) without a browser.

Writes a per-tick CSV and a JSON summary (percentiles + environment: git commit, backend, GPU, driver, cupy/CUDA) so a
number in a report can be traced to its run. The current working directory's code is imported (not this file's
checkout), so the same script can time an older commit checked out elsewhere:

    python -m bench.service_tick --scenario scenarios/stress_1k.json --wind fluidx3d --warmup 100 --ticks 600 --out DIR
    cd <old worktree> && python <this repo>/bench/service_tick.py ... --out DIR       # same workload, old code

AEROSWARM_FORCE_CPU=1 selects the numpy backend.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.getcwd())      # import the code of the checkout we are run from

import argparse
import csv
import json
import platform
import subprocess
import time
from pathlib import Path

import numpy as np


def _env() -> dict:
    from engine import backend
    import hashlib

    import engine.swarm.drones as drones_mod
    import engine.swarm.grid as grid_mod
    import service.server as server_mod
    env = {"python": platform.python_version(), "platform": platform.platform(), "backend": backend.backend_name,
           "numpy": np.__version__, "cwd": os.getcwd(), "script": os.path.abspath(__file__),
           "script_sha256": hashlib.sha256(open(__file__, "rb").read()).hexdigest(),
           # which checkout's code was actually timed (the cwd's, see the module docstring)
           "imported_from": {m.__name__: os.path.abspath(m.__file__) for m in (grid_mod, drones_mod, server_mod)},
           "grid_py_sha256": hashlib.sha256(open(grid_mod.__file__, "rb").read()).hexdigest(),
           "grid_has_fused_near_pairs": "return_pairs" in open(grid_mod.__file__).read()}
    try:
        env["git_commit"] = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
        env["git_dirty"] = bool(subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"],
                                               capture_output=True, text=True).stdout.strip())
    except OSError:
        pass
    try:
        q = subprocess.run(["nvidia-smi", "--query-gpu=name,driver_version,memory.total", "--format=csv,noheader"],
                           capture_output=True, text=True).stdout.strip()
        env["gpu"] = q
    except OSError:
        env["gpu"] = None
    if backend.is_gpu:
        import cupy
        env["cupy"] = cupy.__version__
        env["cuda_runtime"] = cupy.cuda.runtime.runtimeGetVersion()
        env["cuda_driver"] = cupy.cuda.runtime.driverGetVersion()
    return env


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scenario", default="scenarios/stress_1k.json")
    ap.add_argument("--wind", default="fluidx3d")
    ap.add_argument("--tracers", type=int, default=8000)
    ap.add_argument("--warmup", type=int, default=100, help="untimed ticks first (kernel compile, drones take off)")
    ap.add_argument("--ticks", type=int, default=600)
    ap.add_argument("--label", default=None, help="file name stem (default: <backend>_<scenario>_<wind>)")
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)

    from engine import backend
    from engine.scenario.schema import load_scenario
    from service.server import Service

    svc = Service(load_scenario(a.scenario), a.wind, a.tracers, 20.0)
    sync = (lambda: __import__("cupy").cuda.Stream.null.synchronize()) if backend.is_gpu else (lambda: None)
    for _ in range(a.warmup):
        svc.tick()
    sync()
    rows = []
    for k in range(a.ticks):
        t0 = time.perf_counter()
        svc.tick()                 # ends with a host copy of the snapshot, so the GPU work is complete
        sync()
        rows.append((k, (time.perf_counter() - t0) * 1e3, int(svc.sim.drones.active.sum())))
    svc.sim.close()

    ms = np.array([r[1] for r in rows])
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    stem = a.label or f"{backend.backend_name}_{Path(a.scenario).stem}_{a.wind}"
    with open(out / f"{stem}.csv", "w", newline="") as fh:
        w = csv.writer(fh); w.writerow(["tick", "ms", "active_drones"]); w.writerows(rows)
    summary = {"command": " ".join([sys.executable, *sys.argv]), "scenario": a.scenario, "wind": a.wind,
               "tracers": a.tracers, "warmup": a.warmup, "ticks": a.ticks,
               "median_ms": round(float(np.median(ms)), 2), "mean_ms": round(float(ms.mean()), 2),
               "p95_ms": round(float(np.percentile(ms, 95)), 2), "max_ms": round(float(ms.max()), 2),
               "active_drones_mean": round(float(np.mean([r[2] for r in rows])), 1), "env": _env()}
    (out / f"{stem}.json").write_text(json.dumps(summary, indent=2))
    print(f"{stem}: median {summary['median_ms']} ms  p95 {summary['p95_ms']} ms  max {summary['max_ms']} ms  "
          f"(active drones ~{summary['active_drones_mean']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
