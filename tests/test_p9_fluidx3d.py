import json
import shutil
from pathlib import Path

import numpy as np
import pytest

from engine.backend import to_numpy
from engine.scenario.schema import Building, Inflow, Layout, load_scenario
from engine.wind.base import WindSource
from engine.wind.factory import available_tiers, make_wind
from engine.wind.fluidx3d_field import FluidX3DField, angle_distance, layout_distance, scan
from tools.fluidx3d import batch
from tools.fluidx3d.case import DIRECTIONS_DEG, Case, field_bytes
from tools.fluidx3d.convert import convert_frame, convert_run, read_vtk_vector, write_vtk_fluidx3d

ROOT = Path(__file__).resolve().parents[1]
LAY = Layout((400.0, 300.0), (Building(0, 180, 120, 40, 40, 70),))
INF = Inflow(8.0, 0.0, 0.5)


def test_case_geometry_and_budget():
    sc = load_scenario(ROOT / "scenarios/block_small.json")
    c = Case(sc.layout, sc.inflow)
    c.check()
    assert c.lbm_u_ref <= 0.07 / 1.25 + 1e-9 and 0.5 + 3 * c.nu_floor > 0.51
    assert c.gpu_mb() < 4500 and c.shape[0] % 4 == 0
    # rotation round trip, and the city centre lands on the domain centre
    for th in (0, 45, 90, 225):
        for p in [(10.0, 20.0), (390.0, 280.0), (200.0, 150.0)]:
            q = c.to_city(c.to_dom(p, th), th)
            assert q == pytest.approx(p, abs=1e-9)
    assert c.to_dom(c.city_c, 33.0) == pytest.approx(c.dom_c)
    # whole city fits inside the domain for all 8 directions
    for th in DIRECTIONS_DEG:
        for p in [(0, 0), (400, 0), (0, 300), (400, 300)]:
            x, y = c.to_dom(p, th)
            assert 0 < x < c.size_m[0] and 0 < y < c.size_m[1]
    assert 3 * 8 * field_bytes(sc.layout) < 3e9          # guide: all fields under 3 GB


def test_case_text_is_complete():
    sc = load_scenario(ROOT / "scenarios/block_small.json")
    t = Case(sc.layout, sc.inflow).case_text(45.0, "/tmp/x")
    keys = {l.split()[0] for l in t.splitlines() if l and l[0] != "#"}
    assert {"nx", "ny", "nz", "dx_m", "u_ref_si", "z0", "lbm_u_ref", "nu_floor", "cos_t", "sin_t", "dom_cx", "dom_cy",
            "city_cx", "city_cy", "settle_steps", "snap_steps", "n_snaps", "export_dir", "building"} <= keys
    assert t.count("\nbuilding ") == 6
    tpl = (ROOT / "tools/fluidx3d/setup.cpp.template").read_text()
    for k in keys - {"export_dir", "building"}:         # every key the Python writes is read by the C++
        assert f'"{k}"' in tpl, k


def test_defines_patch():
    up = (ROOT / "third_party/FluidX3D/src/defines.hpp")
    if not up.exists():
        pytest.skip("third_party/FluidX3D not cloned")
    p = batch.patch_defines(up.read_text())
    lines = [l.split("//")[0].strip() for l in p.splitlines()]
    for must in ("#define D3Q19", "#define EQUILIBRIUM_BOUNDARIES", "#define SUBGRID", "#define FP16S", "#define SRT"):
        assert must in lines, must
    assert "#define BENCHMARK" not in lines and "#define INTERACTIVE_GRAPHICS" not in lines


def _fake_vtk_dir(tmp_path, case, theta, frames=3, speed=5.0):
    nx, ny, nz = case.shape
    d = tmp_path / "vtk"; d.mkdir()
    for k in range(frames):
        u = np.zeros((nx, ny, nz, 3), np.float32)
        u[..., 0] = speed + k            # uniform flow along the lattice +x, different per frame
        write_vtk_fluidx3d(d / f"u-{k:09d}.vtk", u, case.dx_m)
    return d


def test_vtk_roundtrip_and_conversion_on_synthetic_fixture(tmp_path):
    case = Case(LAY, INF, dx_m=4.0)         # coarse for speed
    u = np.random.default_rng(0).normal(size=(12, 10, 8, 3)).astype(np.float32)
    write_vtk_fluidx3d(tmp_path / "a.vtk", u, 4.0)
    back, sp, dims = read_vtk_vector(tmp_path / "a.vtk")
    np.testing.assert_array_equal(back, u)
    assert dims == (12, 10, 8) and sp == (4.0, 4.0, 4.0)
    pv = pytest.importorskip("pyvista")     # independent reader agrees with the fast parser
    g = pv.read(str(tmp_path / "a.vtk"))
    arr = np.asarray(g.point_data[g.point_data.keys()[0]]).reshape(8, 10, 12, 3).transpose(2, 1, 0, 3)
    np.testing.assert_allclose(arr, u, rtol=1e-6)


@pytest.mark.parametrize("theta", [0.0, 90.0, 45.0, 270.0])
def test_converter_rotates_velocity_back_to_the_city_frame(tmp_path, theta):
    case = Case(LAY, INF, dx_m=4.0)
    d = _fake_vtk_dir(tmp_path, case, theta, frames=1, speed=5.0)
    f = convert_frame(d / "u-000000000.vtk", case, theta, zmax_m=80.0).astype(np.float32)
    assert f.dtype == np.float32 and f.shape == (100, 75, 20, 3)
    far = f[3:20, 3:20, 5:15]               # away from buildings
    t = np.deg2rad(theta)
    np.testing.assert_allclose(far[..., 0], 5.0 * np.cos(t), atol=0.02)
    np.testing.assert_allclose(far[..., 1], 5.0 * np.sin(t), atol=0.02)
    # zero inside the building (x 180-220, y 120-160, z<=70)
    assert np.all(f[46:54, 31:39, :16] == 0.0)


def test_convert_run_writes_float16_frames_and_meta(tmp_path):
    case = Case(LAY, INF, dx_m=4.0)
    d = _fake_vtk_dir(tmp_path, case, 0.0, frames=3)
    meta = convert_run(d, tmp_path / "out", case, 0.0, "unit", zmax_m=80.0, source="test", frame_dt_s=2.0)
    fr = np.load(tmp_path / "out/frame_01.npy")
    assert fr.dtype == np.float16 and fr.shape == tuple(meta["shape"]) and meta["n_frames"] == 3
    assert np.load(tmp_path / "out/frame_02.npy")[3, 3, 5, 0] == pytest.approx(7.0, abs=0.02)


def test_batch_dry_run_reports_budget(capsys):
    assert batch.main(["--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "24 job(s)" in out and "field budget: 2.76 GB" in out
    assert batch.main(["--dry-run", "--zmax", "200"]) == 2          # over 3 GB: refused


@pytest.fixture
def fake_fields(tmp_path):
    out = tmp_path / "fields"
    sc = ROOT / "scenarios/block_small.json"
    rc = batch.main(["--solver", "fake", "--scenarios", str(sc), "--directions", "0", "90", "--dx", "4",
                     "--out", str(out), "--work", str(tmp_path / "work")])
    assert rc == 0
    return out


@pytest.mark.slow
def test_field_adapter_on_fixture_fields(fake_fields):
    # NOTE: fixture fields come from the synthetic wind (meta.source == FAKE-TEST-ONLY) - they test plumbing only.
    meta = json.loads((fake_fields / "block_small/dir_090/meta.json").read_text())
    assert meta["source"] == "FAKE-TEST-ONLY" and meta["n_frames"] == 16
    assert set(scan(fake_fields)["block_small"]) == {0.0, 90.0}
    sc = load_scenario(ROOT / "scenarios/block_small.json")
    w = make_wind("fluidx3d", sc.layout, sc.inflow, field_dir=fake_fields)
    assert isinstance(w, WindSource) and w.name == "fluidx3d" and w.dx_m == 4.0
    # wake behind the tallest building (id 0: 110,190 40x40x60) is visible in slice_z(30)
    sl = np.linalg.norm(to_numpy(w.slice_z(30.0)), axis=2)
    dx = w.dx_m
    wake = sl[int(165 / dx):int(185 / dx), int(205 / dx):int(215 / dx)].mean()
    free = sl[int(20 / dx):int(40 / dx), int(205 / dx):int(215 / dx)].mean()          # far upstream, same row
    assert wake < 0.7 * free, (wake, free)
    # exactly zero inside a building, finite everywhere, shapes
    assert np.all(to_numpy(w.sample(np.array([[130.0, 210.0, 20.0]]))) == 0.0)
    p = np.random.default_rng(1).uniform([0, 0, 0], [400, 300, 119], (300, 3))
    v = to_numpy(w.sample(p))
    assert v.shape == (300, 3) and np.isfinite(v).all()
    # time loop: frames blend, field changes with time, loops with the period
    a = to_numpy(w.sample(np.array([[200.0, 200.0, 30.0]]))).copy()
    w.step(int(3.3 / w.dt_s)); b = to_numpy(w.sample(np.array([[200.0, 200.0, 30.0]])))
    assert not np.allclose(a, b)
    w.time_s = w._period; c = to_numpy(w.sample(np.array([[200.0, 200.0, 30.0]])))
    np.testing.assert_allclose(c, a, atol=1e-5)
    # above zmax the log-law ratio applies (no NaN, faster than below)
    hi = to_numpy(w.sample(np.array([[5.0, 20.0, 115.0], [5.0, 20.0, 70.0]])))
    assert np.linalg.norm(hi[0]) > np.linalg.norm(hi[1])


@pytest.mark.slow
def test_relayout_picks_nearest_preset_and_direction(fake_fields, caplog):
    sc = load_scenario(ROOT / "scenarios/block_small.json")
    w = make_wind("fluidx3d", sc.layout, sc.inflow, field_dir=fake_fields)
    moved = Layout(sc.layout.area_m, tuple(Building(b.id, b.x + 10, b.y, b.w, b.d, b.h) if b.id == 3 else b
                                          for b in sc.layout.buildings))
    with caplog.at_level("WARNING"):
        w.begin_relayout(moved, Inflow(8.0, 80.0, 0.5))
    assert w.relayout_ready() and w.active_dir_deg == 0.0           # not committed yet
    w.commit_relayout()
    assert w.active_dir_deg == 90.0 and w.active_preset == "block_small" and w.preset_distance_m == 10.0
    assert "snapped" in caplog.text and "differs from preset" in caplog.text
    assert w.stats()["preset"] == "block_small"
    assert w.presets()[0]["directions"] == [0.0, 90.0]


def test_missing_fields_is_a_clear_error_and_tier_unavailable(tmp_path):
    assert not FluidX3DField.available(tmp_path)
    with pytest.raises(FileNotFoundError, match="run_fluidx3d_batch"):
        FluidX3DField(field_dir=tmp_path)
    assert "fluidx3d" not in available_tiers(tmp_path)


def test_distance_helpers():
    assert angle_distance(350, 10) == 20 and angle_distance(0, 180) == 180
    assert layout_distance(LAY, LAY) == 0.0
    other = Layout(LAY.area_m, (Building(0, 190, 120, 40, 40, 70),))
    assert layout_distance(LAY, other) == 10.0


@pytest.mark.fluidx3d
def test_real_fluidx3d_smoke(tmp_path):
    """Builds FluidX3D from the clone and runs one tiny job. Skips cleanly when no OpenCL device/clone."""
    clone = ROOT / "third_party" / "FluidX3D"
    if not (clone / "src" / "lbm.cpp").exists():
        pytest.skip("third_party/FluidX3D not cloned")
    try:
        exe = batch.build(batch.prepare_tree(clone, tmp_path / "work"))
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"cannot build FluidX3D here: {exc}")
    sc = load_scenario(ROOT / "scenarios/block_small.json")
    case = Case(sc.layout, sc.inflow, dx_m=8.0, n_snaps=2, snap_interval_s=1.0, settle_flowthroughs=0.3)
    try:
        batch.run_real(exe, case, 0.0, tmp_path / "vtk", tmp_path / "log.txt", 300)
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"no usable OpenCL device: {exc}")
    meta = convert_run(tmp_path / "vtk", tmp_path / "out", case, 0.0, "smoke", zmax_m=80.0)
    f = np.load(tmp_path / "out/frame_00.npy").astype(np.float32)
    assert np.isfinite(f).all() and np.linalg.norm(f[1, 3, 3]) > 1.0 and meta["n_frames"] == 2
