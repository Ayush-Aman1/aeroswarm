#!/usr/bin/env python3
"""Regenerate scenarios/*.json deterministically (buildings are hand-placed, missions are seeded)."""
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from engine.scenario.schema import scenario_from_dict  # noqa: E402

OUT = Path(__file__).resolve().parents[1] / "scenarios"

LAYOUTS = {
    # 6 buildings, 20-60 m tall, in a 400 x 300 m area (the guide's block_small)
    "block_small": [
        (110, 190, 40, 40, 60), (110, 70, 30, 50, 35), (200, 120, 50, 30, 50),
        (280, 200, 40, 40, 25), (280, 50, 35, 45, 40), (190, 230, 30, 30, 20),
    ],
    # two rows of mid-rise blocks forming a canyon along x
    "street_canyon": [
        (80, 60, 70, 40, 40), (180, 60, 70, 40, 55), (280, 60, 70, 40, 30),
        (80, 200, 70, 40, 50), (180, 200, 70, 40, 35), (280, 200, 70, 40, 60),
    ],
    # three towers and a low podium
    "tower_cluster": [
        (120, 120, 40, 40, 60), (200, 150, 30, 30, 55), (170, 60, 35, 35, 45),
        (270, 90, 50, 60, 22), (90, 220, 40, 40, 30), (300, 210, 30, 30, 50),
    ],
}
DEPOTS = {
    "block_small": [(30, 40), (30, 260)],
    "street_canyon": [(25, 150), (25, 30)],
    "tower_cluster": [(30, 40), (30, 260)],
}


def make(name: str, seed: int = 1, n_missions: int = 50) -> dict:
    rng = np.random.default_rng(1000 + sum(map(ord, name)))
    buildings = [dict(id=i, x=x, y=y, w=w, d=d, h=h) for i, (x, y, w, d, h) in enumerate(LAYOUTS[name])]
    depots = [dict(id=i, x=x, y=y) for i, (x, y) in enumerate(DEPOTS[name])]
    missions = []
    while len(missions) < n_missions:
        tx, ty = float(rng.uniform(150, 385)), float(rng.uniform(15, 285))
        if any(b["x"] - 8 <= tx <= b["x"] + b["w"] + 8 and b["y"] - 8 <= ty <= b["y"] + b["d"] + 8 for b in buildings):
            continue
        dep = len(missions) % len(depots)
        missions.append(dict(id=len(missions), depot=dep, target=[round(tx, 1), round(ty, 1)]))
    d = dict(name=name, seed=seed,
             layout=dict(area_m=[400, 300], ceiling_m=120, buildings=buildings),
             inflow=dict(speed_ms=8.0, direction_deg=0.0, roughness=0.5),
             depots=depots, missions=missions,
             sim=dict(dt=0.05, duration_s=300.0, tier="synthetic", routing="naive"))
    scenario_from_dict(d)  # validate
    return d


if __name__ == "__main__":
    for nm in LAYOUTS:
        with open(OUT / f"{nm}.json", "w") as fh:
            json.dump(make(nm), fh, indent=1)
            fh.write("\n")
        print("wrote", OUT / f"{nm}.json")
