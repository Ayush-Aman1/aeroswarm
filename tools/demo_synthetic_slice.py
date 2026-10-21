#!/usr/bin/env python3
"""Demo: save a PNG of slice_z(30) wind speed (Tier 3 synthetic) with building outlines.
   python tools/demo_synthetic_slice.py [scenario.json] [out.png]"""
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import Rectangle

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from engine.backend import to_numpy  # noqa: E402
from engine.scenario.schema import load_scenario  # noqa: E402
from engine.wind.factory import make_wind  # noqa: E402

root = Path(__file__).resolve().parents[1]
sc = load_scenario(sys.argv[1] if len(sys.argv) > 1 else root / "scenarios/block_small.json")
out = Path(sys.argv[2]) if len(sys.argv) > 2 else root / "runs/synthetic_slice_z30.png"
out.parent.mkdir(parents=True, exist_ok=True)
wind = make_wind("synthetic", sc.layout, sc.inflow)
wind.step(40)
sl = to_numpy(wind.slice_z(30.0))
speed = np.linalg.norm(sl, axis=2)
fig, ax = plt.subplots(figsize=(8, 6))
im = ax.imshow(speed.T, origin="lower", extent=(0, sc.layout.area_m[0], 0, sc.layout.area_m[1]), cmap="viridis")
for b in sc.layout.buildings:
    ax.add_patch(Rectangle((b.x, b.y), b.w, b.d, fill=False, ec="w", lw=1.5))
    ax.text(b.cx, b.cy, f"{b.h:g} m", color="w", ha="center", va="center", fontsize=8)
ax.set_title(f"Tier 3 synthetic wind, |u| at z=30 m, inflow {sc.inflow.speed_ms} m/s @ {sc.inflow.direction_deg}°")
ax.set_xlabel("x [m]"); ax.set_ylabel("y [m]")
fig.colorbar(im, label="m/s")
fig.savefig(out, dpi=120, bbox_inches="tight")
print("saved", out)
