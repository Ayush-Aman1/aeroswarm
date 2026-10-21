"""Select a wind adapter by config name. No other module imports an adapter directly."""
from __future__ import annotations

from engine.scenario.schema import Inflow, Layout

TIERS = {
    "synthetic": 3, "fluidx3d": 2, "lbmpy": 1,
}
ALIASES = {"tier3": "synthetic", "tier2": "fluidx3d", "tier1": "lbmpy", "3": "synthetic", "2": "fluidx3d",
           "1": "lbmpy", "native": "native"}


def make_wind(name: str, layout: Layout, inflow: Inflow, dt_s: float = 0.05, **cfg):
    """Build + reset a wind source. cfg is adapter specific (see each adapter's __init__)."""
    key = ALIASES.get(str(name).lower(), str(name).lower())
    if key == "synthetic":
        from engine.wind.synthetic import SyntheticWind
        wind = SyntheticWind(dt_s=dt_s, **cfg)
    elif key == "fluidx3d":
        from engine.wind.fluidx3d_field import FluidX3DField
        wind = FluidX3DField(dt_s=dt_s, **cfg)
    elif key == "lbmpy":
        from engine.wind.lbmpy_solver import LbmpySolver
        wind = LbmpySolver(dt_s=dt_s, **cfg)
    elif key == "native":
        from engine.wind.native import NativeWind
        wind = NativeWind(dt_s=dt_s, **cfg)
    else:
        raise ValueError(f"unknown wind source {name!r}; choose synthetic | fluidx3d | lbmpy | native")
    wind.reset(layout, inflow)
    return wind


def available_tiers(field_dir=None) -> list[str]:
    """Tiers that can start on this machine right now (synthetic always)."""
    out = ["synthetic"]
    try:
        from engine.wind.fluidx3d_field import FluidX3DField
        if FluidX3DField.available(field_dir):
            out.append("fluidx3d")
    except Exception:  # noqa: BLE001
        pass
    try:
        from engine.wind.lbmpy_solver import LbmpySolver
        if LbmpySolver.available():
            out.append("lbmpy")
    except Exception:  # noqa: BLE001
        pass
    try:
        from engine.wind.native import NativeWind
        if NativeWind.available():
            out.append("native")
    except Exception:  # noqa: BLE001
        pass
    return out
