"""Wind-aware A* on a coarse 3D grid (pure numpy + heapq, runs on CPU).

Grid: 10 m horizontal cells, altitude layers 20/40/60/80 m, 26-connectivity. A cell is blocked when its
centre is inside a building footprint grown by `margin` (5 m) and the layer is at or below the roof + margin;
an edge is also rejected if sample points along it pass within 2.5 m of a building.

Edge cost (direction-dependent wind risk, after the RP-A* idea of a gust + crosswind + limit-exceedance
risk term; Shenzhen Univ., ISPRS Archives XLIX-B4-2026, https://isprs-archives.copernicus.org/articles/XLIX-B4-2026/453/2026/ -
only the cost *shape* is borrowed, their RANS pipeline is not):

    cost = length * (1 + a*max(0, -u.dir)/v_cruise + b*gust/v_cruise + c*|u_perp|/v_cruise)

u = mean wind vector on the edge (average of both end cells' snapshot means), dir = unit edge direction,
u_perp = u - (u.dir) dir (crosswind), gust = std of |u| over the last K wind snapshots of that cell.
a = b = c = 0 gives the naive (shortest-path) planner.
"""
from __future__ import annotations

import heapq
import itertools
import math
import queue
import threading
from dataclasses import dataclass

import numpy as np
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components

from engine.backend import to_numpy
from engine.scenario.schema import Layout

LAYERS_M = (20.0, 40.0, 60.0, 80.0)
OFFSETS = [o for o in itertools.product((-1, 0, 1), repeat=3) if o != (0, 0, 0)]   # 26
EDGE_CLEARANCE_M = 2.5


@dataclass
class _Costs:
    """Immutable-by-convention bundle swapped atomically on refresh (thread safety)."""
    cost: list          # 26 lists (length N) of floats, inf = no edge
    deltas: list        # flat-index delta per offset
    layout_version: int


class GridPlanner:
    def __init__(self, layout: Layout, weights=(0.0, 0.0, 0.0), cell_m: float = 10.0, layers=LAYERS_M,
                 margin_m: float = 5.0, v_cruise: float = 12.0, k_snapshots: int = 10, snap_radius_m: float = 30.0):
        self.cell_m, self.layers = cell_m, np.asarray(layers, float)
        self.margin_m, self.v_cruise, self.k = margin_m, v_cruise, k_snapshots
        self.snap_radius_m = snap_radius_m
        self.weights = tuple(weights)
        self._snaps: list[np.ndarray] = []
        self._costs: _Costs | None = None
        self._comp = None
        self.set_layout(layout)

    # ------------------------------------------------------------------ geometry
    def set_layout(self, layout: Layout) -> None:
        self.layout = layout
        self.nx = int(round(layout.area_m[0] / self.cell_m))
        self.ny = int(round(layout.area_m[1] / self.cell_m))
        self.nz = len(self.layers)
        self.shape = (self.nx, self.ny, self.nz)
        self.N = self.nx * self.ny * self.nz
        xs = (np.arange(self.nx) + 0.5) * self.cell_m
        ys = (np.arange(self.ny) + 0.5) * self.cell_m
        X, Y, Z = np.meshgrid(xs, ys, self.layers, indexing="ij")
        self.centers = np.stack([X, Y, Z], axis=-1)             # [nx,ny,nz,3]
        self._bp = np.array([[b.x, b.y, b.x + b.w, b.y + b.d, b.h] for b in layout.buildings],
                            float).reshape(-1, 5)
        self.free = ~self._inside(self.centers, self.margin_m)
        self._valid = self._edge_validity()
        self._comp = None
        self.refresh()

    def _inside(self, P, grow):
        """True where P [...,3] lies in any building grown by `grow` in xy and above by `grow`."""
        out = np.zeros(P.shape[:-1], bool)
        for x0, y0, x1, y1, h in self._bp:
            out |= ((P[..., 0] >= x0 - grow) & (P[..., 0] <= x1 + grow) & (P[..., 1] >= y0 - grow)
                    & (P[..., 1] <= y1 + grow) & (P[..., 2] <= h + grow))
        return out

    def _edge_validity(self):
        dz = self.layers[1] - self.layers[0]
        valid = []
        for o in OFFSETS:
            ok = np.zeros(self.shape, bool)
            src, dst = [], []
            for ax, d in enumerate(o):
                n = self.shape[ax]
                src.append(slice(0, n - d) if d > 0 else slice(-d, n) if d < 0 else slice(0, n))
                dst.append(slice(d, n) if d > 0 else slice(0, n + d) if d < 0 else slice(0, n))
            src, dst = tuple(src), tuple(dst)
            good = self.free[src] & self.free[dst]
            a = self.centers[src]
            vec = np.array([o[0] * self.cell_m, o[1] * self.cell_m, o[2] * dz])
            for t in (0.25, 0.5, 0.75):
                good &= ~self._inside(a + t * vec, EDGE_CLEARANCE_M)
            ok[src] = good
            valid.append(ok)
        return valid

    # ------------------------------------------------------------------ wind statistics
    def observe(self, wind) -> None:
        """Record one wind snapshot (cell-centre velocities) in the ring buffer of K snapshots."""
        u = to_numpy(wind.sample(self.centers.reshape(-1, 3))).reshape(self.shape + (3,)).astype(np.float32)
        self._snaps.append(u)
        if len(self._snaps) > self.k:
            self._snaps.pop(0)

    def set_weights(self, weights) -> None:
        self.weights = tuple(weights)
        self.refresh()

    def refresh(self) -> None:
        """Recompute all 26 edge-cost arrays from the current snapshots + weights (atomic swap)."""
        a, b, c = self.weights
        dz = self.layers[1] - self.layers[0]
        if self._snaps and (a or b or c):
            S = np.stack(self._snaps)
            M = S.mean(axis=0)                                   # mean wind vector per cell
            G = np.linalg.norm(S, axis=-1).std(axis=0)           # gust: std of |u| over snapshots
        else:
            M, G = np.zeros(self.shape + (3,), np.float32), np.zeros(self.shape, np.float32)
        costs, deltas = [], []
        for o, ok in zip(OFFSETS, self._valid):
            vec = np.array([o[0] * self.cell_m, o[1] * self.cell_m, o[2] * dz])
            length = float(np.linalg.norm(vec))
            d = vec / length
            ce = np.full(self.shape, np.inf)
            if a or b or c:
                src, dst = [], []
                for ax, off in enumerate(o):
                    n = self.shape[ax]
                    src.append(slice(0, n - off) if off > 0 else slice(-off, n) if off < 0 else slice(0, n))
                    dst.append(slice(off, n) if off > 0 else slice(0, n + off) if off < 0 else slice(0, n))
                src, dst = tuple(src), tuple(dst)
                u = 0.5 * (M[src] + M[dst])
                along = u @ d
                head = np.maximum(0.0, -along)
                cross = np.linalg.norm(u - along[..., None] * d, axis=-1)
                gust = 0.5 * (G[src] + G[dst])
                factor = np.zeros(self.shape)
                factor[src] = 1 + a * head / self.v_cruise + b * gust / self.v_cruise + c * cross / self.v_cruise
            else:
                factor = np.ones(self.shape)
            ce = np.where(ok, length * factor, np.inf)
            costs.append(ce.ravel().tolist())
            deltas.append((o[0] * self.ny + o[1]) * self.nz + o[2])
        self._costs = _Costs(costs, deltas, self.layout.version)

    # ------------------------------------------------------------------ search
    def _flat(self, ijk):
        return (ijk[0] * self.ny + ijk[1]) * self.nz + ijk[2]

    def _unflat(self, n):
        return n // (self.ny * self.nz), (n // self.nz) % self.ny, n % self.nz

    def snap(self, p) -> tuple | None:
        """Nearest free cell (i,j,k) to point p within snap_radius_m, or None."""
        p = np.asarray(p, float)
        d = np.linalg.norm(self.centers - p, axis=-1)
        d = np.where(self.free, d, np.inf)
        k = int(np.argmin(d))
        if not np.isfinite(d.flat[k]) or d.flat[k] > self.snap_radius_m:
            return None
        return tuple(int(v) for v in np.unravel_index(k, self.shape))

    def _search(self, costs: _Costs, s: int, g: int):
        cost, deltas = costs.cost, costs.deltas
        gx, gy, gz = self.centers[self._unflat(g)]
        cx, cy, cz = (self.centers[..., 0].ravel().tolist(), self.centers[..., 1].ravel().tolist(),
                      self.centers[..., 2].ravel().tolist())
        inf = math.inf
        gs = [inf] * self.N
        parent = [-1] * self.N
        done = bytearray(self.N)
        gs[s] = 0.0
        heap = [(math.dist((cx[s], cy[s], cz[s]), (gx, gy, gz)), 0, s)]
        tie = 1
        while heap:
            _, _, n = heapq.heappop(heap)
            if done[n]:
                continue
            if n == g:
                break
            done[n] = 1
            gn = gs[n]
            for k in range(26):
                c = cost[k][n]
                if c == inf:
                    continue
                m = n + deltas[k]
                ng = gn + c
                if ng < gs[m]:
                    gs[m] = ng
                    parent[m] = n
                    h = math.sqrt((cx[m] - gx) ** 2 + (cy[m] - gy) ** 2 + (cz[m] - gz) ** 2)
                    heapq.heappush(heap, (ng + h, tie, m))
                    tie += 1
        if gs[g] == inf:
            return None, inf
        path, n = [], g
        while n != -1:
            path.append(n)
            n = parent[n]
        return path[::-1], gs[g]

    def plan_cells(self, start_xyz, goal_xyz):
        """-> (list of (i,j,k), cost) or (None, inf)."""
        costs = self._costs
        s, g = self.snap(start_xyz), self.snap(goal_xyz)
        if s is None or g is None:
            return None, math.inf
        path, c = self._search(costs, self._flat(s), self._flat(g))
        if path is None:
            return None, math.inf
        return [self._unflat(n) for n in path], c

    def plan(self, start_xyz, goal_xyz):
        """Waypoints [K,3] in metres from start to goal, or None if unreachable.

        A ground endpoint (z < 1) adds a vertical leg at its x,y, so a delivery is climb -> cruise -> descend.
        """
        cells, _ = self.plan_cells(start_xyz, goal_xyz)
        if cells is None:
            return None
        mid = [tuple(self.centers[c]) for c in cells]
        pts = []
        sx, sy, sz = (float(v) for v in start_xyz)
        gx, gy, gz = (float(v) for v in goal_xyz)
        if sz < 1.0:
            pts += [(sx, sy, 0.0), (sx, sy, mid[0][2])]
        pts += mid
        if gz < 1.0:
            pts += [(gx, gy, mid[-1][2]), (gx, gy, 0.0)]
        else:
            pts += [(gx, gy, gz)]
        return np.asarray(_simplify(pts), np.float32)

    # ------------------------------------------------------------------ reachability
    def _components(self):
        if self._comp is None:
            rows, cols = [], []
            idx = np.arange(self.N).reshape(self.shape)
            for o, ok, in zip(OFFSETS, self._valid):
                dst = idx + (o[0] * self.ny + o[1]) * self.nz + o[2]
                sel = ok
                rows.append(idx[sel]); cols.append(dst[sel])
            r, c = np.concatenate(rows), np.concatenate(cols)
            g = coo_matrix((np.ones(len(r)), (r, c)), shape=(self.N, self.N))
            self._comp = connected_components(g, directed=False)[1]
        return self._comp

    def reachable(self, a_xy, b_xy) -> bool:
        """Is there a grid route between two ground points (e.g. depot and target)?"""
        sa = self.snap((a_xy[0], a_xy[1], 0.0))
        sb = self.snap((b_xy[0], b_xy[1], 0.0))
        if sa is None or sb is None:
            return False
        comp = self._components()
        return bool(comp[self._flat(sa)] == comp[self._flat(sb)])


def _simplify(pts):
    """Drop duplicate points and merge collinear runs."""
    out = [pts[0]]
    for p in pts[1:]:
        if np.allclose(p, out[-1]):
            continue
        out.append(p)
    keep = [out[0]]
    for i in range(1, len(out) - 1):
        a, b, c = np.array(keep[-1]), np.array(out[i]), np.array(out[i + 1])
        u, v = b - a, c - b
        if np.linalg.norm(np.cross(u, v)) < 1e-6 and np.dot(u, v) > 0:
            continue
        keep.append(out[i])
    keep.append(out[-1])
    return keep


def reachable(layout: Layout, depot_xy, target_xy) -> bool:
    """Convenience for edit validation: can a drone fly from depot to target in this layout?"""
    return GridPlanner(layout).reachable(depot_xy, target_xy)


class AsyncReplanner:
    """Runs planner.plan() jobs on one worker thread; results are collected at step boundaries.

    The planner's cost bundle is swapped atomically (single reference assignment) and read once per
    search, so a refresh during a search cannot be observed half-applied.
    """

    def __init__(self, planner: GridPlanner):
        self.planner = planner
        self._jobs: queue.Queue = queue.Queue()
        self._done: queue.Queue = queue.Queue()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True, name="replanner")
        self._thread.start()

    def _run(self):
        while not self._stop.is_set():
            try:
                key, start, goal, tag = self._jobs.get(timeout=0.1)
            except queue.Empty:
                continue
            try:
                res = self.planner.plan(start, goal)
            except Exception as exc:  # noqa: BLE001
                res = exc
            self._done.put((key, tag, res))

    def submit(self, key, start, goal, tag=None) -> None:
        self._jobs.put((key, tuple(start), tuple(goal), tag))

    def collect(self) -> list:
        """All finished (key, tag, waypoints|None|Exception) since the last call."""
        out = []
        while True:
            try:
                out.append(self._done.get_nowait())
            except queue.Empty:
                return out

    def pending(self) -> int:
        return self._jobs.qsize()

    def close(self) -> None:
        self._stop.set()
        self._thread.join(timeout=2)
