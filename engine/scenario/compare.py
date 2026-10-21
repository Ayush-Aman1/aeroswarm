"""Paired comparison of two run folders (same scenario + seeds): table + bar charts.

    python -m engine.scenario.compare runs/A runs/B [--out dir]
Each folder may be a single run (config.json + metrics.csv) or hold several runs (subfolders); runs are
paired by (scenario, seed) and missions are paired by mission id.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from engine.metrics.metrics import read_metrics_csv

METRICS = [("delivery_s", "delivery time [s]"), ("energy", "energy proxy"), ("drift_mean", "mean drift [m]"),
           ("drift_max", "max drift [m]"), ("near_collisions", "near-collisions")]


def _runs(folder: Path) -> dict:
    out = {}
    cands = [folder] if (folder / "config.json").exists() else sorted(p for p in folder.iterdir() if p.is_dir())
    for p in cands:
        if not (p / "config.json").exists():
            continue
        cfg = json.loads((p / "config.json").read_text())
        rows = {int(r["mission"]): r for r in read_metrics_csv(p / "metrics.csv")}
        out[(cfg["scenario"]["name"], cfg["seed"])] = (cfg, rows)
    return out


def _num(r, k):
    v = r[k]
    return float(v) if v not in ("", None) else np.nan


def compare(a_dir, b_dir, out_dir=None, quiet=False) -> dict:
    A, B = _runs(Path(a_dir)), _runs(Path(b_dir))
    keys = sorted(set(A) & set(B))
    if not keys:
        raise SystemExit("no paired (scenario, seed) runs found in the two folders")
    res = {}
    for m, _ in METRICS:
        da, db = [], []
        for k in keys:
            for mid in sorted(set(A[k][1]) & set(B[k][1])):
                ra, rb = A[k][1][mid], B[k][1][mid]
                if ra["status"] == "completed" and rb["status"] == "completed":
                    da.append(_num(ra, m)); db.append(_num(rb, m))
        da, db = np.array(da), np.array(db)
        if m == "near_collisions":      # per-drone counts double-count pairs; fine for relative comparison
            pass
        diff = db - da
        res[m] = dict(n=len(da), a_mean=float(np.nanmean(da)), b_mean=float(np.nanmean(db)),
                      diff_mean=float(np.nanmean(diff)),
                      diff_ci95=float(1.96 * np.nanstd(diff, ddof=1) / np.sqrt(max(len(diff), 1))) if len(diff) > 1 else 0.0,
                      rel_change_pct=float(100 * np.nanmean(diff) / np.nanmean(da)) if np.nanmean(da) else float("nan"))
    ca, cb = next(iter(A.values()))[0], next(iter(B.values()))[0]
    la, lb = f"{ca['routing']}", f"{cb['routing']}"
    if not quiet:
        print(f"paired over {len(keys)} (scenario,seed) pair(s), completed missions only; A={la} ({a_dir}), B={lb} ({b_dir})")
        print(f"{'metric':<22}{'A':>10}{'B':>10}{'B-A':>10}{'±95%':>8}{'%':>8}")
        for m, label in METRICS:
            r = res[m]
            print(f"{label:<22}{r['a_mean']:>10.2f}{r['b_mean']:>10.2f}{r['diff_mean']:>10.2f}{r['diff_ci95']:>8.2f}"
                  f"{r['rel_change_pct']:>8.1f}")
    if out_dir:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        out_dir = Path(out_dir); out_dir.mkdir(parents=True, exist_ok=True)
        fig, axes = plt.subplots(1, len(METRICS), figsize=(3 * len(METRICS), 3.2))
        for ax, (m, label) in zip(axes, METRICS):
            ax.bar([la, lb], [res[m]["a_mean"], res[m]["b_mean"]], color=["#8da0cb", "#66c2a5"])
            ax.set_title(label, fontsize=9)
        fig.suptitle(f"paired comparison ({len(keys)} runs) - wind tier {ca['wind']}")
        fig.tight_layout()
        fig.savefig(out_dir / "compare.png", dpi=120)
        (out_dir / "compare.json").write_text(json.dumps(res, indent=1))
    return res


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("a"); ap.add_argument("b"); ap.add_argument("--out", default=None)
    a = ap.parse_args(argv)
    compare(a.a, a.b, a.out)


if __name__ == "__main__":
    main()
