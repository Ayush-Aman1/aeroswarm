import dataclasses
from pathlib import Path

import numpy as np
import pytest

lbmpy = pytest.importorskip("lbmpy")

from engine import backend
from engine.backend import to_numpy
from engine.scenario.schema import Building, Inflow, Layout, load_scenario
from engine.wind import lbmpy_solver as L
from engine.wind.base import WindSource
from engine.wind.factory import available_tiers, make_wind

ROOT = Path(__file__).resolve().parents[1]
DX = 8.0     # coarse grid so CPU tests stay fast (the real Tier 1 grid is dx = 2 m -> 200 x 150 x 60)


@pytest.fixture(scope="module")
def scenario():
    return load_scenario(ROOT / "scenarios/block_small.json")


@pytest.fixture(scope="module")
def solver(scenario):
    w = make_wind("lbmpy", scenario.layout, scenario.inflow, dx_m=DX)
    for _ in range(300):               # ~ 480 lattice steps: wakes have formed on this coarse grid
        w.step(1)
    return w


def test_units_respect_guide_stability_rules():
    for speed in (4.0, 8.0, 15.0):
        for dx in (2.0, 4.0, 8.0):
            u = L.Units(dx, Inflow(speed, 0.0, 0.5), 120.0)
            u.check()
            assert u.tau > 0.51 and u.omega < 1.0 / 0.51
            # fastest inflow cell (log law at the ceiling, plus speed-up headroom) stays <= 0.08 lattice units
            top = u.u_ref_lat * float(L.log_law(120.0, 1.0, 0.5) / L.log_law(10.0, 1.0, 0.5))
            assert top * L.PEAK_HEADROOM <= 0.08
            assert u.dt_lat_s == pytest.approx(dx * u.u_ref_lat / speed)


def test_faces_for_direction():
    assert L.faces_for(0.0) == (["W"], ["E"], ["S", "N"])
    assert L.faces_for(90.0)[:2] == (["S"], ["N"])
    assert L.faces_for(180.0)[:2] == (["E"], ["W"])
    ins, outs, sides = L.faces_for(45.0)
    assert set(ins) == {"W", "S"} and set(outs) == {"E", "N"} and sides == []
    assert set(L.faces_for(225.0)[0]) == {"E", "N"}


def test_solid_mask_matches_buildings(scenario):
    m = L.solid_mask(scenario.layout, (50, 38, 15), 8.0)
    assert m[17, 25, 3]           # inside building 0 (110..150, 190..230, h 60) : cell centre (140, 204, 28)
    assert not m[2, 2, 2] and not m[17, 25, 14]    # outside / above roof (z 116 m)


def test_implements_protocol_and_registers_as_tier(solver):
    assert isinstance(solver, WindSource) and solver.name == "lbmpy"
    assert solver.bounds_m == (400.0, 300.0, 120.0) and solver.dx_m == DX
    assert "lbmpy" in available_tiers()
    s = solver.stats()
    assert s["target"] == "cpu" and s["tau"] > 0.51 and s["step_ms"] > 0


def test_stable_and_finite_inflow_recovered(solver):
    v = to_numpy(solver.sample(np.random.default_rng(0).uniform([0, 0, 0], [400, 300, 119], (400, 3))))
    assert np.isfinite(v).all()
    assert np.abs(v).max() < 4 * solver.core.units.u_scale * 0.08       # nothing blew up (<= 4x the lattice cap)
    up = to_numpy(solver.sample(np.array([[20.0, 20.0, 30.0]])))[0]
    expected = float(L.log_law(30.0, 8.0, 0.5))
    assert up[0] == pytest.approx(expected, rel=0.25)
    assert abs(up[1]) < 0.3 * expected


def test_wake_slower_than_freestream_and_zero_inside(solver):
    # building 0 (110..150 x 190..230, 60 m): wake is east of it (x > 150) at the same y
    wake = np.linalg.norm(to_numpy(solver.sample(np.array([[175.0, 210.0, 30.0]]))))
    free = np.linalg.norm(to_numpy(solver.sample(np.array([[20.0, 250.0, 30.0]]))))
    assert wake < 0.75 * free, (wake, free)
    assert np.all(to_numpy(solver.sample(np.array([[130.0, 210.0, 20.0]]))) == 0.0)
    sl = to_numpy(solver.slice_z(30.0))
    assert sl.shape == (50, 38, 3) and np.isfinite(sl).all()


def test_mlups_measured_over_100_steps(solver):
    for _ in range(80):
        solver.step(1)
    assert solver.stats()["mlups"] > 0.0


def test_relayout_settles_then_swaps_atomically(scenario):
    w = make_wind("lbmpy", scenario.layout, scenario.inflow, dx_m=DX, relayout_chunk_steps=40,
                  settle_tol=5e-3, settle_min_steps=120)
    for _ in range(100):
        w.step(1)
    probe = np.array([[300.0, 210.0, 12.0]])               # inside building 3 (280..320 x 200..240, 25 m)
    assert np.all(to_numpy(w.sample(probe)) == 0.0)
    moved = Layout(scenario.layout.area_m, tuple(dataclasses.replace(b, x=b.x - 120) if b.id == 3 else b
                                                 for b in scenario.layout.buildings))
    before = to_numpy(w.sample(np.array([[20.0, 20.0, 30.0]]))).copy()
    w.begin_relayout(moved, scenario.inflow)
    assert not w.relayout_ready()
    n = 0
    while not w.relayout_ready() and n < 400:              # old wind keeps running while the new one settles
        w.step(1)
        assert np.all(to_numpy(w.sample(probe)) == 0.0)    # still the old geometry until the commit
        n += 1
    assert w.relayout_ready() and n >= 3
    w.commit_relayout()
    assert not np.all(to_numpy(w.sample(probe)) == 0.0)    # building 3 moved away: cell is fluid now
    assert np.all(to_numpy(w.sample(np.array([[180.0, 220.0, 12.0]]))) == 0.0)
    assert np.isfinite(to_numpy(w.sample(before))).all()


def test_inflow_direction_change_via_relayout(scenario):
    w = make_wind("lbmpy", scenario.layout, dataclasses.replace(scenario.inflow, direction_deg=90.0), dx_m=DX)
    for _ in range(150):
        w.step(1)
    v = to_numpy(w.sample(np.array([[20.0, 20.0, 30.0]])))[0]
    assert v[1] > 3.0 and abs(v[0]) < 0.4 * v[1]           # blowing north now


def test_gpu_target_without_cuda_fails_loudly(scenario):
    if backend.is_gpu:
        pytest.skip("this machine has CUDA")
    with pytest.raises(RuntimeError, match="no CUDA"):
        make_wind("lbmpy", scenario.layout, scenario.inflow, dx_m=DX, target="gpu")


@pytest.mark.gpu
def test_cpu_and_gpu_agree_within_1e4_after_50_steps(scenario):
    if not backend.is_gpu:
        pytest.skip("no CUDA device / cupy")
    small = Layout((80.0, 60.0), (Building(0, 30, 20, 16, 16, 20),), ceiling_m=48.0)
    inflow = Inflow(8.0, 0.0, 0.5)
    cpu = L._Core(small, inflow, 4.0, "cpu", "srt"); gpu = L._Core(small, inflow, 4.0, "gpu", "srt")
    cpu.step(50); gpu.step(50)
    a, b = to_numpy(cpu.velocity_si()), to_numpy(gpu.velocity_si())
    scale = np.abs(a).max()
    assert np.abs(a - b).max() / scale < 1e-4


@pytest.mark.slow
def test_service_runs_the_lbmpy_tier_on_a_coarse_cpu_grid(scenario):
    from service.server import Service
    svc = Service(scenario, "synthetic", n_tracers=200, tick_hz=100.0)
    assert "lbmpy" in svc.hello()["tiers_available"]
    ack = svc.handle({"cmd": "set_tier", "tier": "lbmpy", "id": 1})
    assert ack["ok"], ack
    assert svc.tier == "lbmpy" and svc.sim.wind.name == "lbmpy" and svc.sim.wind.core.shape == (50, 38, 15)
    for _ in range(30):
        data = svc.tick()
    assert len(data) < 1_000_000
    m = svc.stats_message()
    assert m["tier"] == "lbmpy" and m["wind"]["tau"] > 0.51
