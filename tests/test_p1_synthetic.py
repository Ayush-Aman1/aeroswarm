import numpy as np
import pytest

from engine.backend import to_numpy
from engine.scenario.schema import Building, Inflow, Layout
from engine.wind.base import WindSource
from engine.wind.factory import make_wind
from engine.wind.synthetic import log_law

LAY = Layout((400.0, 300.0), (Building(0, 180, 120, 40, 40, 50),))


def mk(direction=0.0, layout=LAY, speed=8.0):
    return make_wind("synthetic", layout, Inflow(speed, direction, 0.5))


def test_implements_protocol():
    w = mk()
    assert isinstance(w, WindSource)
    assert w.bounds_m == (400.0, 300.0, 120.0) and w.dx_m == 2.0


def test_zero_inside_buildings():
    w = mk()
    pts = np.array([[200, 140, 10], [185, 125, 49], [200, 140, 49.9]], float)
    assert np.all(to_numpy(w.sample(pts)) == 0.0)
    assert np.all(to_numpy(w.slice_z(30.0))[95:105, 65:75] == 0.0)   # inside the 180..220 x 120..160 footprint
    assert np.abs(to_numpy(w.sample(np.array([[200, 140, 55.0]])))).max() > 0.0   # above the roof


def test_inflow_recovered_far_upstream():
    w = mk()
    for z in (10.0, 30.0, 80.0):
        v = to_numpy(w.sample(np.array([[4.0, 20.0, z]])))[0]
        assert v[0] == pytest.approx(log_law(z, 8.0, 0.5), rel=0.03)
        assert abs(v[1]) < 1e-3 and abs(v[2]) < 1e-3


def test_wake_slower_than_freestream():
    w = mk()
    wake = to_numpy(w.sample(np.array([[235.0, 140.0, 30.0]])))[0]
    free = to_numpy(w.sample(np.array([[235.0, 40.0, 30.0]])))[0]
    assert np.linalg.norm(wake) < 0.6 * np.linalg.norm(free)


def test_speedup_beside_lateral_faces():
    w = mk()
    side = np.linalg.norm(to_numpy(w.sample(np.array([[200.0, 168.0, 30.0]]))))
    free = np.linalg.norm(to_numpy(w.sample(np.array([[200.0, 40.0, 30.0]]))))
    assert side > 1.15 * free


def test_changes_over_time_in_wake_only():
    w = mk()
    a = to_numpy(w.slice_z(30.0)).copy()
    w.step(37)
    b = to_numpy(w.slice_z(30.0))
    diff = np.abs(a - b).max(axis=2)
    xs = (np.arange(200) + 0.5) * 2
    in_wake = (xs[:, None] > 215) & (xs[:, None] < 215 + 5 * 50) & (np.abs((np.arange(150) + 0.5)[None, :] * 2 - 140) < 60)
    assert diff[in_wake].max() > 0.3
    assert diff[~in_wake].max() < 1e-6
    # upstream point unchanged
    p = np.array([[10.0, 140.0, 30.0]])
    w2 = mk()
    v0 = to_numpy(w2.sample(p)); w2.step(50)
    np.testing.assert_allclose(v0, to_numpy(w2.sample(p)), atol=1e-6)


def test_shedding_frequency_matches_strouhal():
    w = mk()
    p = np.array([[240.0, 140.0, 30.0]])   # centreline wake
    sig = []
    for _ in range(2000):
        w.step(1)
        sig.append(to_numpy(w.sample(p))[0, 1])
    sig = np.array(sig) - np.mean(sig)
    f = np.fft.rfftfreq(len(sig), 0.05)[np.argmax(np.abs(np.fft.rfft(sig * np.hanning(len(sig)))))]
    U, Wd = log_law(50.0, 8.0, 0.5), 40.0
    assert f == pytest.approx(0.2 * U / Wd, rel=0.1)


def test_rotated_wind_moves_wake():
    w = mk(90.0)    # blowing north: wake is north of the building (larger y)
    north = np.linalg.norm(to_numpy(w.sample(np.array([[200.0, 185.0, 30.0]]))))
    south = np.linalg.norm(to_numpy(w.sample(np.array([[200.0, 20.0, 30.0]]))))
    assert north < 0.6 * south
    v = to_numpy(w.sample(np.array([[20.0, 30.0, 30.0]])))[0]
    assert v[1] > 5 and abs(v[0]) < 1e-3


def test_trilinear_is_continuous():
    w = mk()
    a = to_numpy(w.sample(np.array([[100.0, 100.0, 30.0], [100.01, 100.0, 30.0]])))
    assert np.abs(a[0] - a[1]).max() < 0.01


def test_relayout_instant_and_atomic():
    w = mk()
    before = to_numpy(w.sample(np.array([[235.0, 140.0, 30.0]])))
    new = Layout(LAY.area_m, (Building(0, 80, 120, 40, 40, 50),), version=1)
    w.begin_relayout(new, Inflow(8.0, 0.0, 0.5))
    assert w.relayout_ready()
    np.testing.assert_array_equal(before, to_numpy(w.sample(np.array([[235.0, 140.0, 30.0]]))))  # old until commit
    w.commit_relayout()
    after = to_numpy(w.sample(np.array([[235.0, 140.0, 30.0]])))[0]
    assert np.linalg.norm(after) > 4          # wake moved away
    assert to_numpy(w.sample(np.array([[100.0, 140.0, 20.0]])))[0].tolist() == [0, 0, 0]


def test_sample_shapes_and_determinism():
    w1, w2 = mk(), mk()
    p = np.random.default_rng(3).uniform([0, 0, 0], [400, 300, 119], (500, 3))
    for _ in range(5):
        w1.step(); w2.step()
    a, b = to_numpy(w1.sample(p)), to_numpy(w2.sample(p))
    assert a.shape == (500, 3) and np.array_equal(a, b) and np.isfinite(a).all()
