import math
import time

import numpy as np
import pytest
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import dijkstra

from engine.backend import xp
from engine.planner.astar import AsyncReplanner, GridPlanner, reachable
from engine.scenario.schema import Building, Layout, load_scenario

EMPTY = Layout((400.0, 300.0), ())
ONE = Layout((400.0, 300.0), (Building(0, 180, 120, 40, 40, 70),))


def path_len(w):
    return float(np.linalg.norm(np.diff(np.asarray(w, float), axis=0), axis=1).sum())


class BlobWind:
    """Stub WindSource: strong gusty headwind/crosswind blob; zero elsewhere (samples at cell centres)."""
    def __init__(self, centre, radius, u=(-8.0, 6.0, 0.0), gust=True):
        self.c, self.r, self.u, self.gust, self.t = np.array(centre, float), radius, np.array(u, float), gust, 0

    def sample(self, pos):
        P = np.asarray(pos, float)
        inside = np.linalg.norm(P - self.c, axis=1) < self.r
        scale = 1.0 + (0.8 * np.sin(self.t * 1.7) if self.gust else 0.0)
        out = np.zeros((len(P), 3), np.float32)
        out[inside] = (self.u * scale).astype(np.float32)
        return out


def test_naive_is_shortest_open_field():
    pl = GridPlanner(EMPTY)
    w = pl.plan((20, 20, 0), (380, 280, 0))
    straight = math.dist((20, 20), (380, 280))
    # 3D grid path = climb + cruise + descend; horizontal part within a few % of straight (26-connected)
    horiz = float(np.linalg.norm(np.diff(w[1:-1, :2], axis=0), axis=1).sum())
    assert straight <= horiz <= straight * 1.09
    assert w[0].tolist() == [20, 20, 0] and w[-1].tolist() == [380, 280, 0]


def test_astar_matches_dijkstra_optimum():
    pl = GridPlanner(ONE)
    cells, cost = pl.plan_cells((20, 150, 0), (380, 150, 0))
    # independent shortest path over the very same edge set
    rows, cols, wts = [], [], []
    idx = np.arange(pl.N)
    costs = pl._costs
    for k, delta in enumerate(costs.deltas):
        c = np.asarray(costs.cost[k])
        ok = np.isfinite(c)
        rows.append(idx[ok]); cols.append(idx[ok] + delta); wts.append(c[ok])
    g = coo_matrix((np.concatenate(wts), (np.concatenate(rows), np.concatenate(cols))), shape=(pl.N, pl.N)).tocsr()
    s, t = pl._flat(cells[0]), pl._flat(cells[-1])
    d = dijkstra(g, indices=s)[t]
    assert cost == pytest.approx(d, rel=1e-9)


def test_path_avoids_buildings_with_margin():
    sc = load_scenario("scenarios/block_small.json")
    pl = GridPlanner(sc.layout)
    for m in sc.missions[:20]:
        dep = sc.depot(m.depot)
        w = pl.plan((dep.x, dep.y, 0), (m.target[0], m.target[1], 0))
        assert w is not None
        for a, b in zip(w[:-1], w[1:]):
            for t in np.linspace(0, 1, 40):
                p = a + t * (b - a)
                for bl in sc.layout.buildings:
                    assert not (bl.x - 2.0 <= p[0] <= bl.x + bl.w + 2.0 and bl.y - 2.0 <= p[1] <= bl.y + bl.d + 2.0
                                and p[2] <= bl.h + 2.0), (m.id, p, bl)


def test_goes_over_low_building_around_tall():
    low = Layout((400.0, 300.0), (Building(0, 180, 130, 40, 40, 20),))
    w = GridPlanner(low).plan((20, 150, 0), (380, 150, 0))
    assert w[:, 2].max() >= 40               # climbs over the 20 m building (layer 40)
    tall = Layout((400.0, 300.0), (Building(0, 180, 130, 40, 40, 100),))
    w = GridPlanner(tall).plan((20, 150, 0), (380, 150, 0))
    assert np.ptp(w[:, 1]) > 20              # detours sideways around the 100 m tower


def test_wind_aware_bends_around_a_wake():
    straight = GridPlanner(EMPTY)
    base = straight.plan((20, 150, 0), (380, 150, 0))
    blob = BlobWind(centre=(200, 150, 50), radius=70)
    aware = GridPlanner(EMPTY, weights=(4.0, 6.0, 2.0))
    for _ in range(10):
        aware.observe(blob); blob.t += 2.0
    aware.refresh()
    w = aware.plan((20, 150, 0), (380, 150, 0))
    # naive path crosses the blob; aware path stays out of it (at cruise altitude)
    def min_dist(path):
        pts = [a + t * (b - a) for a, b in zip(path[:-1], path[1:]) for t in np.linspace(0, 1, 30)]
        return min(math.dist(p, blob.c) for p in pts if p[2] > 5)
    assert min_dist(base) < 70
    assert min_dist(w) >= 70 - 1e-6
    assert path_len(w) > path_len(base)      # longer, but avoids the wake
    # a=b=c=0 reproduces the naive planner exactly
    naive_again = GridPlanner(EMPTY, weights=(0, 0, 0))
    for _ in range(10):
        naive_again.observe(blob)
    naive_again.refresh()
    np.testing.assert_array_equal(naive_again.plan((20, 150, 0), (380, 150, 0)), base)


def test_blocked_and_enclosed_targets_unreachable():
    pl = GridPlanner(ONE)
    assert pl.plan((20, 150, 0), (200, 140, 0)) is None            # target inside the building
    assert not pl.reachable((20, 150), (200, 140))
    ring = Layout((400.0, 300.0), (
        Building(0, 250, 100, 60, 20, 105), Building(1, 250, 180, 60, 20, 105),
        Building(2, 230, 120, 20, 60, 105), Building(3, 310, 120, 20, 60, 105)))
    assert not reachable(ring, (20, 150), (290, 150))               # walled in by 105 m towers
    assert reachable(ring, (20, 150), (30, 30))
    assert reachable(ONE, (20, 150), (380, 150))


def test_all_scenario_missions_reachable():
    for name in ("block_small", "street_canyon", "tower_cluster"):
        sc = load_scenario(f"scenarios/{name}.json")
        pl = GridPlanner(sc.layout)
        for m in sc.missions:
            d = sc.depot(m.depot)
            assert pl.reachable((d.x, d.y), m.target), (name, m.id)


def test_layout_change_updates_blocking():
    pl = GridPlanner(EMPTY)
    assert pl.plan((20, 150, 0), (380, 150, 0)) is not None
    pl.set_layout(Layout((400.0, 300.0), (Building(0, 170, 60, 60, 180, 105),), version=1))
    w = pl.plan((20, 150, 0), (380, 150, 0))
    assert w is not None            # 105 m wall spans y 60..240: the route must go around its ends
    assert (w[:, 1] < 55).any() or (w[:, 1] > 245).any()


def test_async_replanner_swaps_results_at_collect():
    pl = GridPlanner(ONE)
    rp = AsyncReplanner(pl)
    try:
        for k in range(5):
            rp.submit(k, (20, 150, 0), (380, 150 + k, 0), tag="x")
        t0, got = time.time(), []
        while len(got) < 5 and time.time() - t0 < 20:
            got += rp.collect(); time.sleep(0.02)
        assert sorted(k for k, _, _ in got) == list(range(5))
        assert all(isinstance(r, np.ndarray) for _, _, r in got)
    finally:
        rp.close()


def test_planning_speed_reasonable():
    sc = load_scenario("scenarios/block_small.json")
    pl = GridPlanner(sc.layout, weights=(4, 6, 2))
    blob = BlobWind((200, 150, 40), 60)
    for _ in range(10):
        pl.observe(blob); blob.t += 2
    pl.refresh()
    t0 = time.perf_counter()
    for _ in range(5):
        pl.plan((30, 40, 0), (380, 260, 0))
    assert (time.perf_counter() - t0) / 5 < 1.0
