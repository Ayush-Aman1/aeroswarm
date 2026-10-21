import dataclasses
import json
from pathlib import Path

import numpy as np
import pytest

from engine.metrics.metrics import read_metrics_csv
from engine.protocol import read_replay
from engine.scenario import compare as cmp
from engine.scenario import runner
from engine.scenario.schema import Building, Layout, Mission, load_scenario

ROOT = Path(__file__).resolve().parents[1]


def small(n=6, **sim):
    sc = load_scenario(ROOT / "scenarios/block_small.json")
    sc = dataclasses.replace(sc, missions=sc.missions[:n],
                             sim=dataclasses.replace(sc.sim, start_window_s=10.0, **sim))
    return sc


def test_run_writes_all_outputs(tmp_path):
    s = runner.run(small(), "synthetic", "naive", 1, 150.0, tmp_path / "r", quiet=True)
    for f in ("config.json", "metrics.csv", "summary.json", "replay.bin"):
        assert (tmp_path / "r" / f).stat().st_size > 0
    assert s["completed"] == 6 and s["failed"] == 0
    cfg = json.loads((tmp_path / "r/config.json").read_text())
    assert cfg["routing"] == "naive" and cfg["seed"] == 1 and cfg["wind_tier"] == 3
    rows = read_metrics_csv(tmp_path / "r/metrics.csv")
    assert len(rows) == 6 and all(r["status"] == "completed" for r in rows)
    assert all(0 < float(r["delivery_s"]) < float(r["total_s"]) for r in rows)
    assert all(float(r["energy"]) > 0 for r in rows)


def test_replay_every_half_second(tmp_path):
    runner.run(small(2), "synthetic", "naive", 1, 20.0, tmp_path / "r", quiet=True)
    frames = read_replay(tmp_path / "r/replay.bin")
    assert len(frames) >= 30
    dts = np.diff([f.sim_time for f in frames])
    assert np.allclose(dts, 0.5, atol=1e-3)
    assert frames[0].drone_pos.shape == (2, 3) and frames[0].tracers.shape == (0, 3)


@pytest.mark.parametrize("routing", ["naive", "aware"])
def test_same_seed_same_metrics_twice(tmp_path, routing):
    a = runner.run(small(), "synthetic", routing, 3, 90.0, tmp_path / "a", replay=False, quiet=True)
    b = runner.run(small(), "synthetic", routing, 3, 90.0, tmp_path / "b", replay=False, quiet=True)
    assert (tmp_path / "a/metrics.csv").read_bytes() == (tmp_path / "b/metrics.csv").read_bytes()
    for k in a:
        if k != "wall_s":
            assert a[k] == b[k] or (isinstance(a[k], float) and np.isnan(a[k]) and np.isnan(b[k]))


def test_different_seed_changes_start_times(tmp_path):
    runner.run(small(), "synthetic", "naive", 1, 60.0, tmp_path / "a", replay=False, quiet=True)
    runner.run(small(), "synthetic", "naive", 2, 60.0, tmp_path / "b", replay=False, quiet=True)
    sa = [r["start_s"] for r in read_metrics_csv(tmp_path / "a/metrics.csv")]
    sb = [r["start_s"] for r in read_metrics_csv(tmp_path / "b/metrics.csv")]
    assert sa != sb


def test_unreachable_target_is_failed_not_crash(tmp_path):
    sc = small(2)
    lay = Layout(sc.layout.area_m, sc.layout.buildings + (Building(10, 300, 100, 60, 20, 105), Building(11, 300, 180, 60, 20, 105),
                                                     Building(12, 280, 120, 20, 60, 105), Building(13, 360, 120, 20, 60, 105)))
    sc = dataclasses.replace(sc, layout=lay, missions=(Mission(0, 0, (340.0, 150.0)), sc.missions[1]))
    s = runner.run(sc, "synthetic", "naive", 1, 100.0, tmp_path / "r", replay=False, quiet=True)
    rows = {r["mission"]: r for r in read_metrics_csv(tmp_path / "r/metrics.csv")}
    assert rows["0"]["status"] == "failed"
    assert s["failed"] == 1 and s["completed"] == 1


def test_compare_pairs_runs(tmp_path):
    for r in ("naive", "aware"):
        runner.run(small(), "synthetic", r, 1, 150.0, tmp_path / r, replay=False, quiet=True)
    res = cmp.compare(tmp_path / "naive", tmp_path / "aware", tmp_path / "out", quiet=True)
    assert res["delivery_s"]["n"] == 6
    assert (tmp_path / "out/compare.png").stat().st_size > 2000


def test_aware_uses_weights_and_naive_does_not():
    sc = small(1)
    n = runner.Simulation(sc, wind_name="synthetic", routing="naive")
    a = runner.Simulation(sc, wind_name="synthetic", routing="aware")
    assert n.planner.weights == (0, 0, 0) and a.planner.weights == (sc.sim.w_head, sc.sim.w_gust, sc.sim.w_cross)
    a.set_routing("naive")
    assert a.planner.weights == (0, 0, 0)


def test_layout_change_commits_at_step_boundary_and_replans():
    sc = small(4)
    sim = runner.Simulation(sc, wind_name="synthetic", routing="naive")
    for _ in range(200):
        sim.step()
    b = sc.layout.get(1)
    new = Layout(sc.layout.area_m, tuple(dataclasses.replace(x, x=x.x + 20) if x.id == 1 else x
                                         for x in sc.layout.buildings))
    sim.begin_layout_change(new)
    assert sim.settling and sim.layout_version == 0
    sim.step()
    assert not sim.settling and sim.layout_version == 1 and sim.planner.layout.get(1).x == b.x + 20
    types = [e["type"] for e in sim.events]
    assert types.count("layout_commit") == 1 and types[0] == "settling"
