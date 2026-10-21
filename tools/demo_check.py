#!/usr/bin/env python3
"""Scripted check of the demo flow against a running service (headless: protocol level, no browser).

    python -m service.server --scenario scenarios/block_small.json --wind synthetic &
    python tools/demo_check.py [--url ws://127.0.0.1:8080/ws]
Prints PASS/FAIL per item. Visual items (50+ FPS, XR) stay manual - see TESTING_CHECKLIST_WINDOWS.md.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

import aiohttp

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from engine.protocol import unpack_snapshot  # noqa: E402

results: list[tuple[bool, str]] = []


def check(ok: bool, msg: str) -> bool:
    results.append((ok, msg))
    print(("PASS: " if ok else "FAIL: ") + msg, flush=True)
    return ok


async def main(url: str, wait_s: float) -> int:
    t0 = time.time()
    async with aiohttp.ClientSession() as s:
        async with s.ws_connect(url, max_msg_size=8 * 1024 * 1024) as ws:
            hello = json.loads((await ws.receive(timeout=30)).data)
            check(hello["type"] == "hello", f"connected, tier {hello['tier']}, scenario {hello['scenario']} "
                                            f"({time.time() - t0:.1f} s)")
            nid = [0]
            frames: list = []

            async def pump(until, timeout=15.0):
                end = time.time() + timeout
                while time.time() < end:
                    try:
                        msg = await ws.receive(timeout=max(0.05, end - time.time()))
                    except asyncio.TimeoutError:
                        break
                    if msg.type == aiohttp.WSMsgType.BINARY:
                        frames.append(unpack_snapshot(msg.data))
                        frames[-1].raw_len = len(msg.data)
                    elif msg.type == aiohttp.WSMsgType.TEXT:
                        d = json.loads(msg.data)
                        if until(d):
                            return d
                return None

            async def cmd(**kw):
                nid[0] += 1
                await ws.send_str(json.dumps({"id": nid[0], **kw}))
                return await pump(lambda d: d.get("type") == "ack" and d.get("id") == nid[0])

            # snapshots flow, size budget, 1000-drone-class payload fits
            await pump(lambda d: False, timeout=2.0)
            check(len(frames) >= 10, f"{len(frames)} snapshots in 2 s (target 20 Hz)")
            check(max(f.raw_len for f in frames) < 1_000_000, f"snapshot size {max(f.raw_len for f in frames) / 1024:.0f} kB < 1 MB")
            f = frames[-1]
            check(f.tracers.shape[0] > 0 and f.slice_speed.size > 0 and f.drone_pos.shape[0] > 0,
                  f"snapshot carries {f.drone_pos.shape[0]} drones, {f.tracers.shape[0]} tracers, slice {f.slice_speed.shape}")
            await pump(lambda d: False, timeout=wait_s)
            st = None

            # routing toggle -> live metrics keep flowing
            a = await cmd(cmd="set_routing", mode="aware")
            check(bool(a and a["ok"]), "toggle to wind-aware routing")
            a = await cmd(cmd="set_routing", mode="naive")
            check(bool(a and a["ok"]), "toggle back to naive routing")

            # move a building: accepted, wind re-settles, layout version bumps, no drone ends up inside
            b = hello["layout"]["buildings"][3]
            a = await cmd(cmd="edit_building", building=dict(id=b["id"], x=b["x"] + 10, y=b["y"], w=b["w"], d=b["d"], h=b["h"]))
            check(bool(a and a["ok"]), f"move building {b['id']} by +10 m: accepted ({a and a.get('reason', '')})")
            lay = await pump(lambda d: d.get("type") == "layout", timeout=60)
            check(lay is not None and lay["version"] == hello["layout"]["version"] + 1, "wind settled, layout version bumped")
            if lay:
                nb = [x for x in lay["buildings"] if x["id"] == b["id"]][0]
                last = frames[-1]
                inside = [(i, p) for i, p in enumerate(last.drone_pos)
                          if nb["x"] <= p[0] <= nb["x"] + nb["w"] and nb["y"] <= p[1] <= nb["y"] + nb["d"] and p[2] <= nb["h"]]
                await pump(lambda d: False, timeout=3.0)
                last = frames[-1]
                inside = [i for i, p in enumerate(last.drone_pos)
                          if nb["x"] <= p[0] <= nb["x"] + nb["w"] and nb["y"] <= p[1] <= nb["y"] + nb["d"] and p[2] <= nb["h"]]
                check(not inside, "no drone inside the moved building")

            # drop a building on a depot: rejected with a reason, nothing changes
            dep = hello["depots"][0]
            a = await cmd(cmd="edit_building", building=dict(id=b["id"], x=dep["x"] - 10, y=dep["y"] - 10, w=30, d=30, h=30))
            check(bool(a and not a["ok"] and a.get("reason")), f"building dropped on a depot: rejected ({a and a.get('reason')})")

            # rotate the inflow 45 degrees: accepted, layout message carries the new inflow
            cur = (lay or hello)["inflow"]["direction_deg"] if (lay or hello).get("inflow") else 0.0
            a = await cmd(cmd="set_inflow", direction_deg=(cur + 45) % 360)
            check(bool(a and a["ok"]), f"rotate inflow {cur:.0f} -> {(cur + 45) % 360:.0f} deg: accepted ({a and a.get('reason', '')})")
            lay2 = await pump(lambda d: d.get("type") == "layout", timeout=60)
            check(lay2 is not None and abs(lay2["inflow"]["direction_deg"] - (cur + 45) % 360) < 1e-6, "wind re-settled with the new direction")

            # live metrics present
            stats = await pump(lambda d: d.get("type") == "stats", timeout=5)
            check(stats is not None and "metrics" in stats and stats["metrics"]["active"] >= 0,
                  f"live metrics: {stats and stats['metrics']}")
    bad = [m for ok, m in results if not ok]
    print(f"\n{len(results) - len(bad)}/{len(results)} checks passed")
    return 1 if bad else 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="ws://127.0.0.1:8080/ws")
    ap.add_argument("--wait", type=float, default=5.0, help="seconds to let the swarm fly before editing")
    a = ap.parse_args()
    sys.exit(asyncio.run(main(a.url, a.wait)))
