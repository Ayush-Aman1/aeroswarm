#!/usr/bin/env python3
"""Swarm step time vs N: grid search vs naive, on whatever backend is active (numpy here, cupy on a GPU box).

    python -m bench.swarm_bench [--sizes 100 1000 10000] [--steps 20] [--out experiments/results/mac]
Timing uses time.perf_counter on CPU; on cupy it synchronises the device around every timed block (same
idea as CUDA events, as in the CIS 565 flocking project, https://github.com/LinDadaism/GPU-CUDA-Flocking).
"""
from __future__ import annotations

import argparse
import csv
import json
import time
from pathlib import Path

import numpy as np

from engine import backend
from engine.backend import xp
from engine.scenario.schema import SimSettings
from engine.swarm.drones import Drones

BOUNDS = (400.0, 300.0, 120.0)


class _Still:
    def sample(self, pos):
        return xp.zeros((len(pos), 3), xp.float32)


def _sync():
    if backend.is_gpu:
        xp.cuda.Stream.null.synchronize()


def time_step(n: int, use_grid: bool, steps: int, seed: int = 0) -> float:
    rng = np.random.default_rng(seed)
    d = Drones(n, BOUNDS, SimSettings(), use_grid=use_grid)
    pos = rng.uniform([0, 0, 5], [400, 300, 100], (n, 3))
    goal = rng.uniform([0, 0, 5], [400, 300, 100], (n, 3))
    for i in range(n):
        d.place(i, pos[i]); d.set_path(i, [goal[i]])
    w = _Still()
    d.step(0.05, w); _sync()                      # warm-up (kernel compile / caches)
    t0 = time.perf_counter()
    for _ in range(steps):
        d.step(0.05, w)
    _sync()
    return (time.perf_counter() - t0) * 1e3 / steps


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--sizes", type=int, nargs="+", default=[100, 1000, 10000])
    ap.add_argument("--steps", type=int, default=20)
    ap.add_argument("--naive-max", type=int, default=10000, help="skip the naive path above this N")
    ap.add_argument("--out", default=None)
    a = ap.parse_args(argv)
    out = Path(a.out or f"experiments/results/{'gpu' if backend.is_gpu else 'mac'}")
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    for n in a.sizes:
        for mode in ("grid", "naive"):
            if mode == "naive" and n > a.naive_max:
                continue
            steps = a.steps if n <= 1000 else max(3, a.steps // 5)
            ms = time_step(n, mode == "grid", steps)
            rows.append(dict(backend=backend.backend_name, n=n, search=mode, step_ms=round(ms, 3)))
            print(f"{backend.backend_name:6s} N={n:6d} {mode:5s} {ms:9.2f} ms/step", flush=True)
    with open(out / "swarm_step_time.csv", "w", newline="") as fh:
        wr = csv.DictWriter(fh, fieldnames=list(rows[0])); wr.writeheader(); wr.writerows(rows)
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        fig, ax = plt.subplots(figsize=(5.5, 4))
        for mode in ("grid", "naive"):
            r = [x for x in rows if x["search"] == mode]
            ax.plot([x["n"] for x in r], [x["step_ms"] for x in r], "o-", label=mode)
        ax.set_xscale("log"); ax.set_yscale("log"); ax.set_xlabel("drones N"); ax.set_ylabel("ms per step")
        ax.set_title(f"Swarm step time ({backend.backend_name}) - {'CPU tiers only' if not backend.is_gpu else 'GPU'}")
        ax.legend(); fig.savefig(out / "swarm_step_time.png", dpi=120, bbox_inches="tight")
    except Exception as exc:  # noqa: BLE001
        print("plot skipped:", exc)
    (out / "swarm_step_time.json").write_text(json.dumps(rows, indent=1))
    return rows


if __name__ == "__main__":
    main()
