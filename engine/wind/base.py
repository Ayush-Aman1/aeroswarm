"""WindSource: the only door through which drones, planner, service and viewer see wind.

Units are SI (metres, seconds, m/s) at this interface; lattice units stay inside adapters.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from engine.scenario.schema import Inflow, Layout


@runtime_checkable
class WindSource(Protocol):
    name: str
    bounds_m: tuple[float, float, float]   # x, y, z extent in metres
    dx_m: float                            # grid spacing

    def reset(self, layout: Layout, inflow: Inflow) -> None: ...

    def step(self, n: int = 1) -> None:
        """Advance the wind by n simulation steps of `dt_s` seconds each."""

    def sample(self, pos):
        """pos [N,3] metres -> velocity [N,3] m/s. Trilinear; exactly zero inside buildings."""

    def slice_z(self, z_m: float):
        """-> [nx, ny, 3] velocity on the grid layer nearest z_m."""

    def begin_relayout(self, layout: Layout, inflow: Inflow) -> None: ...

    def relayout_ready(self) -> bool: ...

    def commit_relayout(self) -> None:
        """Swap in the new geometry; call only at a step boundary."""

    def stats(self) -> dict:
        """{'mlups': ..., 'step_ms': ...} (0.0 where not meaningful)."""


class WindSourceBase:
    """Shared plumbing: pending-relayout bookkeeping and stats."""

    name = "base"
    dx_m = 2.0

    def __init__(self, dt_s: float = 0.05) -> None:
        self.dt_s = dt_s
        self.time_s = 0.0
        self.layout: Layout | None = None
        self.inflow: Inflow | None = None
        self._pending: tuple[Layout, Inflow] | None = None
        self._stats = {"mlups": 0.0, "step_ms": 0.0}

    @property
    def bounds_m(self) -> tuple[float, float, float]:
        assert self.layout is not None, "reset() first"
        return self.layout.bounds_m

    def stats(self) -> dict:
        return dict(self._stats)

    def relayout_pending(self) -> bool:
        return self._pending is not None
