#!/usr/bin/env python3
"""P12 experiment: naive vs wind-aware routing, seeds 1-5, three layouts, every wind tier available here.

    python -m experiments.run_experiments [--tiers synthetic fluidx3d lbmpy] [--seeds 1 2 3 4 5] [--workers 4]
Outputs (default experiments/results/<mac|gpu>/): runs/<tier>/<layout>/<routing>_s<seed>/{config,metrics,summary},
summary_runs.csv, summary_by_condition.csv, paired_differences.csv, <tier>_comparison.png and RESULTS.md. Resumable.
Every table and plot is labelled with the wind tier that produced it (Tier 3 synthetic, Tier 2 FluidX3D fields,
Tier 1 lbmpy) so nobody mistakes Tier 2 FluidX3D output for the team's own kernels.
"""
from __future__ import annotations

import argparse
import csv
import dataclasses
import json
import os
import platform
import time
from collections import defaultdict
from multiprocessing import get_context
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
METRICS = [("mean_delivery_s", "delivery time [s]"), ("energy_mean", "energy proxy"), ("drift_mean", "mean drift [m]"),
           ("drift_max", "max drift [m]"), ("near_collisions", "near-collisions")]
TIER_LABEL = {"synthetic": "Tier 3 - synthetic wind", "fluidx3d": "Tier 2 - FluidX3D precomputed fields",
              "lbmpy": "Tier 1 - lbmpy live solver"}
T95 = {1: 12.71, 2: 4.30, 3: 3.18, 4: 2.78, 5: 2.57, 6: 2.45, 7: 2.36, 8: 2.31, 9: 2.26, 10: 2.23}   # two-sided, n-1 dof


def _job(args):
    tier, scen_path, routing, seed, duration, out_dir, cfg = args
    from engine.scenario import runner
    from engine.scenario.schema import load_scenario
    out_dir = Path(out_dir)
    if (out_dir / "summary.json").exists():
        return json.loads((out_dir / "summary.json").read_text())
    sc = load_scenario(scen_path)
    return runner.run(sc, tier, routing, seed, duration, out_dir, replay=False, wind_cfg=cfg, quiet=True)


def available(tier: str, scen_name: str, field_dir: Path | None):
    """(ok, reason). Tier 2 needs fields for exactly this layout; Tier 1 needs lbmpy + a compiler."""
    if tier == "synthetic":
        return True, ""
    if tier == "fluidx3d":
        from engine.wind.fluidx3d_field import scan
        idx = scan(field_dir)
        return (scen_name in idx), f"no FluidX3D fields for {scen_name} (run tools.fluidx3d.batch)"
    if tier == "lbmpy":
        from engine.wind.lbmpy_solver import LbmpySolver
        return LbmpySolver.available(), "lbmpy / C++ compiler not available"
    return False, f"unknown tier {tier}"


def _warm_lbmpy(dx_m: float) -> None:
    """Compile the lbmpy kernels once, serially, so parallel workers only load them from pystencils' on-disk cache
    (concurrent first-time compiles are the one place a parallel experiment run was seen to misbehave)."""
    from engine.scenario.schema import load_scenario
    from engine.wind.factory import make_wind
    sc = load_scenario(ROOT / "scenarios" / "block_small.json")
    print("warming the lbmpy JIT cache ...", flush=True)
    make_wind("lbmpy", sc.layout, sc.inflow, dx_m=dx_m).step(1)


def aggregate(rows):
    """rows: per-run summary dicts -> (by_condition, paired)."""
    by = defaultdict(list)
    for r in rows:
        by[(r["tier"], r["scenario"], r["routing"])].append(r)
    cond = []
    for (tier, scen, routing), rs in sorted(by.items()):
        d = dict(tier=tier, scenario=scen, routing=routing, n_seeds=len(rs),
                 completed_mean=float(np.mean([r["completed"] for r in rs])))
        for m, _ in METRICS:
            v = np.array([r[m] for r in rs], float)
            d[f"{m}_mean"], d[f"{m}_std"] = float(np.nanmean(v)), float(np.nanstd(v, ddof=1)) if len(v) > 1 else 0.0
        cond.append(d)
    paired = []
    keys = sorted({(r["tier"], r["scenario"]) for r in rows})
    for tier, scen in keys:
        a = {r["seed"]: r for r in rows if r["tier"] == tier and r["scenario"] == scen and r["routing"] == "naive"}
        b = {r["seed"]: r for r in rows if r["tier"] == tier and r["scenario"] == scen and r["routing"] == "aware"}
        seeds = sorted(set(a) & set(b))
        if not seeds:
            continue
        for m, label in METRICS:
            diff = np.array([b[s][m] - a[s][m] for s in seeds], float)
            base = float(np.nanmean([a[s][m] for s in seeds]))
            n = len(diff)
            ci = T95.get(n - 1, 1.96) * float(np.nanstd(diff, ddof=1)) / np.sqrt(n) if n > 1 else float("nan")
            paired.append(dict(tier=tier, scenario=scen, metric=m, n_seeds=n, naive_mean=base,
                               aware_mean=float(np.nanmean([b[s][m] for s in seeds])), diff_mean=float(np.nanmean(diff)),
                               diff_ci95=ci, rel_change_pct=100 * float(np.nanmean(diff)) / base if base else float("nan"),
                               significant=bool(n > 1 and abs(np.nanmean(diff)) > ci)))
    return cond, paired


def write_csv(path, rows):
    if not rows:
        return
    with open(path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader(); w.writerows(rows)


def plots(cond, out: Path, machine: str):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    for tier in sorted({c["tier"] for c in cond}):
        cs = [c for c in cond if c["tier"] == tier]
        scens = sorted({c["scenario"] for c in cs})
        fig, axes = plt.subplots(1, len(METRICS), figsize=(3.4 * len(METRICS), 3.6))
        x = np.arange(len(scens))
        for ax, (m, label) in zip(axes, METRICS):
            for k, (routing, col) in enumerate((("naive", "#8da0cb"), ("aware", "#66c2a5"))):
                vals = [next((c for c in cs if c["scenario"] == s and c["routing"] == routing), None) for s in scens]
                ax.bar(x + (k - 0.5) * 0.38, [v[f"{m}_mean"] if v else 0 for v in vals], 0.38, label=routing, color=col,
                       yerr=[v[f"{m}_std"] if v else 0 for v in vals], capsize=3)
            ax.set_xticks(x); ax.set_xticklabels(scens, rotation=18, fontsize=8); ax.set_title(label, fontsize=9)
        axes[0].legend(fontsize=8)
        fig.suptitle(f"{TIER_LABEL.get(tier, tier)} - naive vs wind-aware, mean ± std over seeds ({machine}; CPU swarm/planner path)",
                     fontsize=10)
        fig.tight_layout()
        fig.savefig(out / f"{tier}_comparison.png", dpi=120)
        plt.close(fig)


def write_report(out: Path, cond, paired, skipped, machine, args, wall_s):
    lines = [f"# Naive vs wind-aware routing - results ({machine})", "",
             "> **CPU tiers only.** Produced on a Mac without CUDA: the swarm, planner and metrics ran on the numpy/CPU path. "
             "Tier 2 fields were computed by FluidX3D (OpenCL, Apple GPU) offline; Tier 1 is lbmpy's *CPU* target on a "
             "coarse grid. GPU-tier numbers come from the Windows runs (see `HANDOFF_WINDOWS.md`).", "",
             f"seeds {args.seeds}, duration cap {args.duration:g} s, {len(cond) // 2 if cond else 0} (tier x layout) conditions, "
             f"wall {wall_s / 60:.1f} min. Seeds vary mission start times and the wind's initial phase. "
             "Paired differences are aware - naive, per seed, 95% CI over seeds (t-interval).", ""]
    for tier in sorted({p["tier"] for p in paired}):
        lines += [f"## {TIER_LABEL.get(tier, tier)}", "",
                  "| layout | metric | naive | aware | aware-naive | ±95% CI | change | significant |", "|---|---|---:|---:|---:|---:|---:|:--:|"]
        for p in paired:
            if p["tier"] != tier:
                continue
            lab = dict(METRICS)[p["metric"]]
            lines.append(f"| {p['scenario']} | {lab} | {p['naive_mean']:.2f} | {p['aware_mean']:.2f} | {p['diff_mean']:+.2f} | "
                         f"{p['diff_ci95']:.2f} | {p['rel_change_pct']:+.1f}% | {'yes' if p['significant'] else 'no'} |")
        lines += ["", f"![{tier}]({tier}_comparison.png)", ""]
    if skipped:
        lines += ["## Skipped", ""] + [f"- {s}" for s in skipped] + [""]
    (out / "RESULTS.md").write_text("\n".join(lines))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tiers", nargs="+", default=["synthetic", "fluidx3d", "lbmpy"])
    ap.add_argument("--scenarios", nargs="+", default=["block_small", "street_canyon", "tower_cluster"])
    ap.add_argument("--seeds", nargs="+", type=int, default=[1, 2, 3, 4, 5])
    ap.add_argument("--duration", type=float, default=300.0)
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) // 2))
    ap.add_argument("--out", default=None)
    ap.add_argument("--field-dir", default=None)
    ap.add_argument("--lbmpy-dx", type=float, default=None, help="lbmpy grid spacing (default 8 m on CPU, 2 m on GPU)")
    a = ap.parse_args(argv)
    from engine import backend
    gpu = backend.is_gpu
    out = Path(a.out or ROOT / "experiments" / "results" / ("gpu" if gpu else "mac"))
    out.mkdir(parents=True, exist_ok=True)
    field_dir = Path(a.field_dir) if a.field_dir else None
    machine = f"{platform.system()} {platform.machine()}, {'cupy GPU' if gpu else 'numpy CPU'}"
    jobs, skipped = [], []
    for tier in a.tiers:
        for scen in a.scenarios:
            ok, why = available(tier, scen, field_dir)
            if not ok:
                skipped.append(f"{tier} / {scen}: {why}")
                continue
            cfg = {}
            if tier == "fluidx3d" and field_dir:
                cfg["field_dir"] = str(field_dir)
            if tier == "lbmpy":
                cfg["dx_m"] = a.lbmpy_dx or (2.0 if gpu else 8.0)
            for routing in ("naive", "aware"):
                for seed in a.seeds:
                    d = out / "runs" / tier / scen / f"{routing}_s{seed}"
                    jobs.append((tier, str(ROOT / "scenarios" / f"{scen}.json"), routing, seed, a.duration, str(d), cfg))
    print(f"{len(jobs)} runs on {a.workers} workers; skipped: {skipped or 'none'}", flush=True)
    t0 = time.time()
    if any(j[0] == "lbmpy" for j in jobs):
        _warm_lbmpy(next(j[6]["dx_m"] for j in jobs if j[0] == "lbmpy"))
    results = []
    if jobs:
        with get_context("spawn").Pool(a.workers) as pool:
            for i, r in enumerate(pool.imap(_job, jobs), 1):
                results.append(r)
                if i % 5 == 0 or i == len(jobs):
                    print(f"  {i}/{len(jobs)} done ({(time.time() - t0) / 60:.1f} min)", flush=True)
    rows = []
    for j, r in zip(jobs, results):
        rows.append(dict(r, tier=j[0], scenario=Path(j[1]).stem, routing=j[2], seed=j[3]))
    write_csv(out / "summary_runs.csv", [{k: v for k, v in r.items()} for r in rows])
    cond, paired = aggregate(rows)
    write_csv(out / "summary_by_condition.csv", cond)
    write_csv(out / "paired_differences.csv", paired)
    plots(cond, out, machine)
    write_report(out, cond, paired, skipped, machine, a, time.time() - t0)
    print(f"wrote {out}/RESULTS.md")
    return rows


if __name__ == "__main__":
    main()
