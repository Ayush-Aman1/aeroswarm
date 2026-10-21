"""Simulation (shared by the headless runner and the live service) + CLI.

    python -m engine.scenario.runner scenarios/block_small.json --wind synthetic --routing naive|aware \
        --seed 1 --headless --duration 300

Missions are depot -> target -> depot, one drone per mission. Start times and the wind's initial phase come
from the seed, so same scenario + seed => same metrics (CPU path exactly). Runs write runs/<timestamp>/
{config.json, metrics.csv, summary.json, replay.bin}.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import time
from collections import deque
from datetime import datetime
from pathlib import Path

import numpy as np

from engine import backend
from engine.backend import to_numpy, xp
from engine.metrics.metrics import Metrics, write_metrics_csv, write_summary
from engine.planner.astar import AsyncReplanner, GridPlanner
from engine.protocol import Snapshot, write_replay_frame
from engine.scenario.schema import Inflow, Layout, Scenario, load_scenario
from engine.swarm.drones import Drones
from engine.wind.factory import make_wind

IDLE, OUTBOUND, DELIVERING, RETURNING, DONE = 0, 1, 2, 3, 4
NEAR_BIT = 8
STATS_DT_S = 2.0          # wind snapshot period for the planner's gust statistics
K_SNAPSHOTS = 10
SPINUP_S = STATS_DT_S * K_SNAPSHOTS
REPLAN_BATCH = 3          # drones replanned per step (staggered so no step stalls)
REPLAY_EVERY_S = 0.5


def trim_behind(pos, wps):
    """Drop leading waypoints the drone has already passed (a replan snaps to a cell centre that may lie
    behind the drone; flying back to it would waste time on every replan)."""
    wps = np.asarray(wps, np.float32)
    pos = np.asarray(pos, np.float32)
    while len(wps) > 1 and float(np.dot(wps[1] - wps[0], pos - wps[0])) > 0.0:
        wps = wps[1:]
    # waypoint 0 = where the drone is now, so the segment it flies (for the cross-track metric) is well defined
    return np.concatenate([pos[None, :], wps])


def routing_weights(sc: Scenario, routing: str):
    s = sc.sim
    return (s.w_head, s.w_gust, s.w_cross) if routing == "aware" else (0.0, 0.0, 0.0)


class Simulation:
    def __init__(self, sc: Scenario, wind=None, routing: str | None = None, seed: int | None = None,
                 wind_name: str | None = None, continuous: bool = False, async_planner: bool = False,
                 wind_cfg: dict | None = None):
        self.sc = sc
        self.seed = sc.seed if seed is None else seed
        self.routing = routing or sc.sim.routing
        self.dt = sc.sim.dt
        self.continuous = continuous
        self.layout: Layout = sc.layout
        self.inflow: Inflow = sc.inflow
        self.layout_version = 0
        self.rng = np.random.default_rng(self.seed)
        self.wind = wind if wind is not None else make_wind(wind_name or sc.sim.tier, self.layout, self.inflow,
                                                           self.dt, **(wind_cfg or {}))
        n = len(sc.missions)
        self.n = n
        self.drones = Drones(n, self.layout.bounds_m, sc.sim)
        self.metrics = Metrics(n)
        self.planner = GridPlanner(self.layout, routing_weights(sc, self.routing), v_cruise=sc.sim.cruise_ms,
                                   k_snapshots=K_SNAPSHOTS)
        self.replanner = AsyncReplanner(self.planner) if async_planner else None
        self.phase = np.zeros(n, np.int8)
        self.start_t = np.zeros(n)
        self.deliver_t = np.full(n, np.nan)
        self.deliver_until = np.zeros(n)
        self.leg_epoch = np.zeros(n, int)
        self.spawn = np.zeros((n, 3))
        self.targets = np.array([[m.target[0], m.target[1], 0.0] for m in sc.missions]).reshape(-1, 3)
        self.live = {"delivered": 0, "delivery_sum": 0.0, "energy_sum": 0.0, "drift_sum": 0.0, "completed": 0}
        self.t = 0.0
        self.step_count = 0
        self._next_obs = 0.0
        self._next_replan = sc.sim.replan_s
        self._replan_queue: deque = deque()
        self._pending_layout: tuple[Layout, Inflow] | None = None
        self.events: list[dict] = []          # drained by the service (toasts, layout commits)
        self._init_missions()
        self._spin_up()

    # ------------------------------------------------------------------ setup
    def _init_missions(self):
        per_depot: dict[int, int] = {}
        starts = self.rng.uniform(0.0, self.sc.sim.start_window_s, self.n)
        for i, m in enumerate(self.sc.missions):
            d = self.sc.depot(m.depot)
            k = per_depot.get(m.depot, 0)
            per_depot[m.depot] = k + 1
            ang, rad = k * 2.399963, 2.0 + 1.5 * (k // 8)     # golden-angle ring around the depot
            self.spawn[i] = (d.x + rad * np.cos(ang), d.y + rad * np.sin(ang), 0.0)
            self.drones.place(i, self.spawn[i])
            self.start_t[i] = starts[i]

    def _spin_up(self):
        """Advance the wind (same for every routing mode) so gust stats exist and the wake phase depends on
        the seed; observe on the way."""
        offset = float(self.rng.uniform(0.0, 30.0))
        steps = int(round((SPINUP_S + offset) / self.dt))
        obs_every = int(round(STATS_DT_S / self.dt))
        for k in range(steps):
            self.wind.step(1)
            if k >= steps - K_SNAPSHOTS * obs_every and k % obs_every == 0:
                self.planner.observe(self.wind)
        self.planner.refresh()

    # ------------------------------------------------------------------ planning helpers
    def _goal(self, i):
        return self.targets[i] if self.phase[i] == OUTBOUND else self.spawn[i]

    def _plan(self, i, start, goal, apply_now: bool):
        if self.replanner is not None and not apply_now:
            self.replanner.submit(i, start, goal, tag=int(self.leg_epoch[i]))
            return None
        return self.planner.plan(start, goal)

    def _begin_leg(self, i, start):
        """Plan + install the path for drone i's current phase leg. Synchronous in headless runs (deterministic);
        with the async planner the leg is planned on the worker thread and the drone waits on the ground/at the
        target until the path arrives at a step boundary (_apply_async_results)."""
        goal = self._goal(i)
        self.leg_epoch[i] += 1
        if self.replanner is not None:
            self.drones.active[i] = False
            self.replanner.submit(i, np.asarray(start, float), goal, tag=int(self.leg_epoch[i]))
            return True
        wps = self.planner.plan(start, goal)
        if wps is None:
            return False
        self.drones.set_path(i, wps)
        return True

    # ------------------------------------------------------------------ stepping
    def step(self) -> None:
        dt, pr = self.dt, self.sc.sim
        self._apply_async_results()
        self._maybe_commit_layout()
        # wind statistics / replanning schedule
        if self.t >= self._next_obs:
            self.planner.observe(self.wind)
            self._next_obs += STATS_DT_S
        if self.t >= self._next_replan:
            self._next_replan += pr.replan_s
            if self.routing == "aware":
                self.planner.refresh()
                self._replan_queue = deque(i for i in range(self.n) if self.phase[i] in (OUTBOUND, RETURNING))
        for _ in range(min(REPLAN_BATCH, len(self._replan_queue))):
            i = self._replan_queue.popleft()
            if self.phase[i] in (OUTBOUND, RETURNING):
                self._replan_drone(i)
        # mission starts
        for i in np.nonzero((self.phase == IDLE) & (self.start_t <= self.t))[0]:
            self.phase[i] = OUTBOUND
            self.metrics.reset_drone(i)
            self.drones.energy[i] = 0.0
            self.drones.near_count[i] = 0
            self.start_t[i] = self.t
            if not self._begin_leg(i, self.spawn[i]):
                self.phase[i] = DONE
                self.metrics.close_mission(i, self.sc.missions[i], self.start_t[i], "failed", None, None, self.drones)
        # dynamics
        self.wind.step(1)
        self.drones.step(dt, self.wind)
        idx = xp.nonzero(self.drones.active)[0]
        self.metrics.update(self.drones, idx)
        self.t += dt
        self.step_count += 1
        # events
        arrived = np.nonzero(to_numpy(self.drones.arrived) & to_numpy(self.drones.active))[0]
        for i in arrived:
            ph = self.phase[i]
            if ph == OUTBOUND:
                self.phase[i] = DELIVERING
                self.deliver_t[i] = self.t - self.start_t[i]
                self.deliver_until[i] = self.t + pr.deliver_s
            elif ph == RETURNING:
                self._complete(i)
        for i in np.nonzero((self.phase == DELIVERING) & (self.deliver_until <= self.t))[0]:
            self.phase[i] = RETURNING
            pos = to_numpy(self.drones.pos[i]).astype(float)
            if not self._begin_leg(i, pos):
                self.drones.active[i] = False
                self.phase[i] = DONE
                self.metrics.close_mission(i, self.sc.missions[i], self.start_t[i], "stranded",
                                           self.deliver_t[i], None, self.drones)

    def _replan_drone(self, i):
        pos = to_numpy(self.drones.pos[i]).astype(float)
        goal = self._goal(i)
        if self.replanner is not None:
            self.replanner.submit(i, pos, goal, tag=int(self.leg_epoch[i]))
            return
        wps = self.planner.plan(pos, goal)
        if wps is not None:
            self.drones.set_path(i, trim_behind(pos, wps))

    def _apply_async_results(self):
        if self.replanner is None:
            return
        for key, tag, res in self.replanner.collect():
            if tag != self.leg_epoch[key] or self.phase[key] not in (OUTBOUND, RETURNING):
                continue                                        # stale result: the drone moved on to another leg
            if isinstance(res, np.ndarray):
                pos = to_numpy(self.drones.pos[key])
                self.drones.set_path(key, trim_behind(pos, res))   # atomic swap at the step boundary
            elif not bool(self.drones.active[key]):             # a leg that could not be planned at all
                self.phase[key] = DONE
                self.metrics.close_mission(key, self.sc.missions[key], self.start_t[key],
                                           "failed" if self.deliver_t[key] != self.deliver_t[key] else "stranded",
                                           None if self.deliver_t[key] != self.deliver_t[key] else self.deliver_t[key],
                                           None, self.drones)

    def _complete(self, i):
        t_total = self.t - self.start_t[i]
        self.drones.active[i] = False
        self.drones.vel[i] = 0
        self.phase[i] = DONE
        self.metrics.close_mission(i, self.sc.missions[i], self.start_t[i], "completed", self.deliver_t[i],
                                   t_total, self.drones)
        row = self.metrics.rows[-1]
        self.live["completed"] += 1
        self.live["delivered"] += 1
        self.live["delivery_sum"] += self.deliver_t[i]
        self.live["energy_sum"] += row["energy"]
        self.live["drift_sum"] += row["drift_mean"]
        if self.continuous:                               # re-arm: new mission after a short pause
            self.phase[i] = IDLE
            self.start_t[i] = self.t + float(self.rng.uniform(1.0, 15.0))
            self.drones.place(i, self.spawn[i])

    # ------------------------------------------------------------------ layout changes
    def begin_layout_change(self, layout: Layout | None = None, inflow: Inflow | None = None) -> None:
        layout = layout or self.layout
        inflow = inflow or self.inflow
        self._pending_layout = (layout, inflow)
        self.wind.begin_relayout(layout, inflow)
        self.events.append({"type": "settling", "pending": True})

    def _maybe_commit_layout(self):
        if self._pending_layout is None or not self.wind.relayout_ready():
            return
        layout, inflow = self._pending_layout
        self._pending_layout = None
        self.wind.commit_relayout()                       # at a step boundary
        self.layout_version += 1
        self.layout = Layout(layout.area_m, layout.buildings, layout.ceiling_m, self.layout_version)
        self.inflow = inflow
        self.planner.set_layout(self.layout)
        self.planner.refresh()
        for i in range(self.n):
            if self.phase[i] in (OUTBOUND, RETURNING):
                self._replan_drone(i)
        self.events.append({"type": "layout_commit", "version": self.layout_version})
        self.events.append({"type": "settling", "pending": False})

    @property
    def settling(self) -> bool:
        return self._pending_layout is not None

    def set_routing(self, routing: str) -> None:
        assert routing in ("naive", "aware")
        self.routing = routing
        self.planner.set_weights(routing_weights(self.sc, routing))
        self._replan_queue = deque(i for i in range(self.n) if self.phase[i] in (OUTBOUND, RETURNING))

    # ------------------------------------------------------------------ outputs
    def all_done(self) -> bool:
        return bool((self.phase == DONE).all())

    def states(self) -> np.ndarray:
        s = self.phase.astype(np.uint8)
        return s | (to_numpy(self.drones.near_flag).astype(np.uint8) * NEAR_BIT)

    def snapshot(self, tracers=None, slice_speed=None, slice_z: float = 0.0, flags: int = 0) -> Snapshot:
        pos, vel = self.drones.snapshot_arrays()
        return Snapshot(self.step_count, self.t, self.layout_version, pos, vel, self.states(),
                        np.zeros((0, 3), np.float32) if tracers is None else tracers,
                        np.zeros((0, 0), np.float16) if slice_speed is None else slice_speed, slice_z, flags)

    def live_metrics(self) -> dict:
        lv = self.live
        c = max(lv["completed"], 1)
        return dict(delivered=lv["delivered"], completed=lv["completed"],
                    mean_delivery_s=(lv["delivery_sum"] / c) if lv["completed"] else 0.0,
                    energy=(lv["energy_sum"] / c) if lv["completed"] else 0.0,
                    drift_mean=(lv["drift_sum"] / c) if lv["completed"] else 0.0,
                    near_collisions=int(self.drones.near_events),
                    active=int(to_numpy(self.drones.active).sum()))

    def finalize_rows(self) -> list[dict]:
        """Close still-open missions as 'incomplete' (headless end of run)."""
        done_ids = {r["mission"] for r in self.metrics.rows}
        for i, m in enumerate(self.sc.missions):
            if m.id in done_ids:
                continue
            if self.phase[i] == IDLE:
                self.metrics.rows.append(dict(mission=m.id, drone=i, depot=m.depot, start_s="", status="not_started",
                                              delivery_s="", total_s="", energy=0.0, drift_mean=0.0, drift_max=0.0,
                                              near_collisions=0))
            else:
                dl = None if np.isnan(self.deliver_t[i]) else self.deliver_t[i]
                self.metrics.close_mission(i, m, self.start_t[i], "incomplete", dl, None, self.drones)
        return self.metrics.rows

    def close(self):
        if self.replanner is not None:
            self.replanner.close()


# ---------------------------------------------------------------------------------------- headless
def _git_rev() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], stderr=subprocess.DEVNULL,
                                       cwd=Path(__file__).resolve().parents[2]).decode().strip()
    except Exception:  # noqa: BLE001
        return "unknown"


def run(sc: Scenario, wind_name: str = "synthetic", routing: str = "naive", seed: int | None = None,
        duration_s: float | None = None, out_dir: str | Path | None = None, replay: bool = True,
        wind_cfg: dict | None = None, quiet: bool = False) -> dict:
    seed = sc.seed if seed is None else seed
    duration_s = sc.sim.duration_s if duration_s is None else duration_s
    if out_dir is None:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        out_dir = Path("runs") / f"{stamp}_{sc.name}_{wind_name}_{routing}_s{seed}"
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    t0 = time.perf_counter()
    sim = Simulation(sc, routing=routing, seed=seed, wind_name=wind_name, wind_cfg=wind_cfg)
    config = dict(scenario=sc.to_dict(), wind=wind_name, wind_cfg=wind_cfg or {}, routing=routing, seed=seed,
                  duration_s=duration_s, backend=backend.backend_name, git=_git_rev(), numpy=np.__version__,
                  wind_tier={"synthetic": 3, "fluidx3d": 2, "lbmpy": 1}.get(wind_name, wind_name))
    (out_dir / "config.json").write_text(json.dumps(config, indent=1))
    fh = open(out_dir / "replay.bin", "wb") if replay else None
    replay_every = max(1, int(round(REPLAY_EVERY_S / sc.sim.dt)))
    n_steps = int(round(duration_s / sc.sim.dt))
    try:
        for k in range(n_steps):
            sim.step()
            if fh is not None and k % replay_every == 0:
                write_replay_frame(fh, sim.snapshot())
            if sim.all_done():
                break
    finally:
        if fh is not None:
            fh.close()
        sim.close()
    rows = sim.finalize_rows()
    summary = Metrics.summarise(rows, sim.n, sim.drones.near_events)
    summary.update(routing=routing, wind=wind_name, seed=seed, sim_time_s=round(sim.t, 3),
                   wall_s=round(time.perf_counter() - t0, 2), backend=backend.backend_name)
    write_metrics_csv(out_dir / "metrics.csv", rows)
    write_summary(out_dir / "summary.json", summary)
    if not quiet:
        print(f"[{wind_name}/{routing}/seed {seed}] completed {summary['completed']}/{sim.n} in {sim.t:.0f} s sim "
              f"({summary['wall_s']} s wall) | delivery {summary['mean_delivery_s']:.1f} s | energy "
              f"{summary['energy_mean']:.0f} | drift {summary['drift_mean']:.2f} m | near-coll "
              f"{summary['near_collisions']} -> {out_dir}")
    return summary


def main(argv=None) -> dict:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("scenario")
    ap.add_argument("--wind", default=None, help="synthetic | fluidx3d | lbmpy (default: scenario sim.tier)")
    ap.add_argument("--routing", choices=["naive", "aware"], default=None)
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--headless", action="store_true", help="no viewer (the runner is always headless)")
    ap.add_argument("--duration", type=float, default=None, help="max simulated seconds")
    ap.add_argument("--out", default=None, help="output folder (default runs/<timestamp>...)")
    ap.add_argument("--no-replay", action="store_true")
    ap.add_argument("--wind-cfg", default=None, help="JSON dict of adapter options, e.g. '{\"field_dir\": \"data/fields\"}'")
    a = ap.parse_args(argv)
    sc = load_scenario(a.scenario)
    return run(sc, a.wind or sc.sim.tier, a.routing or sc.sim.routing, a.seed, a.duration, a.out,
               replay=not a.no_replay, wind_cfg=json.loads(a.wind_cfg) if a.wind_cfg else None)


if __name__ == "__main__":
    main()
