import asyncio
import dataclasses
import json
from pathlib import Path

import numpy as np
import pytest
from aiohttp.test_utils import TestClient, TestServer

from engine.protocol import unpack_snapshot
from engine.scenario.schema import load_scenario
from service.server import Service, make_app
from service.tracers import Tracers

ROOT = Path(__file__).resolve().parents[1]


def make_service(n_tracers=500, **kw):
    sc = load_scenario(ROOT / "scenarios/block_small.json")
    sc = dataclasses.replace(sc, sim=dataclasses.replace(sc.sim, start_window_s=5.0))
    return Service(sc, "synthetic", n_tracers=n_tracers, tick_hz=200.0, **kw)


def run(coro):
    return asyncio.run(coro)


async def session(svc, fn):
    client = TestClient(TestServer(make_app(svc)))
    await client.start_server()
    try:
        ws = await client.ws_connect("/ws")
        hello = json.loads((await ws.receive()).data)
        return await fn(client, ws, hello)
    finally:
        await client.close()


async def recv_until(ws, pred, n=400):
    """Read frames until pred(kind, payload) is truthy; returns payload."""
    for _ in range(n):
        msg = await asyncio.wait_for(ws.receive(), 10)
        if msg.type.name == "TEXT":
            d = json.loads(msg.data)
            if pred("json", d):
                return d
        elif msg.type.name == "BINARY":
            if pred("bin", msg.data):
                return msg.data
    raise AssertionError("expected message never arrived")


async def cmd(ws, **kw):
    await ws.send_str(json.dumps(kw))
    return await recv_until(ws, lambda k, d: k == "json" and d.get("type") == "ack" and d.get("id") == kw.get("id"))


def test_hello_and_binary_snapshots():
    async def go(client, ws, hello):
        assert hello["type"] == "hello" and hello["protocol"] == 1 and hello["tier"] == "synthetic"
        assert len(hello["layout"]["buildings"]) == 6 and len(hello["depots"]) == 2 and len(hello["targets"]) == 50
        assert "synthetic" in hello["tiers_available"]
        data = await recv_until(ws, lambda k, d: k == "bin")
        s = unpack_snapshot(data)
        assert s.drone_pos.shape == (50, 3) and s.tracers.shape == (500, 3) and s.slice_speed.shape == (200, 150)
        assert s.slice_z == 30.0 and len(data) < 1_000_000
        st = await recv_until(ws, lambda k, d: k == "json" and d.get("type") == "stats")
        assert st["snapshot_bytes"] == len(data) or st["snapshot_bytes"] > 0
        assert st["tier"] == "synthetic" and "metrics" in st
    run(session(make_service(), go))


def test_snapshot_size_budget_at_full_load():
    svc = make_service(n_tracers=8000)
    data = svc.tick()
    assert len(data) < 1_000_000
    s = unpack_snapshot(data)
    assert s.tracers.shape == (8000, 3)


def test_pause_resume_and_routing():
    async def go(client, ws, hello):
        a = await cmd(ws, cmd="pause", id=1); assert a["ok"]
        s1 = unpack_snapshot(await recv_until(ws, lambda k, d: k == "bin"))
        s2 = unpack_snapshot(await recv_until(ws, lambda k, d: k == "bin"))
        assert s1.step == s2.step and (s2.flags & 1)
        assert (await cmd(ws, cmd="resume", id=2))["ok"]
        assert (await cmd(ws, cmd="set_routing", mode="aware", id=3))["ok"]
        bad = await cmd(ws, cmd="set_routing", mode="zigzag", id=4)
        assert not bad["ok"] and "naive|aware" in bad["reason"]
        unk = await cmd(ws, cmd="explode", id=5)
        assert not unk["ok"]
        assert (await cmd(ws, cmd="set_slice_z", z=60, id=6))["ok"]
        s3 = unpack_snapshot(await recv_until(ws, lambda k, d: k == "bin" and unpack_snapshot(d).slice_z == 60.0))
        assert s3.step > s1.step
    run(session(make_service(), go))


def test_rejected_edit_leaves_layout_unchanged():
    async def go(client, ws, hello):
        before = hello["layout"]
        dep = hello["depots"][0]
        b = before["buildings"][0]
        # drop a building on a depot
        a = await cmd(ws, cmd="edit_building", id=1, building=dict(id=b["id"], x=dep["x"] - 10, y=dep["y"] - 10, w=30, d=30, h=40))
        assert not a["ok"] and "depot" in a["reason"]
        # out of bounds, overlap, unknown id
        for bad, key in ((dict(id=b["id"], x=390, y=10, w=40, d=20, h=30), "outside"),
                         (dict(id=b["id"], x=before["buildings"][1]["x"], y=before["buildings"][1]["y"], w=20, d=20, h=30), "overlaps"),
                         (dict(id=99, x=10, y=10, w=20, d=20, h=30), "unknown")):
            a = await cmd(ws, cmd="edit_building", id=2, building=bad)
            assert not a["ok"] and key in a["reason"], a
        for _ in range(20):
            msg = await asyncio.wait_for(ws.receive(), 5)
            if msg.type.name == "TEXT":
                assert json.loads(msg.data).get("type") != "layout"   # nothing was committed
        st = await client.get("/api/state")
        st = await st.json()
        assert st["hello"]["layout"]["buildings"] == before["buildings"] and st["hello"]["layout"]["version"] == before["version"]
    run(session(make_service(), go))


def test_edit_sealing_a_depot_is_rejected():
    from engine.scenario.schema import Building, scenario_from_dict
    from service.edit import validate_edit
    sc = scenario_from_dict(dict(
        name="pocket", seed=1,
        layout=dict(area_m=[400, 300], ceiling_m=120, buildings=[
            dict(id=0, x=10, y=100, w=50, d=20, h=105), dict(id=1, x=10, y=180, w=50, d=20, h=105),
            dict(id=2, x=300, y=10, w=20, d=20, h=30), dict(id=3, x=300, y=100, w=20, d=100, h=105)]),
        inflow=dict(speed_ms=8, direction_deg=0, roughness=0.5),
        depots=[dict(id=0, x=30, y=150)],
        missions=[dict(id=0, depot=0, target=[200, 150]), dict(id=1, depot=0, target=[200, 60])]))
    svc = Service(sc, "synthetic", 10)
    ok, reason, _ = validate_edit(svc.sim, Building(3, 300, 100, 20, 100, 105))          # unchanged: fine
    assert ok, reason
    ok, reason, new = validate_edit(svc.sim, Building(3, 60, 100, 20, 100, 105))         # closes the pocket
    assert not ok and "depot 0 could no longer reach" in reason and new is None
    assert svc.sim.layout.get(3).x == 300 and svc.sim.layout_version == 0               # nothing changed


def test_drone_in_the_way_is_rejected():
    svc = make_service()
    for _ in range(400):
        svc.tick()
    from engine.backend import to_numpy
    from engine.scenario.schema import Building
    from service.edit import validate_edit
    pos = to_numpy(svc.sim.drones.pos)[to_numpy(svc.sim.drones.active)]
    assert len(pos) > 0
    p = pos[0]
    # find a building id whose move target is empty of buildings: place building 5 (small) around the drone
    b = Building(5, float(np.clip(p[0] - 10, 0, 360)), float(np.clip(p[1] - 10, 0, 260)), 20, 20, min(float(p[2]) + 10, 100))
    ok, reason, _ = validate_edit(svc.sim, b)
    assert not ok and ("drone" in reason or "overlaps" in reason or "cover" in reason or "reach" in reason)


def test_accepted_edit_settles_commits_and_broadcasts_layout():
    async def go(client, ws, hello):
        b = hello["layout"]["buildings"][3]                    # 280,200 40x40x25: move it 10 m down (y)
        a = await cmd(ws, cmd="edit_building", id=1, building=dict(id=b["id"], x=b["x"], y=b["y"] - 10, w=b["w"], d=b["d"], h=b["h"]))
        assert a["ok"], a
        lay = await recv_until(ws, lambda k, d: k == "json" and d.get("type") == "layout")
        assert lay["version"] == hello["layout"]["version"] + 1
        assert [x for x in lay["buildings"] if x["id"] == b["id"]][0]["y"] == b["y"] - 10
        # a second edit right after is accepted once settled
        a2 = await cmd(ws, cmd="set_inflow", id=2, direction_deg=45.0)
        assert a2["ok"], a2
        lay2 = await recv_until(ws, lambda k, d: k == "json" and d.get("type") == "layout" and d["version"] == lay["version"] + 1)
        assert lay2["inflow"]["direction_deg"] == 45.0
    run(session(make_service(), go))


def test_load_scenario_and_tier_errors():
    async def go(client, ws, hello):
        a = await cmd(ws, cmd="load_scenario", id=1, name="street_canyon")
        assert a["ok"]
        h = await recv_until(ws, lambda k, d: k == "json" and d.get("type") == "hello")
        assert h["scenario"] == "street_canyon"
        assert not (await cmd(ws, cmd="load_scenario", id=2, name="../../etc/passwd"))["ok"]
        a = await cmd(ws, cmd="set_tier", id=3, tier="native")
        assert not a["ok"] and "not available" in a["reason"]
        a = await cmd(ws, cmd="load_scenario", id=4, scenario={"name": "bad"})
        assert not a["ok"]
    run(session(make_service(), go))


def test_invalid_json_does_not_kill_connection():
    async def go(client, ws, hello):
        await ws.send_str("{not json")
        a = await recv_until(ws, lambda k, d: k == "json" and d.get("type") == "ack")
        assert not a["ok"]
        assert (await cmd(ws, cmd="pause", id=9))["ok"]
    run(session(make_service(), go))


def test_tracers_respawn_upstream_and_stay_in_bounds():
    from engine.scenario.schema import Inflow, Layout
    from engine.wind.factory import make_wind
    lay = load_scenario(ROOT / "scenarios/block_small.json").layout
    w = make_wind("synthetic", lay, Inflow(8, 0, 0.5))
    tr = Tracers(2000, lay.bounds_m, seed=1)
    for _ in range(600):
        w.step(1); tr.step(w, 0.05)
    assert (tr.pos[:, 0] >= -1).all() and (tr.pos[:, 0] <= 401).all() and (tr.pos[:, 2] >= 0).all()
    tr.set_direction(90.0)
    fresh = tr._upstream_points(500)
    assert fresh[:, 1].max() < 5            # blowing north: respawn at the south edge
    tr.set_direction(0.0)
    assert tr._upstream_points(500)[:, 0].max() < 5


def test_deterministic_tracers():
    from engine.scenario.schema import Inflow
    from engine.wind.factory import make_wind
    lay = load_scenario(ROOT / "scenarios/block_small.json").layout
    out = []
    for _ in range(2):
        w = make_wind("synthetic", lay, Inflow(8, 0, 0.5)); tr = Tracers(300, lay.bounds_m, seed=4)
        for _ in range(50):
            w.step(1); tr.step(w, 0.05)
        out.append(tr.pos.copy())
    np.testing.assert_array_equal(out[0], out[1])
