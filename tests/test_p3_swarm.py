import numpy as np
import pytest

from engine import backend
from engine.backend import to_numpy, xp
from engine.scenario.schema import Building, Inflow, Layout, SimSettings
from engine.swarm import grid as G
from engine.swarm.drones import Drones
from engine.wind.factory import make_wind

BOUNDS = (400.0, 300.0, 120.0)


class StillAir:
    def sample(self, pos):
        return xp.zeros((len(pos), 3), xp.float32)


class UniformWind:
    def __init__(self, u):
        self.u = np.asarray(u, np.float32)

    def sample(self, pos):
        return xp.asarray(np.tile(self.u, (len(pos), 1)))


def rand_pos(n, seed=0):
    return np.random.default_rng(seed).uniform([0, 0, 0], BOUNDS, (n, 3)).astype(np.float32)


def test_grid_equals_naive_2k():
    pos = rand_pos(2000, 1)
    r = 12.0     # large radius so there are plenty of pairs
    gi, gj, gd = (to_numpy(a) for a in G.pairs_grid(pos, r, G.Grid(BOUNDS, r)))
    ni, nj, nd = (to_numpy(a) for a in G.pairs_naive(pos, r))
    assert len(gi) > 100
    np.testing.assert_array_equal(gi, ni)
    np.testing.assert_array_equal(gj, nj)
    np.testing.assert_array_equal(gd, nd)


def test_grid_equals_naive_clustered_and_edges():
    rng = np.random.default_rng(5)
    pos = np.concatenate([rng.normal([200, 150, 40], 6, (800, 3)), rng.uniform(0, 400, (200, 3)) * [1, .75, .3],
                          np.array([[0, 0, 0], [399.9, 299.9, 119.9], [0.5, 0.5, 0.5]])]).astype(np.float32)
    pos = np.clip(pos, 0, np.array(BOUNDS, np.float32) - 1e-3)
    for r in (3.0, 6.0):
        a = [to_numpy(x) for x in G.pairs_grid(pos, r, G.Grid(BOUNDS, r))]
        b = [to_numpy(x) for x in G.pairs_naive(pos, r)]
        for x, y in zip(a, b):
            np.testing.assert_array_equal(x, y)


def test_grid_counts_histogram_scan():
    pos = rand_pos(500, 2)
    g = G.Grid(BOUNDS, 6.0)
    b = g.build(pos)
    counts, starts, order = (to_numpy(b[k]) for k in ("counts", "starts", "order"))
    assert counts.sum() == 500 and starts[0] == 0
    np.testing.assert_array_equal(starts[1:], np.cumsum(counts)[:-1])
    assert sorted(order.tolist()) == list(range(500))
    cid = to_numpy(b["cid"])
    assert (np.diff(cid[order]) >= 0).all()                   # grouped by cell
    for c in np.nonzero(counts)[0][:20]:                      # stable: ids ascending inside a cell
        seg = order[starts[c]:starts[c] + counts[c]]
        assert (np.diff(seg) > 0).all()


def fly(wind, start, goal, steps=3000, params=None, n=1):
    d = Drones(n, BOUNDS, params or SimSettings())
    d.place(0, start)
    d.set_path(0, [goal])
    for _ in range(steps):
        d.step(0.05, wind)
        if bool(d.arrived[0]):
            break
    return d


def test_reach_waypoints_in_still_air():
    d = Drones(1, BOUNDS)
    d.place(0, [10, 10, 0])
    d.set_path(0, [[10, 10, 30], [100, 10, 30], [100, 100, 30], [100, 100, 0]])
    steps = 0
    while not bool(d.arrived[0]) and steps < 6000:
        d.step(0.05, StillAir()); steps += 1
    assert bool(d.arrived[0])
    assert np.linalg.norm(to_numpy(d.pos[0]) - [100, 100, 0]) < 3.01
    assert 20 < steps * 0.05 < 120


def test_drift_under_crosswind():
    # fly along +x at z=30 with wind in +y: the drone must be pushed off the straight line
    d = Drones(1, BOUNDS); d.place(0, [10, 100, 30]); d.set_path(0, [[350, 100, 30]])
    ys = []
    for _ in range(3000):
        d.step(0.05, UniformWind([0, 6, 0])); ys.append(float(d.pos[0, 1]))
        if bool(d.arrived[0]):
            break
    assert max(abs(np.array(ys) - 100)) > 1.0
    d0 = Drones(1, BOUNDS); d0.place(0, [10, 100, 30]); d0.set_path(0, [[350, 100, 30]])
    for _ in range(3000):
        d0.step(0.05, StillAir())
        if bool(d0.arrived[0]):
            break
    assert abs(float(d0.pos[0, 1]) - 100) < 1e-3          # no wind, no drift


def test_energy_and_headwind_cost():
    still = fly(StillAir(), [10, 100, 30], [350, 100, 30], 6000)
    head = fly(UniformWind([-6, 0, 0]), [10, 100, 30], [350, 100, 30], 9000)
    tail = fly(UniformWind([6, 0, 0]), [10, 100, 30], [350, 100, 30], 6000)
    assert float(head.energy[0]) > float(still.energy[0]) > float(tail.energy[0])


def test_separation_and_near_collision_counted_once():
    d = Drones(2, BOUNDS, SimSettings())
    d.place(0, [100, 100, 30]); d.place(1, [101, 100, 30])        # 1 m apart: inside d_near = 2 m
    d.set_path(0, [[100, 100, 30]]); d.set_path(1, [[101, 100, 30]])
    d.step(0.05, StillAir())
    assert d.near_events == 1 and bool(d.near_flag[0]) and bool(d.near_flag[1])
    for _ in range(3):
        d.step(0.05, StillAir())
    assert d.near_events <= 2 and int(d.near_count[0]) == int(d.near_count[1]) == d.near_events
    assert float(d.pos[0, 0]) < 100 and float(d.pos[1, 0]) > 101    # pushed apart


def test_inactive_drones_are_frozen_and_ignored():
    d = Drones(3, BOUNDS)
    for i in range(3):
        d.place(i, [50, 50, 0])
    d.set_path(0, [[200, 50, 30]])
    p0 = to_numpy(d.pos).copy()
    d.step(0.05, StillAir())
    assert d.near_events == 0
    np.testing.assert_array_equal(to_numpy(d.pos)[1:], p0[1:])


def test_grid_and_naive_dynamics_agree():
    def run(use_grid):
        d = Drones(300, BOUNDS, SimSettings(), use_grid=use_grid)
        pos = rand_pos(300, 4) * [0.25, 0.3, 0.2] + [100, 100, 20]
        for i in range(300):
            d.place(i, pos[i]); d.set_path(i, [[120, 120, 30]])
        for _ in range(40):
            d.step(0.05, StillAir())
        return to_numpy(d.pos), d.near_events
    (a, na), (b, nb) = run(True), run(False)
    np.testing.assert_allclose(a, b, atol=1e-4)
    assert na == nb and na > 0


def test_deterministic_with_synthetic_wind():
    lay = Layout((400.0, 300.0), (Building(0, 150, 100, 40, 40, 50),))
    def run():
        w = make_wind("synthetic", lay, Inflow(8, 0, 0.5))
        d = Drones(50, BOUNDS)
        pos = rand_pos(50, 9) * [0.2, 1, 0.4] + [5, 0, 10]
        for i in range(50):
            d.place(i, pos[i]); d.set_path(i, [[350, 150, 30]])
        for _ in range(200):
            w.step(1); d.step(0.05, w)
        return to_numpy(d.pos), to_numpy(d.energy)
    a, b = run(), run()
    np.testing.assert_array_equal(a[0], b[0]); np.testing.assert_array_equal(a[1], b[1])


@pytest.mark.gpu
def test_gpu_kernel_matches_xp_path():
    if not backend.is_gpu:
        pytest.skip("no CUDA device / cupy")
    p = rand_pos(2000, 3) * [0.3, 0.3, 0.3] + [100, 100, 20]
    g = G.Grid(BOUNDS, 6.0)
    acc, near = G.separation_gpu(xp.asarray(p), g, 6.0, 6.0, 2.0)
    d = Drones(2000, BOUNDS, use_kernel=False)
    acc_ref, near_ref, _ = d._separation(xp.asarray(p))
    np.testing.assert_allclose(to_numpy(acc), to_numpy(acc_ref), rtol=1e-4, atol=1e-4)
    np.testing.assert_array_equal(to_numpy(near), to_numpy(near_ref))
