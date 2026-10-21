"""Tier 2 wind: precomputed FluidX3D fields on disk, replayed in time.

Layout of data/fields/<preset>/dir_<deg>/: frame_00.npy ... frame_15.npy (float16 [nx,ny,nz,3], SI, city frame,
2 m grid, z up to zmax) and meta.json (see tools/fluidx3d/convert.py). The 16 frames are looped in time with
linear blending so gusts are preserved. sample() is trilinear; above the stored height the top layer is scaled
by the log-law ratio; exactly zero inside buildings.

Relayout: there are no live CFD edits in this tier - begin_relayout() picks the nearest precomputed preset
(by building geometry) and the nearest stored wind direction. `presets()` lists the menu (the editor shows it).
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path

import numpy as np

from engine.backend import ndi, to_numpy, xp
from engine.scenario.schema import Inflow, Layout
from engine.wind.base import WindSourceBase
from engine.wind.synthetic import log_law

log = logging.getLogger("aeroswarm.wind.fluidx3d")
DEFAULT_DIR = Path(__file__).resolve().parents[2] / "data" / "fields"


def scan(field_dir: Path | str | None = None) -> dict:
    """{preset: {direction_deg: Path}} for every complete run found under field_dir."""
    root = Path(field_dir) if field_dir else DEFAULT_DIR
    out: dict[str, dict[float, Path]] = {}
    if not root.exists():
        return out
    for meta in sorted(root.glob("*/dir_*/meta.json")):
        try:
            m = json.loads(meta.read_text())
        except json.JSONDecodeError:
            continue
        d = meta.parent
        if len(list(d.glob("frame_*.npy"))) == m.get("n_frames"):
            out.setdefault(m["preset"], {})[float(m["direction_deg"])] = d
    return out


def layout_distance(a: Layout, b: Layout) -> float:
    """Sum over matching building ids of |dx|+|dy|+|dw|+|dd|+|dh| (metres); missing ids cost 1000."""
    ba, bb = {x.id: x for x in a.buildings}, {x.id: x for x in b.buildings}
    d = 0.0
    for i in set(ba) | set(bb):
        if i not in ba or i not in bb:
            d += 1000.0
        else:
            p, q = ba[i], bb[i]
            d += abs(p.x - q.x) + abs(p.y - q.y) + abs(p.w - q.w) + abs(p.d - q.d) + abs(p.h - q.h)
    return d


def angle_distance(a: float, b: float) -> float:
    return abs((a - b + 180.0) % 360.0 - 180.0)


class FluidX3DField(WindSourceBase):
    name = "fluidx3d"

    def __init__(self, dt_s: float = 0.05, field_dir: str | Path | None = None, **_: object) -> None:
        super().__init__(dt_s)
        self.field_dir = Path(field_dir) if field_dir else DEFAULT_DIR
        self.index = scan(self.field_dir)
        if not self.index:
            raise FileNotFoundError(
                f"no FluidX3D fields under {self.field_dir}. Generate them on the NVIDIA laptop with "
                f"scripts/windows/run_fluidx3d_batch.ps1 (see HANDOFF_WINDOWS.md)")
        self.meta: dict = {}
        self.preset_distance_m = 0.0
        self.active_preset = ""
        self.active_dir_deg = 0.0
        self._frames: list[Path] = []
        self._cache: dict[int, np.ndarray] = {}
        self._bparams = np.zeros((0, 5))

    @classmethod
    def available(cls, field_dir=None) -> bool:
        return bool(scan(field_dir))

    def presets(self) -> list[dict]:
        """The menu for the editor: preset name, available directions, its buildings."""
        out = []
        for name, dirs in sorted(self.index.items()):
            meta = json.loads((next(iter(dirs.values())) / "meta.json").read_text())
            out.append(dict(preset=name, directions=sorted(dirs), layout=meta["layout"]))
        return out

    # ------------------------------------------------------------------ selection
    def _choose(self, layout: Layout, inflow: Inflow):
        best = None
        for name, dirs in self.index.items():
            meta = json.loads((next(iter(dirs.values())) / "meta.json").read_text())
            from engine.scenario.schema import layout_from_dict
            d = layout_distance(layout, layout_from_dict(meta["layout"]))
            if best is None or d < best[0]:
                best = (d, name, dirs)
        d, name, dirs = best
        theta = min(dirs, key=lambda t: angle_distance(t, inflow.direction_deg))
        return name, theta, dirs[theta], d

    def _load(self, layout: Layout, inflow: Inflow) -> dict:
        name, theta, path, dist = self._choose(layout, inflow)
        meta = json.loads((path / "meta.json").read_text())
        if dist > 0.5:
            log.warning("Tier 2: layout differs from preset %r by %.0f m of building geometry - using the preset's "
                        "precomputed field (no live CFD in this tier)", name, dist)
        if angle_distance(theta, inflow.direction_deg) > 1e-6:
            log.warning("Tier 2: inflow %.0f deg snapped to the nearest stored direction %.0f deg",
                        inflow.direction_deg, theta)
        frames = [path / f"frame_{k:02d}.npy" for k in range(meta["n_frames"])]
        return dict(meta=meta, frames=frames, preset=name, theta=theta, distance=dist, layout=layout, inflow=inflow)

    def _install(self, st: dict) -> None:
        from engine.scenario.schema import layout_from_dict
        self.meta, self._frames = st["meta"], st["frames"]
        self.active_preset, self.active_dir_deg, self.preset_distance_m = st["preset"], st["theta"], st["distance"]
        self.layout, self.inflow = st["layout"], st["inflow"]
        preset_layout = layout_from_dict(self.meta["layout"])
        self._bparams = np.array([[b.x, b.y, b.w, b.d, b.h] for b in preset_layout.buildings], float).reshape(-1, 5)
        self._cache.clear()
        shape = self.meta["shape"]
        self._shape = np.array(shape[:3], float)
        self.dx_m = float(self.meta["dx_m"])
        self._zmax = float(self.meta["zmax_m"])
        self._period = self.meta["n_frames"] * float(self.meta["frame_dt_s"])
        self.time_s = 0.0

    def reset(self, layout: Layout, inflow: Inflow) -> None:
        self._install(self._load(layout, inflow))
        self._pending = None

    def begin_relayout(self, layout: Layout, inflow: Inflow) -> None:
        self._pending = self._load(layout, inflow)

    def relayout_ready(self) -> bool:
        return self._pending is not None

    def commit_relayout(self) -> None:
        if self._pending is None:
            return
        t = self.time_s
        self._install(self._pending)
        self.time_s = t
        self._pending = None

    def step(self, n: int = 1) -> None:
        t0 = time.perf_counter()
        self.time_s += n * self.dt_s
        self._stats = {"mlups": 0.0, "step_ms": (time.perf_counter() - t0) * 1e3 / max(n, 1)}

    # ------------------------------------------------------------------ evaluation
    def _frame(self, k: int):
        if k not in self._cache:
            if len(self._cache) > 3:
                self._cache.pop(next(iter(self._cache)))
            self._cache[k] = xp.asarray(np.load(self._frames[k]).astype(np.float32))
        return self._cache[k]

    def _blend_idx(self):
        n = len(self._frames)
        x = (self.time_s % self._period) / float(self.meta["frame_dt_s"])
        k0 = int(x) % n
        return k0, (k0 + 1) % n, x - int(x)

    def _interp(self, field, co):
        return np.stack([to_numpy(ndi.map_coordinates(field[..., k], co, order=1, mode="nearest"))
                         for k in range(3)], axis=1)

    def sample(self, pos):
        P = to_numpy(pos).astype(np.float64).reshape(-1, 3)
        co = np.clip(P / self.dx_m - 0.5, 0.0, self._shape - 1.0)
        c = xp.asarray(co.T.astype(np.float32))
        k0, k1, f = self._blend_idx()
        v = (1 - f) * self._interp(self._frame(k0), c) + f * self._interp(self._frame(k1), c)
        hi = P[:, 2] > self._zmax
        if hi.any() and self.inflow is not None:
            z0, ur = self.inflow.roughness, self.inflow.speed_ms
            ratio = log_law(P[hi, 2], ur, z0) / max(float(log_law(self._zmax - self.dx_m / 2, ur, z0)), 1e-6)
            v[hi, :2] *= ratio[:, None]
        bp = self._bparams
        if len(bp):
            x, y, z = P[:, 0:1], P[:, 1:2], P[:, 2:3]
            inside = ((x >= bp[:, 0]) & (x <= bp[:, 0] + bp[:, 2]) & (y >= bp[:, 1]) & (y <= bp[:, 1] + bp[:, 3])
                      & (z <= bp[:, 4])).any(axis=1)
            v[inside] = 0.0
        return xp.asarray(v.astype(np.float32))

    def slice_z(self, z_m: float):
        nx, ny, nz = (int(v) for v in self._shape)
        k = int(np.clip(round(z_m / self.dx_m - 0.5), 0, nz - 1))
        k0, k1, f = self._blend_idx()
        a, b = self._frame(k0)[:, :, k, :], self._frame(k1)[:, :, k, :]
        out = (1 - f) * a + f * b
        xs = (np.arange(nx) + 0.5) * self.dx_m
        ys = (np.arange(ny) + 0.5) * self.dx_m
        X, Y = np.meshgrid(xs, ys, indexing="ij")
        z = (k + 0.5) * self.dx_m
        bp = self._bparams
        mask = np.zeros((nx, ny), bool)
        for x0, y0, w, d, h in bp:
            mask |= (X >= x0) & (X <= x0 + w) & (Y >= y0) & (Y <= y0 + d) & (z <= h)
        out = out * xp.asarray((~mask)[..., None].astype(np.float32))
        return out

    def stats(self) -> dict:
        s = super().stats()
        s.update(preset=self.active_preset, direction_deg=self.active_dir_deg, preset_distance_m=self.preset_distance_m)
        return s
