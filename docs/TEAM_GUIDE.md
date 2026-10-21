# AeroSwarm - team guide: what is done, what is next, how to finish

*Status as of 21 Oct 2026. Written for teammates picking the project up. The repo has the code; this document explains it, says what is verified,
and lays out how to link and finish the whole project. Deeper detail lives in `HANDOFF_WINDOWS.md` (runbook), `docs/LINKING_GUIDE.md` (own engine),
`docs/protocol.md`, `docs/xr.md`, `AGENTS.md` (rules for coding agents) and `PROGRESS.md` (live status).*

## 1. TL;DR

* **The complete fallback baseline is built and tested on a Mac (no CUDA):** wind interface with three tiers, drones + swarm grid, wind-aware A*, scenarios/metrics/replay,
  live service, browser viewer with building editor and XR rig, benchmarks and experiments. `git clone` -> `pip install -r requirements.txt` ->
  `python -m service.server` -> open `http://127.0.0.1:8080` works with no GPU and no Node.
* **Tier 2 is real CFD already:** the FluidX3D pipeline built and ran on a Mac GPU (OpenCL) - 4 full-resolution jobs are committed in `data/fields/`.
* **What is left is mostly the NVIDIA laptop**: run the never-executed GPU code (a cupy kernel, lbmpy CUDA), generate the full Tier 2 set (3 layouts x 8 directions),
  measure MLUPS/FPS, rehearse the demo, record the video, write the report - and, as the real engineering goal, **link the team's own CUDA engine** behind
  the `native` adapter (a C ABI, tests and a mock are ready).
* **Two gotchas you must know:** (1) Tier 1 (lbmpy) cannot run on native Windows - use WSL2 Ubuntu (reason in section 5). (2) `docs/explainer.pdf` was never provided (BLOCKERS B1).

## 2. What has been done

| Area | What exists | Evidence (all on the Mac) |
|------|-------------|---------------------------|
| Contracts (P0) | `engine/backend.py` (cupy or numpy `xp`), `WindSource` protocol + factory, scenario schema (validated JSON), 4 scenarios, binary snapshot codec, `docs/protocol.md` | schema/backends/protocol round-trip tests; the JS decoder is tested against bytes produced by the Python codec |
| Tier 3 wind (P1) | `engine/wind/synthetic.py`: log-law inflow, speed-up beside walls, roof upwash, wake 5h long, vortex gusts at Strouhal 0.2 | zero inside buildings, inflow recovered upstream, wake slower, only the wake changes over time, shedding frequency = 0.2 U/W |
| Validation (P2) | D2Q9 cylinder + collision-conservation baselines (`tests/validation`) | St = **0.163** (numpy) and **0.181** (lbmpy), window 0.16-0.22; mass/momentum conserved to 1e-6 in float32 |
| Swarm (P3) | `engine/swarm`: PD + drag + separation, uniform grid (histogram -> scan -> scatter -> 27 cells), naive path, cupy RawKernel | grid == naive **exactly** for 2k drones; reach waypoints; crosswind drift; energy ordering headwind > still > tailwind |
| Planner (P4) | `engine/planner/astar.py`: 10 m grid, layers 20-80 m, 26-connected, wind-risk cost (headwind, gust, crosswind), async replanner, reachability | A* cost == independent Dijkstra; paths keep clearance; wake blob makes the aware path bend; walled-in targets unreachable |
| Scenarios/metrics (P5) | `Simulation` + headless runner, per-mission metrics, replay.bin, paired `compare` | **same scenario + seed -> identical metrics** (naive and aware) |
| Service (P6) | aiohttp WebSocket service, 8k tracers, edit validation (bounds, overlap, depots, targets, drones in the way, reachability), relayout at a step boundary | rejected edit leaves layout unchanged; start-up 0.4 s; tick 13-16 ms incl. a 1000-drone scenario; snapshot 154-181 kB (< 1 MB) |
| Viewer (P7/P8/P11) | Vite + three.js: LOD instanced drones, tracer trails, float16 wind-slice texture, HUD, building editor, WebXR rig + controller grab | 13 JS unit tests; built page driven in a real browser: edit accepted -> wind settles -> layout updates; drop on depot -> rejected with reason and snap-back; 1000 drones + 8k tracers ~120 FPS (Mac) |
| Tier 2 (P9) | `tools/fluidx3d`: case generator, `setup.cpp.template`, batch runner, VTK -> float16 converter; `engine/wind/fluidx3d_field.py` | **FluidX3D built and ran on the Mac GPU**; 4 real jobs (7.4 M cells, 44k steps, 16 snapshots, ~5 min each); real wakes (`docs/img/tier2_vs_tier3_slice.png`) |
| Tier 1 (P10) | `engine/wind/lbmpy_solver.py`: D3Q19 + Smagorinsky, UBB/outflow/free-slip/no-slip, relayout by "second solver settles then swap", units helper | stable; wake behind buildings; relayout swaps atomically; MLUPS counter; lattice inflow <= 0.07, tau 0.5105 |
| Benchmarks/experiments (P12) | `bench/` (MLUPS, FluidX3D benchmark mode, swarm step time), `experiments/run_experiments.py` | tables, plots and `RESULTS.md` in `experiments/results/mac` for all three tiers |
| Linking (new) | `native/aeroswarm_native.h` C ABI, `engine/wind/native.py`, mock engine, `tools/compare_winds.py` | adapter tested against a compiled mock: zero-in-solids, relayout protocol, loud errors |
| Handoff | `HANDOFF_WINDOWS.md`, `scripts/windows/*.ps1`, `scripts/linux/*.sh`, `TESTING_CHECKLIST_WINDOWS.md`, `prompts/WINDOWS_AGENT_PROMPT.md` | scripts' wiring is unit-tested (modules/files they call exist); **the scripts themselves have not been run on Windows** |

## 3. Results so far (Mac - "CPU tiers only")

**Naive vs wind-aware routing** (5 seeds x 3 layouts x 3 tiers, paired by seed, 95% CI; details `experiments/results/mac/RESULTS.md`; * = significant):

| tier | delivery time | energy proxy | mean drift | max drift | near-collisions |
|------|--------------|--------------|-----------|-----------|----------------|
| Tier 3 synthetic | +1.4 .. +1.8 %* | -3.2 .. -8.7 %* | -7 .. -34 %* | -0 .. -67 % | -32 .. +2 % |
| Tier 2 FluidX3D fields | +1.5 .. +1.9 %* | -4.5 .. -9.7 %* | -16 .. -51 %* | +0.4 .. -83 % | -18 .. +24 % |
| Tier 1 lbmpy (CPU, 8 m grid) | +1.4 .. +2.2 %* | -1.9 .. -12.1 %* | -18 .. -48 %* | -3.5 .. -82 % | -28 .. +29 % |

Reading: wind-aware routing **costs ~1.5-2 % delivery time and saves 2-12 % energy and 7-51 % mean cross-track drift** consistently across tiers and layouts.
Near-collisions go both ways (aware routes concentrate traffic) - do not claim an improvement there. These are *our* metric definitions (see `engine/metrics/metrics.py`).

**Wind tiers vs each other** (block_small, z = 30 m, `tools/compare_winds.py`): Tier 2 (FluidX3D 2 m) vs Tier 1 (lbmpy 4 m, CPU): relative L2 **0.17**, correlation **0.93**,
speed ratio 1.06, wake ratio 1.14 -> within the default swap tolerance. Tier 2 vs Tier 3: relative L2 0.36, correlation 0.75, **wake ratio 5.2** - the analytic wake is far
weaker than real CFD (see next-steps item "calibrate Tier 3").

**Performance:** FluidX3D benchmark (256^3, FP16S) **2056 MLUPs = 79 % of the bandwidth ceiling** on the M1 Pro (200 GB/s, 77 B/cell); lbmpy single-thread CPU
~25 MLUPS (4 % of a 328 B/cell ceiling - CPU, not representative of CUDA); swarm step 1k drones **1.96 ms (grid) vs 20.5 ms (naive)**, 10k **14.5 ms vs 1289 ms**.

Always state the tier with a result: **Tier 2 output is FluidX3D's, not the team's own kernels.**

## 4. Known gaps and risks (be honest in the report)

1. **Never executed on a GPU:** the cupy `RawKernel` neighbour loop (`engine/swarm/grid.py`), the lbmpy CUDA target, `scripts/windows/*.ps1`, `scripts/linux/*.sh`, the XR session itself.
2. **`docs/explainer.pdf` missing** -> the "1D worked example" of the P2 test is a textbook D1Q3 stand-in (BLOCKERS B1).
3. **Tier 3's wake is much weaker than CFD** (wake ratio 5.2). Fine as the instant tier, but calibrate it against Tier 2 before using it for quantitative claims.
4. **Tier 2 menu is small on the Mac:** only block_small (0/90 deg) and street_canyon/tower_cluster (0 deg) exist; the other directions are generated on the laptop.
5. **Near-collision metric** is noisy and layout dependent; keep claims to energy/drift/delivery time.
6. **Licences:** FluidX3D is non-commercial/no-military/no-AI-training and requires publishing the altered source with any published results; lbmpy/pystencils are GPL-3.0-or-later;
   the repo has no licence file yet - decide as a team (`CREDITS.md`).
7. Node 26 built the viewer on the Mac; the guide wants Node 20 (works with both; keep `viewer/package-lock.json`).
8. Replays (`replay.bin`) are written and readable in Python but the viewer cannot play them yet.

## 5. Gotcha: Tier 1 needs Linux
`pystencils 2.0`'s CPU JIT knows only Linux and macOS compilers (no MSVC), and `lbmpy` compiles its macroscopic-value kernels on the CPU even for the GPU target.
On Windows run Tier 1 under **WSL2 Ubuntu** (shares the Windows NVIDIA driver; `scripts/linux/*.sh`); keep FluidX3D on native Windows (WSL2 has no OpenCL).
Native Ubuntu runs everything. This was found by reading the installed pystencils source; it has not been tried on a Windows machine.

## 6. What to do next (suggested split, 4 people)

| # | Workstream | Steps | Done when |
|---|-----------|-------|-----------|
| A | **GPU bring-up** | setup + verify scripts; fix `test_gpu_kernel_matches_xp_path`; fix `test_cpu_and_gpu_agree_within_1e4_after_50_steps` (WSL2); swarm bench on GPU | `run_tests.ps1` and `run_tests.sh` print RESULT PASS with 0 skips |
| B | **Tier 2 dataset + FluidX3D numbers** | `run_fluidx3d_batch.ps1` (24 jobs, runs unattended ~2-3 h); FluidX3D benchmark mode; check wakes in `slice_z(30)` | 3 x 8 fields, < 3 GB, benchmark row in the MLUPS table |
| C | **Tier 1 on GPU + experiments + demo** | 200x150x60 at 2 m, MLUPS at 64^3/128^3/256x128x128, cylinder on GPU, `bench.sh`, `bench.ps1`; rehearse `demo.ps1`, FPS on `stress_1k`, XR walkthrough, screen recording | all `TESTING_CHECKLIST_WINDOWS.md` boxes ticked with evidence |
| D | **Own CUDA engine -> `native` adapter** | section 7 | passes P2 tests + `compare_winds` vs Tier 1 on three layouts, or the team decides to ship the fallback |
| all | **Report** | per-tier labelled tables from `results/`, MLUPS vs bandwidth ceiling, naive-vs-aware, credits | submission |

Proposed dates (the guide's, shift freely): Dec 20 = full desktop demo on Tier 3 **and** Tier 2 (every demo-flow box ticked); Jan 10 = swap decision; January = experiments + report.
If the lab is short on time, order of value: A -> B -> C(demo + evidence) -> D.

## 7. How to approach linking the team's own engine
The rule that makes it painless: nothing but a wind adapter knows which tier runs. Your engine is the fourth adapter - **do not change the swarm, planner, service or viewer.**

1. **Copy the mock** `native/mock/aero_mock.c` as the skeleton. Keep its function names/signatures (`native/aeroswarm_native.h`, ABI version 1): create/reset/step/sample/slice/relayout/stats.
   Build to `native/build/aeroswarm_native.dll` (or `AEROSWARM_NATIVE_LIB`), run `python -m service.server --wind native` - the viewer shows your (fake) wind immediately.
2. **Validate the maths in 2D first** with the P2 tests (cylinder St in 0.16-0.22, collision conserves mass/momentum) before any 3D work.
3. **3D in layers:** periodic box + D3Q19 BGK -> bounce-back for the building mask -> log-law UBB inflow + outflow -> Smagorinsky -> relayout (build the new geometry beside the running one, `ready` when settled, `commit` at a step boundary).
4. **Stay inside the stability rules:** lattice inflow <= 0.08, tau > 0.51, Smagorinsky on; SI units at the boundary.
5. **Compare continuously:** `python tools/compare_winds.py scenarios/block_small.json lbmpy native` (thresholds in the script; Tier 2 vs Tier 1 passes with margin, so they are achievable).
6. **Benchmark with the same harness** and report MLUPS as a percentage of the bandwidth ceiling.
7. **Decide on Jan 10:** swap only if P2 + `compare_winds` pass on all three layouts; otherwise ship Tier 2 for the demo and Tier 1 for live edits.
Optimisations come last (device-pointer sampling, async streams, fused swarm step) - see `docs/LINKING_GUIDE.md` section 4.

## 8. Working agreements
* One task per branch; commit message `P<n>: <summary>`; never force-push or rewrite history; GPU work goes on `windows-gpu`.
* Every change ships a test (or a headless check for the viewer) and a one-line demo command; run `pytest -m "not gpu and not fluidx3d"` before pushing.
* Determinism: same scenario + seed -> same metrics (CPU exactly, GPU within 1e-4 relative). Seed every RNG from the scenario.
* No silent fallbacks: a failed GPU path must log loudly; the code only continues on numpy when `AEROSWARM_ALLOW_CPU_FALLBACK` allows it.
* Borrowed code gets a comment with URL + licence and a line in `CREDITS.md`. Read the *installed* version of lbmpy/pystencils/cupy/three.js before using their APIs.
* If you use a coding agent: give it `AGENTS.md`, one module prompt at a time, and check three things - tests pass, its demo command works, `git diff` stays inside the module's folders.

## 9. Quick reference
```bash
python -m pytest -m "not gpu and not fluidx3d"                     # CPU suite     (cd viewer && npm test: JS tests)
python -m service.server --scenario scenarios/block_small.json --wind synthetic|fluidx3d|lbmpy|native
python -m engine.scenario.runner scenarios/block_small.json --wind synthetic --routing aware --seed 1 --headless
python -m engine.scenario.compare runs/A runs/B                      # paired comparison
python -m experiments.run_experiments --tiers synthetic fluidx3d lbmpy
python -m bench.mlups ; python -m bench.fluidx3d_bench ; python -m bench.swarm_bench
python -m tools.fluidx3d.batch --dry-run                           # Tier 2 jobs and budget
python tools/demo_check.py                                           # scripted demo flow against a running service
python tools/compare_winds.py scenarios/block_small.json fluidx3d lbmpy
```
Scenarios: `block_small` (the guide's 400 x 300 m, 6 buildings, 2 depots, 50 missions), `street_canyon`, `tower_cluster`, `stress_1k` (1000 drones).
Wind direction convention: degrees the wind blows **toward**, counter-clockwise from +x (east); x east, y north, z up.
