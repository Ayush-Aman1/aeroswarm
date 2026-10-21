"""The ctypes adapter against native/mock/aero_mock.c compiled on the fly: proves the C ABI, the relayout protocol
and error handling that the team's CUDA engine must satisfy (docs/LINKING_GUIDE.md)."""
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from engine.backend import to_numpy
from engine.scenario.schema import Building, Inflow, Layout, load_scenario
from engine.wind.base import WindSource
from engine.wind.factory import make_wind
from engine.wind.native import NativeError, NativeWind

ROOT = Path(__file__).resolve().parents[1]
CC = shutil.which("cc") or shutil.which("clang") or shutil.which("gcc")


@pytest.fixture(scope="module")
def lib(tmp_path_factory):
    if CC is None:
        pytest.skip("no C compiler")
    out = tmp_path_factory.mktemp("native") / ("aero_mock.dll" if sys.platform == "win32" else "libaero_mock.so")
    flags = ["-shared", "-fPIC"] if sys.platform != "darwin" else ["-dynamiclib"]
    subprocess.run([CC, "-O1", *flags, "-o", str(out), str(ROOT / "native/mock/aero_mock.c"), "-lm"], check=True)
    return str(out)


LAY = Layout((400.0, 300.0), (Building(0, 180, 120, 40, 40, 70),))
INF = Inflow(8.0, 0.0, 0.5)


def test_native_adapter_implements_the_interface(lib):
    w = make_wind("native", LAY, INF, dx_m=4.0, lib_path=lib)
    assert isinstance(w, WindSource) and w.name == "native" and w.bounds_m == (400.0, 300.0, 120.0)
    v = to_numpy(w.sample(np.array([[20.0, 20.0, 30.0], [200.0, 140.0, 10.0]])))
    assert v.shape == (2, 3) and v[0, 0] > 5 and v[0, 1] == pytest.approx(0, abs=1e-4)
    assert np.all(v[1] == 0.0)                                             # inside the building
    sl = to_numpy(w.slice_z(30.0))
    assert sl.shape == (100, 75, 3) and sl[2, 2, 0] > 5 and np.all(sl[47:53, 33:37] == 0)
    a = to_numpy(w.sample(np.array([[20.0, 20.0, 30.0]]))).copy()
    w.step(20)
    assert not np.allclose(a, to_numpy(w.sample(np.array([[20.0, 20.0, 30.0]]))))        # time dependent
    assert w.stats() == {"mlups": 1234.5, "step_ms": 0.5}


def test_native_relayout_protocol(lib):
    w = NativeWind(dx_m=4.0, lib_path=lib); w.reset(LAY, INF)
    probe = np.array([[300.0, 140.0, 10.0]])
    assert np.linalg.norm(to_numpy(w.sample(probe))) > 0
    new = Layout(LAY.area_m, (Building(0, 280, 120, 40, 40, 70),), version=1)
    w.begin_relayout(new, Inflow(8.0, 90.0, 0.5))
    n = 0
    while not w.relayout_ready():
        w.step(1); n += 1
        assert np.linalg.norm(to_numpy(w.sample(probe))) > 0     # old geometry until commit
        assert n < 10
    w.commit_relayout()
    assert np.all(to_numpy(w.sample(probe)) == 0.0)
    v = to_numpy(w.sample(np.array([[20.0, 20.0, 30.0]])))[0]
    assert v[1] > 5 and abs(v[0]) < 1e-3                          # new inflow direction (north)


def test_native_errors_are_loud(tmp_path, lib):
    with pytest.raises(FileNotFoundError, match="LINKING_GUIDE"):
        NativeWind(lib_path=str(tmp_path / "nope.so"))
    w = NativeWind(dx_m=4.0, lib_path=lib); w.reset(LAY, INF)
    with pytest.raises(NativeError, match="no relayout pending"):
        w.lib.aero_relayout_commit(w.h) < 0 and w._check(-1, "aero_relayout_commit")


def test_compare_winds_identical_sources_agree_and_different_ones_do_not():
    from tools.compare_winds import compare
    sc = load_scenario(ROOT / "scenarios/block_small.json")
    same, _ = compare(sc, "synthetic", "synthetic", steps=5)
    assert same["rel_l2"] == pytest.approx(0.0, abs=1e-7) and same["pass"] and same["wake_ratio_b_over_a"] == pytest.approx(1.0)
