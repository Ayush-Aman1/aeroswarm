# AeroSwarm service ⇄ viewer protocol (version 1)

Shared by `service/server.py`, `viewer/`, replay files and `engine/protocol.py`.

## Coordinates and units
SI units. **x = east, y = north, z = up**, origin at the south-west corner of the area. The viewer
maps sim `(x, y, z)` to three.js `(x, z, -y)`. Buildings are axis-aligned boxes with min corner `(x, y)`,
footprint `w` (along x) × `d` (along y) and height `h`. `direction_deg` is the direction the wind blows
**toward**, counter-clockwise from +x (0 = blowing east).

## Binary snapshot (server → client, WebSocket binary frame, 20 Hz)
All little-endian. Header 36 bytes (`struct "<4sHHIIIIHHff"`):

| off | type | field |
|----:|------|-------|
| 0 | char[4] | magic `AERO` |
| 4 | u16 | version (1) |
| 6 | u16 | flags (bit0: paused) |
| 8 | u32 | step |
| 12 | u32 | layout_version |
| 16 | u32 | n_drones |
| 20 | u32 | n_tracers |
| 24 | u16 | slice_nx |
| 26 | u16 | slice_ny |
| 28 | f32 | slice_z (metres) |
| 32 | f32 | sim_time (seconds) |

Body, each block 4-byte aligned (so JS typed-array views never need copies):

1. `float32[n_drones][6]` — position xyz, velocity xyz
2. `uint8[n_drones]`, zero-padded to a multiple of 4 — drone state (below)
3. `float32[n_tracers][3]` — tracer positions
4. `float16[slice_nx * slice_ny]` row-major with **x fastest** (index `j*nx + i`), padded to a
   multiple of 4 bytes — wind speed `|u|` in m/s on the slice plane (cell `(i,j)` centre at
   `((i+.5)·dx, (j+.5)·dx)`), downsampled so the whole frame stays < 1 MB.

Drone state byte: low 3 bits = `0 idle · 1 outbound · 2 delivering · 3 returning · 4 done`;
bit 3 (`8`) = near-collision flash this step.

Replay files (`runs/<ts>/replay.bin`) are `[u32 length][snapshot]` repeated, snapshots every 0.5 s,
`n_tracers = 0` and an empty slice.

## JSON messages, client → server
Every command may carry `"id": <int>`; the reply echoes it.

| `cmd` | fields | effect |
|-------|--------|--------|
| `load_scenario` | `name` (file in `scenarios/`) **or** `scenario` (inline object) | reset everything |
| `set_inflow` | `speed_ms?`, `direction_deg?` | relayout with new inflow (wind re-settles) |
| `edit_building` | `building: {id, x, y, w, d, h}` | validate, then relayout |
| `set_routing` | `mode: "naive" \| "aware"` | switch the planner weights, replan |
| `set_tier` | `tier: "synthetic" \| "fluidx3d" \| "lbmpy"` | swap wind adapter (if available) |
| `set_slice_z` | `z` | height of the streamed wind slice |
| `pause` / `resume` | – | freeze / unfreeze stepping |

## JSON messages, server → client
| `type` | fields |
|--------|--------|
| `hello` | `protocol`, `scenario` (name), `layout` (`area_m, ceiling_m, buildings, version`), `depots`, `targets`, `inflow`, `tier`, `routing`, `tiers_available`, `slice_z` |
| `ack` | `id`, `cmd`, `ok`, `reason?` — a rejected `edit_building` leaves the layout unchanged |
| `settling` | `pending: bool` — a relayout is in progress (UI shows "settling wind…") |
| `layout` | full layout object whenever `layout_version` changes (commit of an edit) |
| `stats` | ~2 Hz: `tier, routing, step, sim_time, fps_server, snapshot_bytes, wind {mlups, step_ms}, metrics {delivered, mean_delivery_s, energy, drift_mean, near_collisions, active}` |
| `toast` | `level`, `text` |

## Size budget
`snapshot_bytes` is logged in `stats`. Budget 1 MB: 1 000 drones = 24 kB + 1 kB, 8 000 tracers = 96 kB,
a 100×75 float16 slice = 15 kB. If a slice would push the frame over the budget the server halves it.
