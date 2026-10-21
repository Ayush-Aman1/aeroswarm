#!/usr/bin/env python3
"""Regenerate viewer/tests/fixtures/snapshot.{bin,json}: a snapshot packed by engine/protocol.py plus the
values the JS decoder (viewer/src/protocol.js) must reproduce. Keeps the two codecs honest."""
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from engine.protocol import Snapshot, pack_snapshot  # noqa: E402

out = Path(__file__).resolve().parents[1] / "viewer/tests/fixtures"
r = np.random.default_rng(7)
n, m, nx, ny = 5, 7, 6, 3
s = Snapshot(step=1234, sim_time=61.7, layout_version=2,
             drone_pos=r.uniform(0, 300, (n, 3)).astype("f4"), drone_vel=r.uniform(-8, 8, (n, 3)).astype("f4"),
             drone_state=np.array([0, 1, 2, 3, 4 | 8], "u1"), tracers=r.uniform(0, 300, (m, 3)).astype("f4"),
             slice_speed=r.uniform(0, 14, (nx, ny)).astype("f2"), slice_z=30.0, flags=1)
(out / "snapshot.bin").write_bytes(pack_snapshot(s))
exp = dict(step=1234, layoutVersion=2, nDrones=n, nTracers=m, sliceNx=nx, sliceNy=ny, sliceZ=30.0, paused=True,
           simTime=float(np.float32(61.7)),
           dronePV=np.concatenate([s.drone_pos, s.drone_vel], 1).ravel().tolist(), droneState=s.drone_state.tolist(),
           tracers=s.tracers.ravel().tolist(), slice=s.slice_speed.astype("f4").T.ravel().tolist())
(out / "snapshot.json").write_text(json.dumps(exp))
print("wrote fixtures")
