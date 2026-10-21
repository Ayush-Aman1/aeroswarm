"""Per-mission and per-run metrics. Reductions use xp sums; host copies only at events / summary time.

Definitions
  delivery_s   : mission start -> drone reaches the delivery point (first arrival)
  total_s      : mission start -> back at the depot (only for completed missions)
  energy       : sum over steps of |thrust accel| * dt  (a proxy: m/s of delta-v spent; unit-mass drone)
  drift_mean/max: distance (m) from the drone to the planned segment it is currently flying (cross-track)
  near_collisions: events where a pair of drones comes within d_near (each pair once per encounter)
"""
from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field

import numpy as np

from engine.backend import to_numpy, xp

CSV_FIELDS = ["mission", "drone", "depot", "start_s", "status", "delivery_s", "total_s", "energy",
              "drift_mean", "drift_max", "near_collisions"]


def segment_distance(p, a, b):
    """Distance from points p to segments a-b (all [m,3] xp arrays)."""
    ab = b - a
    denom = xp.maximum((ab * ab).sum(axis=1), 1e-9)
    t = xp.clip(((p - a) * ab).sum(axis=1) / denom, 0.0, 1.0)
    return xp.linalg.norm(p - (a + t[:, None] * ab), axis=1)


class Metrics:
    def __init__(self, n: int):
        self.n = n
        self.drift_sum = xp.zeros(n, xp.float32)
        self.drift_max = xp.zeros(n, xp.float32)
        self.drift_steps = xp.zeros(n, xp.int32)
        self.rows: list[dict] = []        # finished (or force-closed) missions

    def update(self, drones, idx):
        """Accumulate cross-track drift for the active drones `idx` (xp int array)."""
        if idx.size == 0:
            return
        wp = drones.wp[idx]
        cur = drones.path[idx, wp]
        prev = drones.path[idx, xp.maximum(wp - 1, 0)]
        d = segment_distance(drones.pos[idx], prev, cur)
        self.drift_sum[idx] += d
        self.drift_max[idx] = xp.maximum(self.drift_max[idx], d)
        self.drift_steps[idx] += 1

    def reset_drone(self, i):
        self.drift_sum[i] = 0.0
        self.drift_max[i] = 0.0
        self.drift_steps[i] = 0

    def drift_of(self, i):
        steps = int(self.drift_steps[i])
        return (float(self.drift_sum[i]) / steps if steps else 0.0), float(self.drift_max[i])

    def close_mission(self, i, mission, start_s, status, delivery_s, total_s, drones):
        dm, dx = self.drift_of(i)
        self.rows.append(dict(
            mission=mission.id, drone=i, depot=mission.depot, start_s=round(start_s, 3), status=status,
            delivery_s=("" if delivery_s is None else round(delivery_s, 3)),
            total_s=("" if total_s is None else round(total_s, 3)),
            energy=round(float(drones.energy[i]), 3), drift_mean=round(dm, 3), drift_max=round(dx, 3),
            near_collisions=int(drones.near_count[i])))

    # ------------------------------------------------------------------ aggregation
    @staticmethod
    def summarise(rows: list[dict], n_missions: int, near_events: int) -> dict:
        done = [r for r in rows if r["status"] == "completed"]
        deliv = [r for r in rows if r["delivery_s"] != ""]
        def mean(xs):
            return float(np.mean(xs)) if xs else float("nan")
        return dict(
            n_missions=n_missions,
            completed=len(done),
            delivered=len(deliv),
            failed=sum(r["status"] == "failed" for r in rows),
            mean_delivery_s=mean([r["delivery_s"] for r in deliv]),
            mean_total_s=mean([r["total_s"] for r in done]),
            energy_mean=mean([r["energy"] for r in rows if r["status"] != "failed"]),
            drift_mean=mean([r["drift_mean"] for r in rows if r["status"] != "failed"]),
            drift_max=float(max([r["drift_max"] for r in rows], default=0.0)),
            near_collisions=int(near_events),
        )


def write_metrics_csv(path, rows):
    with open(path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=CSV_FIELDS)
        w.writeheader()
        for r in sorted(rows, key=lambda r: r["mission"]):
            w.writerow(r)


def read_metrics_csv(path):
    with open(path) as fh:
        return list(csv.DictReader(fh))


def write_summary(path, summary: dict):
    with open(path, "w") as fh:
        json.dump(summary, fh, indent=1, sort_keys=True)
