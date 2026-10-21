"""Scenario schema: dataclasses + JSON load/validate.

Conventions (shared by every module and docs/protocol.md):
  * SI units. x = east, y = north, z = up; origin at the south-west corner of the area.
  * Building: axis-aligned box with min corner (x, y), footprint w (along x) by d (along y), height h.
  * Inflow.direction_deg: direction the wind blows TOWARD, counter-clockwise from +x.
    0 = wind blows east (towards +x), 90 = towards +y.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path


class SchemaError(ValueError):
    """Raised when a scenario / layout / inflow fails validation."""


@dataclass(frozen=True)
class Building:
    id: int
    x: float
    y: float
    w: float
    d: float
    h: float

    @property
    def cx(self) -> float:
        return self.x + self.w / 2

    @property
    def cy(self) -> float:
        return self.y + self.d / 2

    def contains_xy(self, px: float, py: float, margin: float = 0.0) -> bool:
        return (self.x - margin <= px <= self.x + self.w + margin
                and self.y - margin <= py <= self.y + self.d + margin)


@dataclass(frozen=True)
class Layout:
    area_m: tuple[float, float]
    buildings: tuple[Building, ...]
    ceiling_m: float = 120.0
    version: int = 0

    @property
    def bounds_m(self) -> tuple[float, float, float]:
        return (self.area_m[0], self.area_m[1], self.ceiling_m)

    def get(self, bid: int) -> Building:
        for b in self.buildings:
            if b.id == bid:
                return b
        raise KeyError(bid)

    def replace_building(self, new: Building) -> "Layout":
        bs = tuple(new if b.id == new.id else b for b in self.buildings)
        if all(b.id != new.id for b in self.buildings):
            raise KeyError(new.id)
        return replace(self, buildings=bs, version=self.version + 1)

    def point_blocked(self, px: float, py: float, margin: float = 0.0) -> bool:
        """True if the ground-projected point lies inside any footprint (+margin)."""
        return any(b.contains_xy(px, py, margin) for b in self.buildings)

    def to_dict(self) -> dict:
        return {"area_m": list(self.area_m), "ceiling_m": self.ceiling_m,
                "buildings": [asdict(b) for b in self.buildings]}


@dataclass(frozen=True)
class Inflow:
    speed_ms: float = 8.0          # reference speed at 10 m height
    direction_deg: float = 0.0     # blowing toward, CCW from +x
    roughness: float = 0.5         # aerodynamic roughness length z0 in metres (urban ~0.5-1)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class Depot:
    id: int
    x: float
    y: float


@dataclass(frozen=True)
class Mission:
    id: int
    depot: int                 # Depot.id
    target: tuple[float, float]  # ground delivery point (x, y)


@dataclass(frozen=True)
class SimSettings:
    dt: float = 0.05
    duration_s: float = 300.0
    tier: str = "synthetic"
    routing: str = "naive"             # naive | aware
    start_window_s: float = 60.0       # mission start times ~ U(0, window) from the seed
    cruise_ms: float = 12.0
    thrust_max: float = 8.0            # m/s^2 (unit mass, so also N/kg)
    wind_drag: float = 0.5             # 1/s: a = k (u_wind - v)
    r_sep: float = 6.0
    d_near: float = 2.0                # near-collision distance
    reach_m: float = 4.0
    deliver_s: float = 2.0
    replan_s: float = 15.0             # aware routing: refresh wind stats + replan period
    # planner cost weights (a=b=c=0 is the naive planner)
    w_head: float = 4.0
    w_gust: float = 6.0
    w_cross: float = 2.0


@dataclass(frozen=True)
class Scenario:
    name: str
    seed: int
    layout: Layout
    inflow: Inflow
    depots: tuple[Depot, ...]
    missions: tuple[Mission, ...]
    sim: SimSettings = field(default_factory=SimSettings)

    def depot(self, did: int) -> Depot:
        for d in self.depots:
            if d.id == did:
                return d
        raise KeyError(did)

    def to_dict(self) -> dict:
        return {
            "name": self.name, "seed": self.seed,
            "layout": self.layout.to_dict(), "inflow": self.inflow.to_dict(),
            "depots": [asdict(d) for d in self.depots],
            "missions": [{"id": m.id, "depot": m.depot, "target": list(m.target)} for m in self.missions],
            "sim": asdict(self.sim),
        }


# ----------------------------------------------------------------------------------- validation

def validate_inflow(inflow: Inflow) -> None:
    if not 0.0 < inflow.speed_ms <= 40.0:
        raise SchemaError(f"inflow speed_ms must be in (0, 40], got {inflow.speed_ms}")
    if not 0.001 <= inflow.roughness <= 5.0:
        raise SchemaError(f"inflow roughness must be in [0.001, 5], got {inflow.roughness}")


def validate_building(b: Building, area_m: tuple[float, float], ceiling_m: float) -> None:
    if min(b.w, b.d, b.h) <= 0:
        raise SchemaError(f"building {b.id}: w, d, h must be positive")
    if b.x < 0 or b.y < 0 or b.x + b.w > area_m[0] or b.y + b.d > area_m[1]:
        raise SchemaError(f"building {b.id}: footprint outside the {area_m[0]:g} x {area_m[1]:g} m area")
    if b.h > ceiling_m * 0.9:
        raise SchemaError(f"building {b.id}: height {b.h:g} m exceeds 90% of the {ceiling_m:g} m ceiling")


def validate_layout(layout: Layout) -> None:
    if layout.area_m[0] <= 0 or layout.area_m[1] <= 0:
        raise SchemaError("area_m must be positive")
    ids = [b.id for b in layout.buildings]
    if len(set(ids)) != len(ids):
        raise SchemaError("duplicate building ids")
    for b in layout.buildings:
        validate_building(b, layout.area_m, layout.ceiling_m)
    bs = layout.buildings
    for i in range(len(bs)):
        for j in range(i + 1, len(bs)):
            a, b = bs[i], bs[j]
            if a.x < b.x + b.w and b.x < a.x + a.w and a.y < b.y + b.d and b.y < a.y + a.d:
                raise SchemaError(f"buildings {a.id} and {b.id} overlap")


def validate_scenario(sc: Scenario) -> None:
    validate_layout(sc.layout)
    validate_inflow(sc.inflow)
    if sc.sim.routing not in ("naive", "aware"):
        raise SchemaError(f"routing must be naive|aware, got {sc.sim.routing!r}")
    if sc.sim.dt <= 0 or sc.sim.duration_s <= 0:
        raise SchemaError("dt and duration_s must be positive")
    dep_ids = [d.id for d in sc.depots]
    if len(set(dep_ids)) != len(dep_ids) or not dep_ids:
        raise SchemaError("depots need unique ids and at least one entry")
    for d in sc.depots:
        if not (0 <= d.x <= sc.layout.area_m[0] and 0 <= d.y <= sc.layout.area_m[1]):
            raise SchemaError(f"depot {d.id} outside the area")
        if sc.layout.point_blocked(d.x, d.y, 5.0):
            raise SchemaError(f"depot {d.id} lies inside a building (+5 m margin)")
    mids = [m.id for m in sc.missions]
    if len(set(mids)) != len(mids):
        raise SchemaError("duplicate mission ids")
    for m in sc.missions:
        if m.depot not in dep_ids:
            raise SchemaError(f"mission {m.id}: unknown depot {m.depot}")
        tx, ty = m.target
        if not (0 <= tx <= sc.layout.area_m[0] and 0 <= ty <= sc.layout.area_m[1]):
            raise SchemaError(f"mission {m.id}: target outside the area")
        if sc.layout.point_blocked(tx, ty, 5.0):
            raise SchemaError(f"mission {m.id}: target lies inside a building (+5 m margin)")


# ----------------------------------------------------------------------------------- JSON

def layout_from_dict(d: dict) -> Layout:
    try:
        layout = Layout(
            area_m=(float(d["area_m"][0]), float(d["area_m"][1])),
            ceiling_m=float(d.get("ceiling_m", 120.0)),
            buildings=tuple(Building(int(b["id"]), float(b["x"]), float(b["y"]),
                                     float(b["w"]), float(b["d"]), float(b["h"]))
                            for b in d["buildings"]),
            version=int(d.get("version", 0)),
        )
    except (KeyError, TypeError, IndexError) as exc:
        raise SchemaError(f"bad layout: {exc!r}") from exc
    validate_layout(layout)
    return layout


def inflow_from_dict(d: dict) -> Inflow:
    try:
        inflow = Inflow(float(d.get("speed_ms", 8.0)), float(d.get("direction_deg", 0.0)),
                        float(d.get("roughness", 0.5)))
    except (TypeError, ValueError) as exc:
        raise SchemaError(f"bad inflow: {exc!r}") from exc
    validate_inflow(inflow)
    return inflow


def scenario_from_dict(d: dict) -> Scenario:
    try:
        sim_fields = SimSettings.__dataclass_fields__
        unknown = set(d.get("sim", {})) - set(sim_fields)
        if unknown:
            raise SchemaError(f"unknown sim settings: {sorted(unknown)}")
        sc = Scenario(
            name=str(d["name"]),
            seed=int(d["seed"]),
            layout=layout_from_dict(d["layout"]),
            inflow=inflow_from_dict(d["inflow"]),
            depots=tuple(Depot(int(x["id"]), float(x["x"]), float(x["y"])) for x in d["depots"]),
            missions=tuple(Mission(int(m["id"]), int(m["depot"]),
                                   (float(m["target"][0]), float(m["target"][1])))
                           for m in d["missions"]),
            sim=SimSettings(**d.get("sim", {})),
        )
    except (KeyError, TypeError, IndexError) as exc:
        raise SchemaError(f"bad scenario: {exc!r}") from exc
    validate_scenario(sc)
    return sc


def load_scenario(path: str | Path) -> Scenario:
    with open(path) as fh:
        return scenario_from_dict(json.load(fh))


def dump_scenario(sc: Scenario, path: str | Path) -> None:
    with open(path, "w") as fh:
        json.dump(sc.to_dict(), fh, indent=1)
        fh.write("\n")
