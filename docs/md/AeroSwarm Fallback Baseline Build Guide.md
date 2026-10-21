# AeroSwarm Fallback Baseline: Build Guide

Oct 18, 2026 · @Ayush Aman

## Purpose and strategy

The fallback is a complete, demo-ready AeroSwarm built mostly from existing open-source parts, sitting behind the same interface as your own engine. If your own kernels are ready by January, you swap them in; if not, the fallback runs the demo.

Only the wind solver is genuinely risky, so it gets three tiers. Everything else (drones, swarm grid, wind-aware A\*, service, viewer, XR) is built once and shared by all tiers.

| Tier | Wind source | Live building edits | Still GPU LBM? | Risk |
|----|----|----|----|----|
| 1 | lbmpy-generated CUDA kernels (D3Q19, Smagorinsky, bounce-back), run from Python | Yes | Yes | Medium |
| 2 | FluidX3D, run offline per layout and wind direction, fields saved to disk | Pick from a precomputed menu | Yes (offline) | Low |
| 3 | Synthetic wind: uniform flow plus analytic building wakes and corner speed-up | Yes, instant | No | Near zero |

Tier 3 is built first because it unblocks all the drone and viewer work, exactly as your October plan already says. Tier 2 comes next because it is the most reliable "real CFD" result. Tier 1 is the stretch goal of the fallback.

The rule that makes swapping painless: no module except the wind adapter knows which tier is running. Your own CUDA engine later becomes a fourth adapter behind the same interface.

## Architecture

A Python-hosted engine with four interchangeable wind adapters, a WebSocket service and a browser viewer. Swapping tiers means changing one config value.

<img src="media/image1.png" style="width:6in;height:4.98214in" alt="fallback architecture · 4 wind adapters behind one interface" />

fallback architecture · 4 wind adapters behind one interface

Drones and the planner only ever call the interface; the service and viewer never see wind internals. Your Phase 1 design hosts the engine in C++; here Python hosts it, and your native engine joins later as the native.py adapter through its C ABI.

### Interface contract

class WindSource(Protocol):\
name: str\
bounds_m: tuple\[float, float, float\] \# x, y, z extent in metres\
dx_m: float \# grid spacing\
def reset(self, layout: Layout, inflow: Inflow) -\> None: ...\
def step(self, n: int = 1) -\> None: ...\
def sample(self, pos): \# pos \[N,3\] metres -\> vel \[N,3\] m/s, trilinear\
...\
def slice_z(self, z_m: float): \# -\> \[nx, ny, 3\] at that height\
...\
def begin_relayout(self, layout, inflow) -\> None: ...\
def relayout_ready(self) -\> bool: ...\
def commit_relayout(self) -\> None: ... \# called at a step boundary\
def stats(self) -\> dict: ... \# {'mlups': ..., 'step_ms': ...}

### Folder layout

aeroswarm/\
AGENTS.md master prompt for the coding agent\
CREDITS.md\
engine/\
backend.py xp = cupy or numpy\
wind/ base.py, factory.py, synthetic.py,\
fluidx3d_field.py, lbmpy_solver.py, native.py\
swarm/ drones.py, grid.py\
planner/ astar.py\
scenario/ schema.py, runner.py, compare.py\
metrics/\
service/server.py\
viewer/ Vite + three.js\
tools/fluidx3d/ setup.cpp template, batch.py\
scenarios/ \*.json\
runs/ outputs (gitignored)\
bench/ experiments/ tests/ docs/\
third_party/ cloned references (gitignored)

## Download checklist

You need two machines: the NVIDIA laptop (RTX 3060) for anything CUDA or OpenCL, and any Mac for the viewer, planner and CPU paths. The code auto-detects the GPU and falls back to NumPy, so Mac development never blocks.

### On the NVIDIA laptop (Windows 11 or Ubuntu 22.04/24.04)

- [ ] Latest NVIDIA Studio or Game Ready driver; confirm with nvidia-smi

- [ ] CUDA Toolkit 12.x; confirm with nvcc --version

- [ ] Miniconda, then a Python 3.11 environment named aeroswarm

- [ ] Windows only: Visual Studio 2022 Community with "Desktop development with C++" (needed to build FluidX3D)

- [ ] Ubuntu only: build-essential and ocl-icd-opencl-dev (FluidX3D's OpenCL headers)

- [ ] Git and Git LFS

### On every machine

- [ ] Python 3.11 environment with: numpy scipy aiohttp pytest matplotlib meshio pyvista

- [ ] GPU machine only: cupy-cuda12x and lbmpy\[gpu\] (pulls in pystencils); test with python -c "import cupy; cupy.show_config()"

- [ ] Optional, for the Bengaluru extension: osmnx geopandas shapely

- [ ] Node.js 20 LTS (for the Vite + three.js viewer)

- [ ] Chrome, plus the Meta Immersive Web Emulator extension from the Chrome Web Store (Brave usually works too; use Chrome if the WebXR tab doesn't appear)

- [ ] A coding agent: Claude Code, Cursor or OpenCode all work with the prompts in this doc

### Repos to clone into third_party/ (read-only references)

- [ ] ProjectPhysX/FluidX3D: Tier 2 wind solver, built and run on the NVIDIA laptop

- [ ] pmocz/latticeboltzmann-python: 2D cylinder validation baseline

- [ ] akdemironur/cuda_d2q9_flow_over_cylinder: 2D CUDA reference for parity checks

- [ ] arch85-km/urban-wind-lab: reference for tracer, slice and colour-map visuals (MIT)

- [ ] NVIDIA/cuda-samples: the particles sample for the uniform-grid neighbour search

- [ ] LinDadaism/GPU-CUDA-Flocking (or any CIS 565 Project 1 fork): boids neighbour-search reference

- [ ] mapbox/webgl-wind (optional): particle-trail shader reference

No trained models or datasets are needed. After installing, freeze exact versions with pip freeze \> requirements.lock and commit package-lock.json, so the agent never drifts onto a different lbmpy or three.js API.

## Pick list

Take ideas and small adapted snippets, never whole files, except FluidX3D, which runs as an external tool you only configure. That keeps licences clean and keeps your code consistent with one interface.

| Source | Take | Ignore | Feeds module |
|----|----|----|----|
| FluidX3D | src/setup.cpp pattern, defines.hpp switches (D3Q19, SUBGRID, EQUILIBRIUM_BOUNDARIES), lbm.u.write_device_to_vtk() export, units helper | Its renderer, multi-GPU, free-surface and thermal extensions | Tier 2 wind |
| lbmpy | LBMConfig with D3Q19 + Smagorinsky, CreateKernelConfig(target=Target.GPU), NoSlip / UBB boundaries, its MLUPS benchmark helper | waLBerla code generation, cumulant and multiphase methods | Tier 1 wind |
| pmocz/latticeboltzmann-python | Whole D2Q9 loop as the 2D CPU baseline, cylinder mask, vorticity plot | Its plotting style | Validation |
| akdemironur/cuda_d2q9 | Kernel layout and launch config for comparing your 2D CPU vs CUDA | Coursera-specific I/O | Validation |
| NVIDIA cuda-samples particles | calcHash → sort → findCellStart sequence, 27-cell neighbour loop | OpenGL interop, collision physics | Swarm grid |
| CIS 565 flocking | Scattered vs coherent grid comparison, timing method with CUDA events | Cohesion and alignment rules | Swarm grid, benchmarks |
| urban-wind-lab | Colour maps, slice-plane approach, GPU streamline tracer idea, inflow log-profile | Its Web Worker solver | Viewer |
| three.js examples | webgl_gpgpu_birds and InstancedMesh patterns, TransformControls, webxr_xr_dragging controller grab | Everything else | Viewer, editor, XR |
| mapbox/webgl-wind | Fading particle-trail shader | Global map projection | Viewer (optional) |
| RP-A\* paper (Shenzhen Univ., ISPRS 2026) | Direction-dependent wind-risk cost: gust, crosswind and limit-exceedance terms | Their RANS pipeline | Planner |

Two things are written fresh by the agent because nothing reusable exists: the wind-aware A\* on a coarse 3D grid, and the synthetic Tier 3 wind field.

## Build order and gates

The fallback reaches a full desktop demo by Dec 20, matching your December minimum-viable gate, with January kept for experiments and the report. Dates are proposals; shift them freely.

<img src="media/image2.png" style="width:6in;height:4.00893in" alt="proposed build schedule, Oct 2026 to Jan 2027, 3 gates" />

proposed build schedule, Oct 2026 to Jan 2027, 3 gates

Gate criteria: vortex shedding means the P2 Strouhal test passes. Full desktop demo means every demo-flow box in the checklist is ticked on at least Tier 3 and Tier 2. At the Jan 10 swap decision, your own kernels replace the fallback only if they pass the same P2 tests and match Tier 1 within tolerance.

## Running the coding agent

Save the master prompt below as AGENTS.md (or CLAUDE.md for Claude Code) in the repo root, then paste one module prompt per session. The agent re-reads the master file every session, so you never repeat context.

How to drive it with minimal input:

1.  Create an empty repo, add AGENTS.md, the Phase 1 explainer PDF as docs/explainer.pdf, and clone the references into third_party/.

2.  Start a session, paste the next module prompt, and let it run until it reports its acceptance tests.

3.  Check only three things: tests pass, the demo command in its report works, git diff touches only the module's folders. Then commit.

4.  If it fails twice on the same thing, paste the matching row from Troubleshooting.

GPU modules (Tier 1, Tier 2, CuPy swarm path) must run on the NVIDIA laptop. Everything else can be built on the Mac with the NumPy path.

### Master context prompt (AGENTS.md)

You are building the FALLBACK BASELINE of AeroSwarm, a wind-aware drone swarm\
simulator (see docs/explainer.pdf). Goal: a working demo by January even if the\
team's own CUDA kernels are not finished. Reuse open-source parts; credit them.\
\
ARCHITECTURE (do not change without asking):\
\- Python 3.11 package \`engine/\` hosts the simulation. Array code uses \`xp\`\
(cupy if a CUDA GPU is present, else numpy) from engine/backend.py.\
\- Wind comes ONLY through the WindSource interface in engine/wind/base.py.\
Adapters: synthetic.py (Tier 3), fluidx3d_field.py (Tier 2),\
lbmpy_solver.py (Tier 1), native.py (team's own CUDA engine via ctypes, later).\
No other module may import an adapter directly; use engine/wind/factory.py.\
\- Interface units are SI (metres, seconds, m/s). Lattice units stay inside adapters.\
\- Drones, swarm grid, planner, metrics, scenarios live in engine/swarm,\
engine/planner, engine/metrics, engine/scenario.\
\- service/server.py (aiohttp) steps the engine and streams binary snapshots\
over a WebSocket. viewer/ is Vite + three.js. They share docs/protocol.md.\
\- Scenarios are seeded JSON in scenarios/. Runs write to runs/\<timestamp\>/.\
\
RULES:\
1\. Work only in the folders the current task names. Never refactor others.\
2\. Before using lbmpy, pystencils, cupy, three.js or FluidX3D APIs, read the\
INSTALLED version's source or docs. Do not rely on memory; versions drift.\
3\. Every module ships pytest tests (or a headless check for viewer code) and a\
one-line demo command. Run them before reporting.\
4\. Deterministic: same scenario + seed =\> same metrics (CPU path exactly,\
GPU path within 1e-4 relative).\
5\. Code borrowed or adapted from third_party/ gets a comment with the source\
URL and licence, and a line in CREDITS.md.\
6\. No silent fallbacks: if the GPU path fails, log it loudly and continue on\
numpy only when the config allows it.\
7\. Keep LBM stable: lattice inflow speed \<= 0.08, tau \> 0.51, Smagorinsky on.\
8\. Finish each task with a short report: files changed, tests run and results,\
demo command, known issues. Then stop.

## Module prompts

Paste these one per session, in order. Each assumes the master prompt is in AGENTS.md and the previous modules are committed.

### P0. Scaffold and interfaces

Task P0: create the repo skeleton and the contracts every later module uses.\
\- Folders: engine/{wind,swarm,planner,scenario,metrics}, service/, viewer/,\
tools/fluidx3d/, scenarios/, runs/, tests/, docs/, third_party/ (gitignored).\
\- engine/backend.py: pick xp = cupy if a CUDA device works, else numpy;\
env var AEROSWARM_FORCE_CPU=1 forces numpy. Expose to_numpy().\
\- engine/wind/base.py: WindSource protocol with name, bounds_m, dx_m,\
reset(layout, inflow), step(n), sample(pos\[N,3\]) -\> vel\[N,3\] (trilinear,\
zero inside buildings), slice_z(z_m) -\> \[nx,ny,3\], begin_relayout(layout,\
inflow) / relayout_ready() / commit_relayout(), stats() -\> dict\
(mlups, step_ms). Plus engine/wind/factory.py selecting by config name.\
\- engine/scenario/schema.py: dataclasses + JSON load/validate for Layout\
(axis-aligned box buildings: id,x,y,w,d,h in metres), Inflow (speed_ms,\
direction_deg, roughness), Depots, Missions, seed, sim settings.\
\- scenarios/block_small.json: 400 x 300 m area, 6 buildings 20-60 m tall,\
2 depots, 50 missions, seed 1.\
\- docs/protocol.md: binary snapshot format (little-endian header: magic\
'AERO', version, step, layout_version, n_drones, n_tracers, slice nx, ny,\
slice z; then float32 drone pos+vel, float32 tracer pos, float16 slice\
speeds) and JSON command messages (load_scenario, set_inflow,\
edit_building, set_routing, set_tier, pause, resume).\
\- CREDITS.md stub, requirements.txt, pytest config.\
Tests: schema round-trip, backend selection, protocol pack/unpack.

### P1. Tier 3 synthetic wind

Task P1: engine/wind/synthetic.py implementing WindSource with no CFD.\
Build a 3D field on a 2 m grid covering the scenario bounds, up to 120 m:\
\- Log-law inflow profile U(z) = U_ref \* ln(z/z0)/ln(10/z0), direction from\
Inflow.\
\- Per building, in the rotated wind frame: zero velocity inside; speed-up\
factor ~1.3 in a band beside the lateral faces; upwash over the roof;\
a wake region of length 5\*h downstream with a Gaussian velocity deficit;\
alternating vortices in the wake whose phase advances with time at\
Strouhal 0.2 (f = 0.2 \* U / width), so step() makes the wake gusty.\
\- sample() uses trilinear interpolation (cupyx/scipy map_coordinates,\
order=1). slice_z() returns the grid layer nearest z.\
\- begin_relayout/commit_relayout rebuild the static part; instant.\
Tests: zero inside buildings, inflow recovered far upstream, wake speed\
lower than freestream, field changes over time in wake only.\
Demo: script saving a PNG of slice_z(30) speed with building outlines.

### P2. Validation baselines

Task P2: tests/validation/ using third_party/latticeboltzmann-python as the\
reference (adapt, credit it).\
\- cylinder_2d.py: D2Q9 flow past a cylinder, Re about 100-150; record the\
lift-direction velocity at a probe behind the cylinder, FFT it, report\
Strouhal number. Pass if 0.16 \<= St \<= 0.22. Save a vorticity PNG.\
\- test_collision_conservation.py: random cells, one BGK collision, mass and\
momentum conserved to 1e-6 (float32). Reproduce the 1D worked example from\
docs/explainer.pdf exactly.\
These same tests will later validate Tier 1 and the team's own kernels.

### P3. Drones and swarm grid

Task P3: engine/swarm/ with xp arrays (works on numpy and cupy).\
\- State: pos, vel, target waypoint index, path buffer, energy, flags.\
\- step(dt, wind): PD controller toward waypoint with thrust cap; wind drag\
F = k\*(u_wind - v); separation force from neighbours within r_sep\
(Reynolds 1987 separation rule only); semi-implicit Euler; energy +=\
\|thrust\|\*dt.\
\- grid.py neighbour search exactly as hist -\> exclusive scan -\> scatter:\
cell id per drone, bincount (histogram), cumsum (scan), stable scatter of\
ids; then check own + 26 neighbour cells. On GPU write the neighbour loop\
as a cupy RawKernel modelled on NVIDIA cuda-samples 'particles' (credit).\
Also keep a naive O(N^2) path for correctness tests.\
\- Near-collision counter: pairs closer than d_nc, counted once per pair.\
Tests: grid result == naive result for 2k random drones; drones reach\
waypoints in still air; drift appears under crosswind.\
Bench script: step time vs N = 100, 1k, 10k on CPU and GPU.

### P4. Wind-aware A\* planner

Task P4: engine/planner/astar.py, pure numpy, runs on CPU.\
\- Coarse 3D grid: 10 m horizontal, altitude layers 20/40/60/80 m; cells\
inside buildings plus a 5 m margin are blocked; 26-connectivity.\
\- Edge cost = length \* (1 + a\*max(0, -u.dir)/v_cruise + b\*gust + c\*cross),\
where u is mean wind at the edge, gust is the std of \|u\| over the last K\
wind snapshots for that cell, cross is the crosswind fraction. Cite the\
RP-A\* paper in a comment. a=b=c=0 gives the naive planner.\
\- Wind statistics are refreshed from WindSource every T seconds; replanning\
runs in a worker thread and swaps paths atomically.\
\- reachable(layout, depot, target) for edit validation.\
Tests: naive path is the shortest; with a strong wake on the straight line,\
wind-aware path bends around it; blocked target reports unreachable.

### P5. Scenarios, metrics and replay

Task P5: engine/scenario/runner.py and engine/metrics/.\
\- Missions depot -\> target -\> depot; mission start times drawn from the seed.\
\- Metrics per mission and per run: delivery time, energy proxy, mean and max\
cross-track drift, near-collisions; reductions done with xp sums.\
\- runs/\<ts\>/: config.json, metrics.csv, summary.json, replay.bin (snapshots\
every 0.5 s in the docs/protocol.md format).\
\- compare.py: paired comparison of two run folders (same seeds), printing a\
table and saving bar charts.\
CLI: python -m engine.scenario.runner scenarios/block_small.json\
--wind synthetic --routing naive\|aware --seed 1 --headless --duration 300

### P6. Live service

Task P6: service/server.py with aiohttp.\
\- Serves viewer/dist statically and a WebSocket at /ws.\
\- Fixed-rate asyncio loop: engine steps, tracer advection (8k tracers moved\
by WindSource.sample, RK2, respawn at inflow), snapshot at 20 Hz.\
\- Commands per docs/protocol.md. edit_building: validate (inside bounds, no\
drone inside new box + margin, every depot still reachable via the\
planner); on success begin_relayout, keep running the old wind until\
relayout_ready(), then commit at a step boundary and bump layout_version;\
on failure reply {ok:false, reason}.\
\- Snapshot must stay under 1 MB; downsample the slice if needed.\
Tests: protocol round-trip with a test client; a rejected edit leaves the\
layout unchanged.

### P7. Viewer

Task P7: viewer/ with Vite + three.js (version pinned in package-lock).\
\- Connect to /ws, decode snapshots per docs/protocol.md.\
\- Buildings as boxes; ground plane; OrbitControls.\
\- Drones: two InstancedMesh (detailed near, simple far) for LOD, colour by\
state (flying, delivering, near-collision flash). One draw call per LOD.\
\- Tracers: THREE.Points with a fading trail shader (adapt mapbox/webgl-wind\
idea, credit it); colour by speed.\
\- Wind slice: plane with a DataTexture from the float16 slice, viridis\
colour map, height slider.\
\- HUD: tier, routing mode, step, FPS, metrics so far, toggles for each layer.\
Check: renders 1k drones + 8k tracers at \>= 50 FPS on the NVIDIA laptop.

### P8. Building editor

Task P8: viewer editor mode.\
\- Click a building to select; TransformControls for move (x, y) and scale\
(w, d, h); on release send edit_building.\
\- Show 'settling wind...' while pending, a toast with the reason if\
rejected, and snap the building back.\
\- Buttons: rotate inflow direction by 45 degrees, switch naive/aware routing.

### P9. Tier 2 FluidX3D fields

Task P9 (NVIDIA laptop): precomputed CFD wind via FluidX3D.\
\- tools/fluidx3d/: a setup.cpp main_setup() template that reads a generated\
header (from scenario JSON) with the box buildings, sets TYPE_S cells,\
TYPE_E inflow on the x-min face with the log profile, enables D3Q19,\
SUBGRID, EQUILIBRIUM_BOUNDARIES. Wind direction is handled by rotating the\
city, not the inflow. Settle N steps, then export 16 velocity snapshots\
with lbm.u.write_device_to_vtk() at equal intervals. Read FluidX3D's\
README and LICENSE first; do not modify its core files.\
\- tools/fluidx3d/batch.py: for each layout preset x 8 directions, generate\
the header, build, run, then convert VTK -\> float16 .npy on a 2 m grid\
in SI units (rotated back) using meshio or pyvista. Total under 3 GB.\
\- engine/wind/fluidx3d_field.py: WindSource that loops the 16 frames in\
time (gusts preserved), samples trilinearly, and in relayout picks the\
nearest precomputed preset (editor shows preset choices in Tier 2 mode).\
Test: wake behind the tallest building is visible in slice_z(30).

### P10. Tier 1 lbmpy live solver

Task P10 (NVIDIA laptop): engine/wind/lbmpy_solver.py.\
\- lbmpy with D3Q19, SRT or TRT, Smagorinsky on, Target.GPU (cupy). Read\
the installed lbmpy docs and tests to find the current API for: kernel\
creation, NoSlip boundaries on building cells, UBB inflow, an outflow\
boundary, and macroscopic velocity output.\
\- Grid about 200 x 150 x 60 at 2 m; lattice inflow \<= 0.08; unit\
conversion in one helper.\
\- Relayout: build a second solver with the new geometry, step it in\
chunks between live steps until settled (residual of mean \|u\| below a\
threshold), then swap.\
\- stats(): MLUPS measured over 100 steps.\
Tests: P2 cylinder Strouhal test passes on lbmpy in 2D; CPU vs GPU lbmpy\
agree within 1e-4 after 50 steps on a small grid.

### P11. WebXR drone's-eye view

Task P11: viewer XR mode.\
\- renderer.xr.enabled, VRButton; a camera rig that can ride any drone\
(next/previous drone on controller buttons) with smoothed motion.\
\- Controller grab-and-move of buildings, modelled on the three.js\
webxr_xr_dragging example; on release send edit_building as in P8.\
\- Verify with the Immersive Web Emulator in Chrome devtools; document the\
steps in docs/xr.md.

### P12. Benchmarks and experiments

Task P12: bench/ and experiments/.\
\- Wind: MLUPS for Tier 1 at 64^3, 128^3, 256x128x128; FluidX3D's own\
benchmark mode; compare each to the bandwidth ceiling\
(GPU bandwidth / bytes per cell update).\
\- Swarm: step ms vs N for CPU vs GPU, naive vs grid search.\
\- Experiment: block_small and two more layouts, naive vs aware routing,\
seeds 1-5, each tier available. Output metrics tables and plots to\
experiments/results/ ready for the report.

## Demo and testing checklist

The fallback is "ready" when every box below is ticked on the NVIDIA laptop with Wi-Fi off. Run this list once in early December and again the week before the deadline.

Correctness

- [ ] pytest passes on CPU (AEROSWARM_FORCE_CPU=1) and on GPU

- [ ] 2D cylinder Strouhal number between 0.16 and 0.22, vorticity PNG saved

- [ ] Collision conserves mass and momentum; the explainer's 1D worked example reproduces exactly

- [ ] Grid neighbour search matches the naive search for 2k drones

- [ ] Same scenario and seed give identical metrics twice in a row

Demo flow (rehearse in this order)

- [ ] python -m service.server --scenario scenarios/block_small.json --wind \<best tier\> starts in under 30 s

- [ ] Viewer shows buildings, 1k drones, tracers and the wind slice at 50+ FPS

- [ ] Move a building: wind re-settles, routes bend, no drone ends up inside it

- [ ] Drop a building on a depot: rejected with a reason, nothing changes

- [ ] Rotate the inflow 45 degrees: wakes swing, swarm replans

- [ ] Toggle naive vs wind-aware routing and show the live metric difference

- [ ] Enter XR in the emulator, ride a drone, grab a building

Evidence for the report

- [ ] MLUPS table with percentage of the bandwidth ceiling, per tier and grid size

- [ ] Swarm step time vs N, CPU vs GPU, naive vs grid

- [ ] Naive vs aware results over 5 seeds and 3 layouts: delivery time, energy proxy, drift, near-collisions

- [ ] A recorded screen video of the full demo flow, in case the laptop fails on the day

- [ ] CREDITS.md complete and matching the table below

## Credits and licences

Only FluidX3D and lbmpy carry real constraints: FluidX3D is non-commercial only, and lbmpy is copyleft, so keep it a pip dependency rather than copying its code. Confirm every "check" row by opening the repo's LICENSE file before submission.

| Source | Used for | Licence | How you use it |
|----|----|----|----|
| [FluidX3D](https://github.com/ProjectPhysX/FluidX3D) | Tier 2 wind fields | Custom, free for non-commercial use | External tool; only setup.cpp edited |
| [lbmpy](https://pypi.org/project/lbmpy/) | Tier 1 wind solver | Copyleft (check) | pip dependency, not vendored |
| [latticeboltzmann-python](https://github.com/pmocz/latticeboltzmann-python) | 2D validation | Check | Adapted, with header comment |
| [cuda_d2q9_flow_over_cylinder](https://github.com/akdemironur/cuda_d2q9_flow_over_cylinder) | 2D CUDA reference | Check | Reference only |
| [urban-wind-lab](https://github.com/arch85-km/urban-wind-lab) | Visual design reference | MIT | Ideas and small snippets |
| [NVIDIA cuda-samples](https://github.com/NVIDIA/cuda-samples) | Uniform-grid neighbour search | BSD-style (check) | Kernel adapted, credited |
| [GPU-CUDA-Flocking](https://github.com/LinDadaism/GPU-CUDA-Flocking) | Grid comparison method | Check | Reference only |
| [three.js](https://github.com/mrdoob/three.js) | Viewer, editor, XR | MIT | npm dependency, examples adapted |
| [webgl-wind](https://github.com/mapbox/webgl-wind) | Trail shader idea | Check | Adapted, credited |
| [Immersive Web Emulator](https://github.com/meta-quest/immersive-web-emulator) | XR testing | MIT | Browser extension |
| [RP-A\* paper](https://isprs-archives.copernicus.org/articles/XLIX-B4-2026/453/2026/) | Planner cost design | Open access | Cited in report |

Credit line format for CREDITS.md and code headers: Adapted from \<repo URL\> (\<licence\>), \<what was taken\>. The report should also say which tier produced each result, so nobody mistakes Tier 2 FluidX3D output for your own kernels.

## Troubleshooting

Most failures come from three places: LBM stability, version drift, and the agent wandering outside its task. Paste the "tell the agent" text as-is.

| Symptom | Likely cause | Tell the agent |
|----|----|----|
| Wind turns to NaN or explodes | Lattice speed too high or tau near 0.5 | "Print lattice inflow speed and tau. Keep inflow \<= 0.08 and tau \> 0.51, enable Smagorinsky, ramp inflow up over 500 steps." |
| lbmpy import or API errors | Installed version differs from what the agent remembers | "Stop guessing the API. Open the installed lbmpy and pystencils source and their tests, then rewrite to match." |
| cupy import fails | CUDA version mismatch | "Run cupy.show_config() and nvidia-smi, then install the cupy wheel matching the driver's CUDA version." |
| FluidX3D finds no device | OpenCL runtime missing | "Run FluidX3D's device listing, then install the NVIDIA driver's OpenCL component. Do not modify FluidX3D core files." |
| Viewer stutters or lags | Snapshot too large | "Log snapshot bytes. Keep it under 1 MB: halve slice resolution, send float16, cap tracers at 8k." |
| Drones end up inside buildings | Edit validation or planner margin gap | "Add a test reproducing this, then fix validation in service and the 5 m margin in the planner." |
| Emulator tab missing | Browser or page not exposing WebXR | "Test in Chrome with the Immersive Web Emulator on threejs.org webxr_xr_dragging first, then our page." |
| GPU path won't run on the Mac | Expected; no CUDA on macOS | Nothing. Develop with AEROSWARM_FORCE_CPU=1; run GPU modules on the NVIDIA laptop. |
| Agent edits unrelated modules | Context drift | "Revert changes outside \<folders\>. Re-read AGENTS.md rule 1 and redo the task within scope." |
| Results differ between runs | Unseeded randomness or thread timing | "Find every RNG and seed it from the scenario. Make replanning results apply at fixed step boundaries." |
