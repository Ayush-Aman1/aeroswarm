#!/usr/bin/env python3
"""Compare two wind sources on the same scenario through the WindSource interface only (tier-agnostic).

    python tools/compare_winds.py scenarios/block_small.json lbmpy native [--steps 2000] [--z 30] [--out dir]
Used for the Jan-10 swap decision: the team's own engine replaces the fallback only if it passes the P2 tests AND
matches Tier 1 within tolerance. Metrics on a common 4 m grid at height z (cells inside buildings excluded):
  rel_l2          ||u_a - u_b|| / ||u_a||                        (field difference)
  speed_corr      Pearson correlation of |u|
  mean_speed_ratio  mean|u_b| / mean|u_a|
  wake_ratio_b_over_a  wake deficit behind the tallest building in b relative to a (1.0 = same wake strength)
Default pass thresholds (tune them as a team): rel_l2 <= 0.30, speed_corr >= 0.90, |mean_speed_ratio-1| <= 0.10,
|wake_ratio-1| <= 0.25 - Tier 2 vs Tier 1 is the reference calibration (see docs/LINKING_GUIDE.md).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from engine.backend import to_numpy  # noqa: E402
from engine.scenario.schema import load_scenario  # noqa: E402
from engine.wind.factory import make_wind  # noqa: E402

THRESHOLDS = dict(rel_l2=0.30, speed_corr=0.90, mean_speed_ratio_tol=0.10, wake_ratio_tol=0.25)


def common_grid(layout, z, h=4.0):
    xs = (np.arange(int(layout.area_m[0] / h)) + 0.5) * h
    ys = (np.arange(int(layout.area_m[1] / h)) + 0.5) * h
    X, Y = np.meshgrid(xs, ys, indexing="ij")
    P = np.stack([X.ravel(), Y.ravel(), np.full(X.size, z)], axis=1)
    solid = np.zeros(X.shape, bool)
    for b in layout.buildings:
        solid |= (X >= b.x - h) & (X <= b.x + b.w + h) & (Y >= b.y - h) & (Y <= b.y + b.d + h) & (z <= b.h)
    return P, X.shape, solid


def wake_deficit(speed, shape, layout, z, free, h=4.0):
    """Mean |u| in the box 5..40 m behind the tallest building's lee face, divided by the free-stream |u|."""
    b = max(layout.buildings, key=lambda q: q.h)
    x0, x1 = b.x + b.w + 5, b.x + b.w + 40
    xs = (np.arange(shape[0]) + 0.5) * h
    ys = (np.arange(shape[1]) + 0.5) * h
    X, Y = np.meshgrid(xs, ys, indexing="ij")
    box = (X >= x0) & (X <= x1) & (Y >= b.y) & (Y <= b.y + b.d)
    return float(speed[box].mean() / free) if box.any() else float("nan")


def compare(sc, tier_a, tier_b, steps=2000, z=30.0, cfg_a=None, cfg_b=None):
    P, shape, solid = common_grid(sc.layout, z)
    out = {}
    fields = {}
    for tag, tier, cfg in (("a", tier_a, cfg_a or {}), ("b", tier_b, cfg_b or {})):
        w = make_wind(tier, sc.layout, sc.inflow, sc.sim.dt, **cfg)
        for _ in range(steps):
            w.step(1)
        fields[tag] = to_numpy(w.sample(P)).reshape(shape + (3,))
    a, b = fields["a"], fields["b"]
    m = ~solid
    sa, sb = np.linalg.norm(a, axis=-1), np.linalg.norm(b, axis=-1)
    out["rel_l2"] = float(np.linalg.norm((a - b)[m]) / np.linalg.norm(a[m]))
    out["speed_corr"] = float(np.corrcoef(sa[m], sb[m])[0, 1])
    out["mean_speed_ratio"] = float(sb[m].mean() / sa[m].mean())
    free_a, free_b = float(sa[m][sa[m] > 0.9 * np.percentile(sa[m], 90)].mean()), float(sb[m][sb[m] > 0.9 * np.percentile(sb[m], 90)].mean())
    da, db = wake_deficit(sa, shape, sc.layout, z, free_a), wake_deficit(sb, shape, sc.layout, z, free_b)
    out.update(wake_a=da, wake_b=db, wake_ratio_b_over_a=db / da if da else float("nan"))
    t = THRESHOLDS
    out["pass"] = bool(out["rel_l2"] <= t["rel_l2"] and out["speed_corr"] >= t["speed_corr"]
                       and abs(out["mean_speed_ratio"] - 1) <= t["mean_speed_ratio_tol"]
                       and abs(out["wake_ratio_b_over_a"] - 1) <= t["wake_ratio_tol"])
    out["tiers"] = [tier_a, tier_b]
    return out, (sa, sb, shape)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("scenario"); ap.add_argument("tier_a"); ap.add_argument("tier_b")
    ap.add_argument("--steps", type=int, default=2000); ap.add_argument("--z", type=float, default=30.0)
    ap.add_argument("--cfg-a", default="{}"); ap.add_argument("--cfg-b", default="{}"); ap.add_argument("--out", default=None)
    a = ap.parse_args(argv)
    sc = load_scenario(a.scenario)
    res, (sa, sb, shape) = compare(sc, a.tier_a, a.tier_b, a.steps, a.z, json.loads(a.cfg_a), json.loads(a.cfg_b))
    print(json.dumps(res, indent=1))
    if a.out:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
        fig, axes = plt.subplots(1, 3, figsize=(15, 4))
        ext = (0, sc.layout.area_m[0], 0, sc.layout.area_m[1])
        vmax = max(sa.max(), sb.max())
        for ax, f, t in ((axes[0], sa, a.tier_a), (axes[1], sb, a.tier_b)):
            im = ax.imshow(f.T, origin="lower", extent=ext, vmin=0, vmax=vmax, cmap="viridis"); ax.set_title(f"{t}: |u| at z={a.z:g} m")
        im2 = axes[2].imshow((sb - sa).T, origin="lower", extent=ext, cmap="RdBu", vmin=-vmax / 2, vmax=vmax / 2); axes[2].set_title("b - a")
        fig.colorbar(im, ax=axes[:2]); fig.colorbar(im2, ax=axes[2])
        fig.savefig(out / f"compare_{a.tier_a}_{a.tier_b}.png", dpi=110, bbox_inches="tight")
        (out / f"compare_{a.tier_a}_{a.tier_b}.json").write_text(json.dumps(res, indent=1))
    return 0 if res["pass"] else 3


if __name__ == "__main__":
    sys.exit(main())
