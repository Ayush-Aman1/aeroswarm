"""Fourth wind adapter: the team's own CUDA engine through its C ABI (native/aeroswarm_native.h) with ctypes.

The library path comes from `lib_path`, the AEROSWARM_NATIVE_LIB environment variable, or native/build/ (see
docs/LINKING_GUIDE.md). native/mock/aero_mock.c is a reference implementation used by the tests; the real engine
implements the same header. Failures are loud: a missing/incompatible library raises, there is no silent fallback.
"""
from __future__ import annotations

import ctypes
import os
import sys
import time
from pathlib import Path

import numpy as np

from engine.backend import to_numpy, xp
from engine.scenario.schema import Inflow, Layout
from engine.wind.base import WindSourceBase

ROOT = Path(__file__).resolve().parents[2]
ABI_VERSION = 1


def default_library_names() -> list[Path]:
    build = ROOT / "native" / "build"
    names = {"win32": ["aeroswarm_native.dll"], "darwin": ["libaeroswarm_native.dylib"]}.get(sys.platform, ["libaeroswarm_native.so"])
    return [build / n for n in names]


def solid_mask(layout: Layout, shape, dx_m: float) -> np.ndarray:
    xs, ys, zs = ((np.arange(n) + 0.5) * dx_m for n in shape)
    X, Y, Z = np.meshgrid(xs, ys, zs, indexing="ij")
    m = np.zeros(shape, bool)
    for b in layout.buildings:
        m |= (X >= b.x) & (X <= b.x + b.w) & (Y >= b.y) & (Y <= b.y + b.d) & (Z <= b.h)
    return m


class NativeError(RuntimeError):
    pass


class NativeWind(WindSourceBase):
    name = "native"

    def __init__(self, dt_s: float = 0.05, dx_m: float = 2.0, lib_path: str | None = None, **_: object) -> None:
        super().__init__(dt_s)
        self.dx_m = dx_m
        candidates = [Path(p) for p in (lib_path, os.environ.get("AEROSWARM_NATIVE_LIB")) if p] or default_library_names()
        path = next((p for p in candidates if p.exists()), None)
        if path is None:
            raise FileNotFoundError("native engine library not found (tried: " + ", ".join(map(str, candidates)) +
                                    "). Build it and set AEROSWARM_NATIVE_LIB - see docs/LINKING_GUIDE.md")
        self.lib = ctypes.CDLL(str(path))
        self._declare()
        ver = self.lib.aero_abi_version()
        if ver != ABI_VERSION:
            raise NativeError(f"{path.name} implements ABI {ver}, this adapter needs {ABI_VERSION}")
        self.path = path
        self.h = None
        self.shape = (0, 0, 0)
        self._solid_boxes = np.zeros((0, 5))

    @classmethod
    def available(cls, *_a, **_k) -> bool:
        return any(p.exists() for p in [Path(os.environ["AEROSWARM_NATIVE_LIB"])] if "AEROSWARM_NATIVE_LIB" in os.environ) \
            or any(p.exists() for p in default_library_names())

    def _declare(self) -> None:
        L = self.lib
        c_f, c_i, c_u8p = ctypes.c_float, ctypes.c_int, ctypes.POINTER(ctypes.c_uint8)
        fp = ctypes.POINTER(ctypes.c_float)
        L.aero_abi_version.restype = c_i
        L.aero_create.restype = ctypes.c_void_p
        L.aero_create.argtypes = [c_i, c_i, c_i, c_f, c_f]
        L.aero_destroy.argtypes = [ctypes.c_void_p]
        L.aero_reset.argtypes = [ctypes.c_void_p, c_u8p, c_f, c_f, c_f]
        L.aero_step.argtypes = [ctypes.c_void_p, c_i]
        L.aero_sample.argtypes = [ctypes.c_void_p, fp, c_i, fp]
        L.aero_slice_z.argtypes = [ctypes.c_void_p, c_f, fp]
        L.aero_relayout_begin.argtypes = [ctypes.c_void_p, c_u8p, c_f, c_f, c_f]
        L.aero_relayout_ready.argtypes = [ctypes.c_void_p]
        L.aero_relayout_commit.argtypes = [ctypes.c_void_p]
        L.aero_stats.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_double), ctypes.POINTER(ctypes.c_double)]
        L.aero_last_error.restype = ctypes.c_char_p
        for fn in (L.aero_reset, L.aero_step, L.aero_sample, L.aero_slice_z, L.aero_relayout_begin,
                   L.aero_relayout_ready, L.aero_relayout_commit, L.aero_stats):
            fn.restype = c_i

    def _check(self, rc: int, what: str) -> int:
        if rc < 0:
            msg = self.lib.aero_last_error()
            raise NativeError(f"{what} failed ({rc}): {msg.decode() if msg else 'no message'}")
        return rc

    @staticmethod
    def _ptr(a: np.ndarray, ctype):
        return a.ctypes.data_as(ctypes.POINTER(ctype))

    # ------------------------------------------------------------------ interface
    def _solid(self, layout: Layout) -> np.ndarray:
        return np.ascontiguousarray(solid_mask(layout, self.shape, self.dx_m).astype(np.uint8))

    def reset(self, layout: Layout, inflow: Inflow) -> None:
        if self.h:
            self.lib.aero_destroy(self.h)
        self.shape = tuple(int(round(v / self.dx_m)) for v in layout.bounds_m)
        self.h = self.lib.aero_create(*self.shape, self.dx_m, self.dt_s)
        if not self.h:
            raise NativeError("aero_create returned NULL: " + (self.lib.aero_last_error() or b"").decode())
        solid = self._solid(layout)
        self._check(self.lib.aero_reset(self.h, self._ptr(solid, ctypes.c_uint8), inflow.speed_ms, inflow.direction_deg,
                                        inflow.roughness), "aero_reset")
        self._install(layout, inflow)
        self._pending = None
        self.time_s = 0.0

    def _install(self, layout: Layout, inflow: Inflow) -> None:
        self.layout, self.inflow = layout, inflow
        self._solid_boxes = np.array([[b.x, b.y, b.w, b.d, b.h] for b in layout.buildings], float).reshape(-1, 5)

    def step(self, n: int = 1) -> None:
        t0 = time.perf_counter()
        self._check(self.lib.aero_step(self.h, int(n)), "aero_step")
        self.time_s += n * self.dt_s
        ml, ms = ctypes.c_double(), ctypes.c_double()
        if self.lib.aero_stats(self.h, ctypes.byref(ml), ctypes.byref(ms)) == 0:
            self._stats = {"mlups": ml.value, "step_ms": ms.value}
        else:
            self._stats = {"mlups": 0.0, "step_ms": (time.perf_counter() - t0) * 1e3 / max(n, 1)}

    def sample(self, pos):
        P = np.ascontiguousarray(to_numpy(pos).astype(np.float32).reshape(-1, 3))
        out = np.empty_like(P)
        self._check(self.lib.aero_sample(self.h, self._ptr(P, ctypes.c_float), len(P), self._ptr(out, ctypes.c_float)), "aero_sample")
        bp = self._solid_boxes                      # the contract says zero inside solids; enforce it exactly here too
        if len(bp):
            x, y, z = P[:, 0:1], P[:, 1:2], P[:, 2:3]
            out[((x >= bp[:, 0]) & (x <= bp[:, 0] + bp[:, 2]) & (y >= bp[:, 1]) & (y <= bp[:, 1] + bp[:, 3])
                 & (z <= bp[:, 4])).any(axis=1)] = 0.0
        return xp.asarray(out)

    def slice_z(self, z_m: float):
        out = np.empty((self.shape[0], self.shape[1], 3), np.float32)
        self._check(self.lib.aero_slice_z(self.h, float(z_m), self._ptr(out, ctypes.c_float)), "aero_slice_z")
        return xp.asarray(out)

    def begin_relayout(self, layout: Layout, inflow: Inflow) -> None:
        solid = self._solid(layout)
        self._check(self.lib.aero_relayout_begin(self.h, self._ptr(solid, ctypes.c_uint8), inflow.speed_ms,
                                                 inflow.direction_deg, inflow.roughness), "aero_relayout_begin")
        self._pending = (layout, inflow)

    def relayout_ready(self) -> bool:
        return self._pending is not None and self._check(self.lib.aero_relayout_ready(self.h), "aero_relayout_ready") == 1

    def commit_relayout(self) -> None:
        if self._pending is None:
            return
        self._check(self.lib.aero_relayout_commit(self.h), "aero_relayout_commit")
        self._install(*self._pending)
        self._pending = None

    def __del__(self):
        try:
            if getattr(self, "h", None):
                self.lib.aero_destroy(self.h)
        except Exception:  # noqa: BLE001
            pass
