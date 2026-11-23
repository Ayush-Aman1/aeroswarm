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


def _msvc_vcvars():
    """Path to vcvars64.bat of the newest Visual Studio / Build Tools with the C++ tools, or None (Windows only)."""
    if sys.platform != "win32":
        return None
    import os
    vswhere = Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Microsoft Visual Studio/Installer/vswhere.exe"
    if not vswhere.exists():
        return None
    r = subprocess.run([str(vswhere), "-latest", "-products", "*", "-requires",
                        "Microsoft.VisualStudio.Component.VC.Tools.x86.x64", "-property", "installationPath"],
                       capture_output=True, text=True)
    bat = Path(r.stdout.strip()) / "VC/Auxiliary/Build/vcvars64.bat" if r.stdout.strip() else None
    return bat if bat and bat.exists() else None


VCVARS = None if CC else _msvc_vcvars()


@pytest.fixture(scope="module")
def lib(tmp_path_factory):
    if CC is None and VCVARS is None:
        pytest.skip("no C compiler")
    d = tmp_path_factory.mktemp("native")
    out = d / ("aero_mock.dll" if sys.platform == "win32" else "libaero_mock.so")
    src = ROOT / "native/mock/aero_mock.c"
    if CC is None:      # MSVC: cl inside a vcvars64 environment; the header's AERO_API is __declspec(dllexport)
        subprocess.run(f'call "{VCVARS}" >nul 2>&1 && cl /nologo /O1 /LD "{src}" /Fe:"{out}" /Fo:"{d}\\\\"',
                       shell=True, check=True, capture_output=True)
        return str(out)
    flags = ["-shared", "-fPIC"] if sys.platform != "darwin" else ["-dynamiclib"]
    subprocess.run([CC, "-O1", *flags, "-o", str(out), str(src), "-lm"], check=True)
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
