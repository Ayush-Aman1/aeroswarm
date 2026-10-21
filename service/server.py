"""AeroSwarm live service: steps the engine, streams binary snapshots at 20 Hz over /ws, serves viewer/dist.

    python -m service.server --scenario scenarios/block_small.json --wind synthetic [--port 8080]
Protocol: docs/protocol.md.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import time
from dataclasses import replace
from pathlib import Path

import numpy as np
from aiohttp import WSMsgType, web

from engine import backend
from engine.backend import to_numpy
from engine.protocol import Snapshot, pack_snapshot
from engine.scenario.runner import Simulation
from engine.scenario.schema import (Building, Inflow, SchemaError, Scenario, inflow_from_dict, load_scenario,
                                    scenario_from_dict)
from service.edit import validate_edit
from service.tracers import Tracers

log = logging.getLogger("aeroswarm.service")
ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT_BUDGET = 1_000_000
FLAG_PAUSED = 1


def available_tiers(field_dir: Path | None = None) -> list[str]:
    from engine.wind.factory import available_tiers as _a
    return _a(field_dir)


class Service:
    def __init__(self, scenario: Scenario, wind_name: str = "synthetic", n_tracers: int = 8000,
                 tick_hz: float = 20.0, scenarios_dir: Path | None = None, slice_z: float = 30.0,
                 wind_cfg: dict | None = None, seed: int | None = None):
        self.scenarios_dir = scenarios_dir or ROOT / "scenarios"
        self.tick_hz = tick_hz
        self.n_tracers = n_tracers
        self.slice_z = slice_z
        self.wind_cfg = wind_cfg or {}
        self.paused = False
        self.clients: set[web.WebSocketResponse] = set()
        self._busy: set[web.WebSocketResponse] = set()
        self._task: asyncio.Task | None = None
        self._fps = 0.0
        self._last_snapshot_bytes = 0
        self._next_stats = 0.0
        self.tier = wind_name
        self._load(scenario, wind_name, seed)

    # ---------------------------------------------------------------- engine lifecycle
    def _load(self, scenario: Scenario, wind_name: str, seed: int | None = None) -> None:
        old = getattr(self, "sim", None)
        if old is not None:
            old.close()
        self.scenario = scenario
        self.sim = Simulation(scenario, wind_name=wind_name, seed=seed, continuous=True, async_planner=True,
                              wind_cfg=self.wind_cfg)
        self.tier = wind_name
        self.tracers = Tracers(self.n_tracers, self.sim.layout.bounds_m, seed=scenario.seed)
        self.tracers.set_direction(self.sim.inflow.direction_deg)

    def hello(self) -> dict:
        sc, sim = self.scenario, self.sim
        return {"type": "hello", "protocol": 1, "scenario": sc.name, "layout": {**sim.layout.to_dict(),
                "version": sim.layout_version}, "depots": [{"id": d.id, "x": d.x, "y": d.y} for d in sc.depots],
                "targets": [{"id": m.id, "x": m.target[0], "y": m.target[1]} for m in sc.missions],
                "inflow": sim.inflow.to_dict(), "tier": self.tier, "routing": sim.routing,
                "tiers_available": available_tiers(), "slice_z": self.slice_z,
                "scenarios": sorted(p.stem for p in self.scenarios_dir.glob("*.json")),
                "paused": self.paused}

    # ---------------------------------------------------------------- stepping
    def tick(self) -> bytes:
        """One simulation step (unless paused) and the binary snapshot for it."""
        t0 = time.perf_counter()
        if not self.paused:
            self.sim.step()
            self.tracers.step(self.sim.wind, self.sim.dt)
        snap = self._snapshot()
        data = pack_snapshot(snap)
        self._last_snapshot_bytes = len(data)
        self._step_ms = (time.perf_counter() - t0) * 1e3
        return data

    def _snapshot(self) -> Snapshot:
        sim = self.sim
        sl = np.linalg.norm(to_numpy(sim.wind.slice_z(self.slice_z)), axis=2).astype(np.float16)
        tr = self.tracers.pos
        est = 24 * sim.n + 12 * len(tr) + sl.size * 2
        while est > SNAPSHOT_BUDGET - 4096 and min(sl.shape) > 8:        # keep each frame under 1 MB
            sl = sl[::2, ::2]
            est = 24 * sim.n + 12 * len(tr) + sl.size * 2
        return sim.snapshot(tracers=tr, slice_speed=np.ascontiguousarray(sl), slice_z=self.slice_z,
                            flags=FLAG_PAUSED if self.paused else 0)

    def stats_message(self) -> dict:
        sim = self.sim
        return {"type": "stats", "tier": self.tier, "routing": sim.routing, "step": sim.step_count,
                "sim_time": round(sim.t, 2), "fps_server": round(self._fps, 1),
                "snapshot_bytes": self._last_snapshot_bytes, "settling": sim.settling,
                "step_ms": round(getattr(self, "_step_ms", 0.0), 2), "wind": sim.wind.stats(),
                "metrics": sim.live_metrics(), "paused": self.paused, "layout_version": sim.layout_version,
                "inflow": sim.inflow.to_dict()}

    async def run(self) -> None:
        period = 1.0 / self.tick_hz
        nxt = time.perf_counter()
        last = nxt
        while True:
            data = self.tick()
            now = time.perf_counter()
            self._fps = 0.9 * self._fps + 0.1 * (1.0 / max(now - last, 1e-6)) if self._fps else self.tick_hz
            last = now
            await self._broadcast_events()
            if self.clients:
                for ws in list(self.clients):
                    if ws in self._busy:
                        continue                              # slow client: drop this frame
                    self._busy.add(ws)
                    asyncio.create_task(self._send(ws, data))
                if now >= self._next_stats:
                    self._next_stats = now + 0.5
                    await self._broadcast_json(self.stats_message())
            nxt += period
            await asyncio.sleep(max(0.0, nxt - time.perf_counter()))
            if time.perf_counter() - nxt > 1.0:
                nxt = time.perf_counter()                     # fell behind: don't burst-catch-up

    async def _send(self, ws, data: bytes) -> None:
        try:
            await ws.send_bytes(data)
        except Exception:  # noqa: BLE001
            self.clients.discard(ws)
        finally:
            self._busy.discard(ws)

    async def _broadcast_json(self, msg: dict) -> None:
        text = json.dumps(msg)
        for ws in list(self.clients):
            try:
                await ws.send_str(text)
            except Exception:  # noqa: BLE001
                self.clients.discard(ws)

    async def _broadcast_events(self) -> None:
        ev, self.sim.events = self.sim.events, []
        for e in ev:
            if e["type"] == "layout_commit":
                lay = {**self.sim.layout.to_dict(), "version": self.sim.layout_version}
                self.tracers.set_direction(self.sim.inflow.direction_deg)
                await self._broadcast_json({"type": "layout", **lay, "inflow": self.sim.inflow.to_dict()})
            elif e["type"] == "settling":
                await self._broadcast_json(e)

    # ---------------------------------------------------------------- commands
    def handle(self, msg: dict) -> dict:
        """Execute one client command; returns the ack dict."""
        cmd = msg.get("cmd")
        ack = {"type": "ack", "id": msg.get("id"), "cmd": cmd, "ok": True}
        try:
            fn = getattr(self, f"_cmd_{cmd}", None)
            if fn is None:
                return {**ack, "ok": False, "reason": f"unknown command {cmd!r}"}
            reason = fn(msg)
            if reason:
                return {**ack, "ok": False, "reason": reason}
        except (SchemaError, KeyError, TypeError, ValueError) as exc:
            return {**ack, "ok": False, "reason": f"bad {cmd}: {exc}"}
        return ack

    def _cmd_pause(self, m):
        self.paused = True

    def _cmd_resume(self, m):
        self.paused = False

    def _cmd_set_slice_z(self, m):
        z = float(m["z"])
        if not 0 <= z <= self.sim.layout.ceiling_m:
            return "z out of range"
        self.slice_z = z

    def _cmd_set_routing(self, m):
        if m.get("mode") not in ("naive", "aware"):
            return "mode must be naive|aware"
        self.sim.set_routing(m["mode"])

    def _cmd_set_inflow(self, m):
        cur = self.sim.inflow
        new = inflow_from_dict({"speed_ms": m.get("speed_ms", cur.speed_ms),
                                "direction_deg": m.get("direction_deg", cur.direction_deg) % 360.0,
                                "roughness": cur.roughness})
        if self.sim.settling:
            return "wind is still settling from the previous edit"
        self.sim.begin_layout_change(self.sim.layout, new)

    def _cmd_edit_building(self, m):
        b = m["building"]
        new = Building(int(b["id"]), float(b["x"]), float(b["y"]), float(b["w"]), float(b["d"]), float(b["h"]))
        ok, reason, new_layout = validate_edit(self.sim, new)
        if not ok:
            return reason
        self.sim.begin_layout_change(new_layout, self.sim.inflow)

    def _cmd_set_tier(self, m):
        tier = m.get("tier")
        if tier not in available_tiers():
            return f"tier {tier!r} is not available on this machine (available: {available_tiers()})"
        if self.sim.settling:
            return "wind is still settling"
        try:
            self._load(replace(self.scenario, layout=self.sim.layout, inflow=self.sim.inflow), tier,
                       seed=self.sim.seed)
        except Exception as exc:  # noqa: BLE001 - report to the client, keep the old simulation
            log.exception("tier switch failed")
            return f"could not start tier {tier}: {exc}"

    def _cmd_load_scenario(self, m):
        if "scenario" in m:
            sc = scenario_from_dict(m["scenario"])
        else:
            name = Path(str(m["name"])).stem            # no path traversal
            p = self.scenarios_dir / f"{name}.json"
            if not p.exists():
                return f"no such scenario {name!r}"
            sc = load_scenario(p)
        self._load(sc, self.tier)


# ------------------------------------------------------------------------------------------ app
def make_app(service: Service, start_loop: bool = True) -> web.Application:
    app = web.Application()
    dist = ROOT / "viewer" / "dist"

    async def ws_handler(request):
        ws = web.WebSocketResponse(max_msg_size=4 * 1024 * 1024, heartbeat=20)
        await ws.prepare(request)
        service.clients.add(ws)
        await ws.send_str(json.dumps(service.hello()))
        try:
            async for msg in ws:
                if msg.type != WSMsgType.TEXT:
                    continue
                try:
                    data = json.loads(msg.data)
                except json.JSONDecodeError:
                    await ws.send_str(json.dumps({"type": "ack", "ok": False, "reason": "invalid JSON"}))
                    continue
                ack = service.handle(data)
                await ws.send_str(json.dumps(ack))
                if ack["ok"] and data.get("cmd") in ("load_scenario", "set_tier"):
                    await service._broadcast_json(service.hello())
        finally:
            service.clients.discard(ws)
        return ws

    async def index(request):
        f = dist / "index.html"
        if f.exists():
            return web.FileResponse(f)
        return web.Response(text="AeroSwarm service is running, but viewer/dist is missing. Build it with: "
                                 "cd viewer && npm ci && npm run build", content_type="text/plain")

    async def api_scenarios(request):
        return web.json_response(sorted(p.stem for p in service.scenarios_dir.glob("*.json")))

    async def api_state(request):
        return web.json_response({"hello": service.hello(), "stats": service.stats_message(),
                                  "backend": backend.backend_name})

    app.router.add_get("/ws", ws_handler)
    app.router.add_get("/api/scenarios", api_scenarios)
    app.router.add_get("/api/state", api_state)
    app.router.add_get("/", index)
    if (dist / "assets").exists():
        app.router.add_static("/assets", dist / "assets")
    if dist.exists():
        for f in dist.iterdir():
            if f.is_file() and f.name != "index.html":
                app.router.add_get(f"/{f.name}", lambda r, f=f: web.FileResponse(f))

    async def on_start(app):
        if start_loop:
            service._task = asyncio.create_task(service.run())

    async def on_stop(app):
        if service._task:
            service._task.cancel()
        service.sim.close()

    app.on_startup.append(on_start)
    app.on_cleanup.append(on_stop)
    return app


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scenario", default=str(ROOT / "scenarios/block_small.json"))
    ap.add_argument("--wind", default="synthetic", help="synthetic | fluidx3d | lbmpy")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--tracers", type=int, default=8000)
    ap.add_argument("--hz", type=float, default=20.0)
    ap.add_argument("--wind-cfg", default=None, help="JSON dict of adapter options")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    t0 = time.perf_counter()
    sc = load_scenario(a.scenario)
    svc = Service(sc, a.wind, a.tracers, a.hz, wind_cfg=json.loads(a.wind_cfg) if a.wind_cfg else None)
    log.info("engine ready in %.1f s (backend %s, tier %s)", time.perf_counter() - t0, backend.backend_name, a.wind)
    print(f"AeroSwarm service: http://{a.host}:{a.port}  (ws://{a.host}:{a.port}/ws)", flush=True)
    web.run_app(make_app(svc), host=a.host, port=a.port, print=None)


if __name__ == "__main__":
    main()
