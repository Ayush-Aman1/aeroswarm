"""Validation of building edits (P6/P8): a rejected edit must leave everything unchanged."""
from __future__ import annotations

import numpy as np

from engine.backend import to_numpy
from engine.planner.astar import GridPlanner
from engine.scenario.schema import Building, Layout, SchemaError, validate_building

MARGIN_M = 5.0


def validate_edit(sim, new: Building) -> tuple[bool, str, Layout | None]:
    """-> (ok, reason, new_layout). `sim` is an engine.scenario.runner.Simulation."""
    if sim.settling:
        return False, "wind is still settling from the previous edit", None
    layout = sim.layout
    try:
        layout.get(new.id)
    except KeyError:
        return False, f"unknown building id {new.id}", None
    try:
        validate_building(new, layout.area_m, layout.ceiling_m)
    except SchemaError as exc:
        return False, str(exc), None
    for b in layout.buildings:
        if b.id != new.id and new.x < b.x + b.w and b.x < new.x + new.w and new.y < b.y + b.d and b.y < new.y + new.d:
            return False, f"overlaps building {b.id}", None
    for d in sim.sc.depots:
        if new.contains_xy(d.x, d.y, MARGIN_M):
            return False, f"would cover depot {d.id} (needs {MARGIN_M:g} m clearance)", None
    for m in sim.sc.missions:
        if new.contains_xy(m.target[0], m.target[1], MARGIN_M):
            return False, f"would cover the delivery point of mission {m.id}", None
    pos = to_numpy(sim.drones.pos)[to_numpy(sim.drones.active)]
    if len(pos):
        inside = ((pos[:, 0] >= new.x - MARGIN_M) & (pos[:, 0] <= new.x + new.w + MARGIN_M)
                  & (pos[:, 1] >= new.y - MARGIN_M) & (pos[:, 1] <= new.y + new.d + MARGIN_M)
                  & (pos[:, 2] <= new.h + MARGIN_M))
        if inside.any():
            return False, f"{int(inside.sum())} drone(s) are in the way of the new footprint", None
    new_layout = layout.replace_building(new)
    planner = GridPlanner(new_layout)
    for d in sim.sc.depots:
        bad = [m.id for m in sim.sc.missions if m.depot == d.id and not planner.reachable((d.x, d.y), m.target)]
        if bad:
            return False, f"depot {d.id} could no longer reach {len(bad)} target(s) (e.g. mission {bad[0]})", None
    return True, "", new_layout
