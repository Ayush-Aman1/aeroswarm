"""Binary snapshot codec shared by service, replay files and tests. Spec: docs/protocol.md."""
from __future__ import annotations

import struct
from dataclasses import dataclass

import numpy as np

MAGIC = b"AERO"
VERSION = 1
HEADER = struct.Struct("<4sHHIIIIHHff")   # 36 bytes
assert HEADER.size == 36


@dataclass
class Snapshot:
    step: int
    sim_time: float
    layout_version: int
    drone_pos: np.ndarray       # [n,3] float32
    drone_vel: np.ndarray       # [n,3] float32
    drone_state: np.ndarray     # [n] uint8
    tracers: np.ndarray         # [m,3] float32
    slice_speed: np.ndarray     # [nx,ny] float16 (|u| in m/s)
    slice_z: float = 0.0
    flags: int = 0


def _pad4(n: int) -> int:
    return (-n) % 4


def pack_snapshot(s: Snapshot) -> bytes:
    n, m = len(s.drone_pos), len(s.tracers)
    nx, ny = s.slice_speed.shape if s.slice_speed.size else (0, 0)
    parts = [HEADER.pack(MAGIC, VERSION, s.flags, s.step, s.layout_version, n, m, nx, ny,
                         float(s.slice_z), float(s.sim_time))]
    pv = np.concatenate([np.asarray(s.drone_pos, "<f4"), np.asarray(s.drone_vel, "<f4")], axis=1) if n else \
        np.zeros((0, 6), "<f4")
    parts.append(np.ascontiguousarray(pv).tobytes())
    st = np.asarray(s.drone_state, np.uint8).tobytes()
    parts.append(st + b"\0" * _pad4(len(st)))
    parts.append(np.ascontiguousarray(np.asarray(s.tracers, "<f4").reshape(-1, 3)).tobytes())
    sl = np.ascontiguousarray(np.asarray(s.slice_speed, "<f2")).tobytes()
    parts.append(sl + b"\0" * _pad4(len(sl)))
    return b"".join(parts)


def unpack_snapshot(buf: bytes) -> Snapshot:
    if len(buf) < HEADER.size:
        raise ValueError("snapshot too short")
    magic, ver, flags, step, lv, n, m, nx, ny, sz, st_time = HEADER.unpack_from(buf, 0)
    if magic != MAGIC:
        raise ValueError(f"bad magic {magic!r}")
    if ver != VERSION:
        raise ValueError(f"unsupported protocol version {ver}")
    off = HEADER.size
    pv = np.frombuffer(buf, "<f4", n * 6, off).reshape(n, 6).copy()
    off += n * 24
    state = np.frombuffer(buf, np.uint8, n, off).copy()
    off += n + _pad4(n)
    tr = np.frombuffer(buf, "<f4", m * 3, off).reshape(m, 3).copy()
    off += m * 12
    sl = np.frombuffer(buf, "<f2", nx * ny, off).reshape(nx, ny).copy()
    off += nx * ny * 2 + _pad4(nx * ny * 2)
    if off != len(buf):
        raise ValueError(f"trailing/missing bytes: parsed {off}, got {len(buf)}")
    return Snapshot(step, st_time, lv, pv[:, :3], pv[:, 3:], state, tr, sl, sz, flags)


# Replay files are a plain concatenation of [u32 length][snapshot bytes].
def write_replay_frame(fh, s: Snapshot) -> int:
    b = pack_snapshot(s)
    fh.write(struct.pack("<I", len(b)) + b)
    return len(b)


def read_replay(path) -> list[Snapshot]:
    out = []
    with open(path, "rb") as fh:
        while True:
            head = fh.read(4)
            if not head:
                break
            (ln,) = struct.unpack("<I", head)
            out.append(unpack_snapshot(fh.read(ln)))
    return out
