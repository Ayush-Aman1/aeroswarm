import json
from pathlib import Path

import numpy as np
import pytest

from engine import backend
from engine.protocol import Snapshot, pack_snapshot, read_replay, unpack_snapshot, write_replay_frame
from engine.scenario import schema as S

ROOT = Path(__file__).resolve().parents[1]
SCENARIOS = sorted((ROOT / "scenarios").glob("*.json"))


def test_scenarios_exist_and_validate():
    names = {p.stem for p in SCENARIOS}
    assert {"block_small", "street_canyon", "tower_cluster"} <= names
    for p in SCENARIOS:
        S.load_scenario(p)


def test_block_small_matches_guide():
    sc = S.load_scenario(ROOT / "scenarios/block_small.json")
    assert sc.layout.area_m == (400.0, 300.0)
    assert len(sc.layout.buildings) == 6 and len(sc.depots) == 2 and len(sc.missions) == 50
    assert sc.seed == 1
    assert all(20 <= b.h <= 60 for b in sc.layout.buildings)


def test_schema_roundtrip(tmp_path):
    sc = S.load_scenario(ROOT / "scenarios/block_small.json")
    p = tmp_path / "x.json"
    S.dump_scenario(sc, p)
    assert S.load_scenario(p) == sc
    assert S.scenario_from_dict(json.loads(json.dumps(sc.to_dict()))) == sc


@pytest.mark.parametrize("mutate,msg", [
    (lambda d: d["layout"]["buildings"][0].update(w=-1), "positive"),
    (lambda d: d["layout"]["buildings"][0].update(x=390), "outside"),
    (lambda d: d["layout"]["buildings"][1].update(id=0), "duplicate"),
    (lambda d: d["layout"]["buildings"][1].update(x=110, y=190), "overlap"),
    (lambda d: d["inflow"].update(speed_ms=0), "speed"),
    (lambda d: d["missions"][0].update(depot=9), "unknown depot"),
    (lambda d: d["depots"][0].update(x=120, y=200), "inside a building"),
    (lambda d: d["sim"].update(routing="x"), "routing"),
    (lambda d: d["sim"].update(bogus=1), "unknown sim"),
])
def test_schema_rejects_bad_input(mutate, msg):
    d = json.loads((ROOT / "scenarios/block_small.json").read_text())
    mutate(d)
    with pytest.raises(S.SchemaError, match=msg):
        S.scenario_from_dict(d)


def test_layout_replace_bumps_version():
    sc = S.load_scenario(ROOT / "scenarios/block_small.json")
    b = sc.layout.get(0)
    lay = sc.layout.replace_building(S.Building(0, b.x + 5, b.y, b.w, b.d, b.h))
    assert lay.version == sc.layout.version + 1 and lay.get(0).x == b.x + 5


def test_backend_selection(monkeypatch):
    xp, _, name = backend.select_backend(force_cpu=True)
    assert xp is np and name == "numpy"
    # the test environment has no cupy: auto-detect must fall to numpy without raising
    monkeypatch.setitem(__import__("sys").modules, "cupy", None)
    xp, _, name = backend.select_backend(force_cpu=False)
    assert xp is np and name == "numpy"
    assert backend.to_numpy(np.arange(3)).tolist() == [0, 1, 2]


def test_backend_loud_failure(monkeypatch, caplog):
    class FakeRuntime:
        @staticmethod
        def getDeviceCount():
            raise RuntimeError("driver mismatch")

    class FakeCupy:
        class cuda:
            runtime = FakeRuntime

    monkeypatch.setitem(__import__("sys").modules, "cupy", FakeCupy)
    with caplog.at_level("ERROR"):
        xp, _, name = backend.select_backend(force_cpu=False, allow_fallback=True)
    assert name == "numpy" and "GPU BACKEND FAILED" in caplog.text
    with pytest.raises(RuntimeError):
        backend.select_backend(force_cpu=False, allow_fallback=False)


def _snap(n=7, m=11, nx=5, ny=4):
    r = np.random.default_rng(0)
    return Snapshot(step=42, sim_time=2.1, layout_version=3,
                    drone_pos=r.normal(size=(n, 3)).astype("f4"), drone_vel=r.normal(size=(n, 3)).astype("f4"),
                    drone_state=r.integers(0, 16, n).astype("u1"), tracers=r.normal(size=(m, 3)).astype("f4"),
                    slice_speed=r.uniform(0, 12, (nx, ny)).astype("f2"), slice_z=30.0, flags=1)


@pytest.mark.parametrize("n,m,nx,ny", [(7, 11, 5, 4), (0, 0, 0, 0), (1000, 8000, 100, 75), (3, 1, 3, 3)])
def test_protocol_roundtrip(n, m, nx, ny):
    s = _snap(n, m, nx, ny)
    b = pack_snapshot(s)
    assert len(b) % 4 == 0
    t = unpack_snapshot(b)
    assert (t.step, t.layout_version, t.flags, t.slice_z) == (42, 3, 1, 30.0)
    assert t.sim_time == pytest.approx(2.1, rel=1e-6)
    for a in ("drone_pos", "drone_vel", "drone_state", "tracers", "slice_speed"):
        np.testing.assert_array_equal(getattr(t, a), getattr(s, a))


def test_protocol_size_budget():
    assert len(pack_snapshot(_snap(1000, 8000, 100, 75))) < 1_000_000


def test_protocol_rejects_garbage():
    with pytest.raises(ValueError):
        unpack_snapshot(b"NOPE" + bytes(40))
    with pytest.raises(ValueError):
        unpack_snapshot(pack_snapshot(_snap())[:-4])


def test_replay_roundtrip(tmp_path):
    p = tmp_path / "r.bin"
    with open(p, "wb") as fh:
        for k in range(3):
            s = _snap()
            s.step = k
            write_replay_frame(fh, s)
    frames = read_replay(p)
    assert [f.step for f in frames] == [0, 1, 2]


def test_slice_is_x_fastest_on_the_wire():
    """docs/protocol.md: index j*nx + i, i.e. the byte stream walks x first."""
    nx, ny = 4, 3
    sl = (np.arange(nx)[:, None] + 10 * np.arange(ny)[None, :]).astype("f2")      # value = i + 10 j
    s = _snap(2, 2, nx, ny)
    s.slice_speed = sl
    b = pack_snapshot(s)
    body = np.frombuffer(b[-(nx * ny * 2):], "<f2")
    assert body.tolist() == [i + 10 * j for j in range(ny) for i in range(nx)]
