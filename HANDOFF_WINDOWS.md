# HANDOFF - finish AeroSwarm on the NVIDIA laptop

Everything that does not need CUDA or FluidX3D-on-NVIDIA was built and tested on an Apple-silicon Mac. This file takes a teammate
from `git clone` to GPU results. Paste `prompts/WINDOWS_AGENT_PROMPT.md` into your coding agent if you use one; the scripts below
print `PASS:` / `FAIL:` lines and write logs to `results\windows\<date>\` (Linux/WSL2 scripts: `results/linux/<date>/`).

> **Read this first - Tier 1 needs Linux.** `pystencils 2.0` (used by `lbmpy`) has CPU-JIT compiler support for Linux and macOS only (no MSVC),
> and `lbmpy` compiles its macroscopic-value kernels on the CPU even for the GPU target. Native Windows therefore runs: swarm GPU
> kernel (cupy), Tier 3, Tier 2 (FluidX3D builds with Visual Studio and uses the NVIDIA OpenCL runtime), service, viewer, XR.
> **Tier 1 (lbmpy live solver, the lbmpy CUDA tests, MLUPS of Tier 1) must run under WSL2 Ubuntu or native Ubuntu** with `scripts/linux/*.sh`.
> WSL2 shares the Windows NVIDIA driver (do not install a driver inside it) but has **no OpenCL**, so FluidX3D stays on native Windows.
> The two sides share the repo folder (`/mnt/c/...` in WSL2) and `data/fields`.

## 1. Task status

| Task | Tag | Done on Mac | Still needs the NVIDIA laptop |
|------|-----|-------------|-------------------------------|
| P0 scaffold, schema, backend, protocol | [MAC] | complete, tested | - |
| P1 Tier 3 synthetic wind | [MAC] | complete, tested | - |
| P2 validation baselines | [MAC] | numpy D2Q9 St = 0.163; lbmpy D2Q9 St = 0.181; collision conservation | `lbmpy_cylinder_2d.run_lbmpy_cylinder(target="gpu")` St; **`docs/explainer.pdf` missing** (BLOCKERS B1) |
| P3 drones + swarm grid | [MAC+GPU] | numpy path complete, grid == naive exactly (2k drones), bench script | run the `gpu` test: **the cupy RawKernel `separation_gpu` has never been compiled** (no CUDA on the Mac); bench N = 100/1k/10k on GPU |
| P4 wind-aware A* | [MAC] | complete (CPU), async replanner | - |
| P5 scenarios, metrics, replay | [MAC] | complete, deterministic (identical metrics twice, naive + aware) | GPU path determinism within 1e-4 |
| P6 live service | [MAC] | complete, tested (protocol round trip, rejected edit leaves layout unchanged) | - |
| P7 viewer | [MAC] | complete; 1000 drones + 8k tracers + slice measured at ~120 FPS in a Mac browser | **the 50+ FPS check on this laptop** (`stress_1k.json`) |
| P8 building editor | [MAC] | complete; verified in a real browser (pick, move, accept / reject + snap-back) | manual drag with the mouse on this laptop |
| P9 Tier 2 FluidX3D | [WINDOWS] | complete pipeline, **ran on the Mac GPU**: 4 real jobs (block_small 0/90, street_canyon 0, tower_cluster 0 deg) committed under `data/fields/`; adapter + converter tested | build with MSVC, **the full 3 layouts x 8 directions set** (`run_fluidx3d_batch.ps1`, 2.76 GB), FluidX3D benchmark mode on the RTX 3060 |
| P10 Tier 1 lbmpy | [MAC+GPU] | complete on CPU (grid 8 m: tests; 4 m: comparison); relayout swap works; Tier 2 vs Tier 1 comparison passes | **CUDA path**: parity test, MLUPS, 200x150x60 at 2 m, cylinder on GPU - under WSL2/Ubuntu |
| P11 WebXR | [MAC] | build + rig/grab logic unit-tested | the emulator walkthrough (`docs/xr.md`) |
| P12 bench + experiments | [MAC+GPU] | harness complete, Mac results in `experiments/results/mac` (all three tiers) | the same harness unchanged on the GPU (`bench.ps1`, `scripts/linux/bench.sh`) |

## 2. One-time setup (about an hour)

Install by hand, in this order:
1. **NVIDIA driver** (Studio or Game Ready, latest) - check `nvidia-smi`.
2. **CUDA Toolkit 12.x** - check `nvcc --version` (cupy-cuda12x wheels need a driver supporting CUDA 12).
3. **Visual Studio 2022 Community** with *Desktop development with C++* (needed to build FluidX3D).
4. **Git** + **Git LFS** (`git lfs install`), **Node.js 20 LTS**, **Miniconda**.
5. Chrome + the **Immersive Web Emulator** extension (Chrome Web Store; Meta).
6. (Tier 1) **WSL2 Ubuntu 22.04/24.04** (`wsl --install -d Ubuntu`), then inside it `sudo apt update && sudo apt install -y build-essential git python3.11 python3.11-venv`.

Then, in PowerShell at the repo root (`git clone <repo>; cd aeroswarm`):
```powershell
powershell -ExecutionPolicy Bypass -File scripts\windows\setup.ps1      # conda env aeroswarm (Python 3.11), cupy-cuda12x, lbmpy[gpu], npm ci, third_party clones
powershell -ExecutionPolicy Bypass -File scripts\windows\verify_gpu.ps1 # must end with RESULT: verify_gpu PASS
```
and in WSL2 for Tier 1:
```bash
cd /mnt/c/<path to>/aeroswarm && bash scripts/linux/setup.sh && bash scripts/linux/verify_gpu.sh
```
Expected: every line `PASS:`; `AeroSwarm backend = cupy`. Typical fixes: cupy import fails -> install the wheel matching `nvidia-smi`'s CUDA version
(`cupy-cuda12x`); FluidX3D finds no device -> reinstall the full NVIDIA driver package (it ships `OpenCL.dll`).

## 3. Commands, in order, with expected output

| # | Command | Expect |
|---|---------|--------|
| 1 | `scripts\windows\run_tests.ps1` | `PASS: pytest cpu` (hundreds of tests), `PASS: pytest gpu_swarm` (**first real run of the RawKernel - fix it here if it fails**), `PASS: pytest fluidx3d`, `PASS: viewer vitest`. A *skipped* GPU test is a FAIL here |
| 2 | `wsl bash scripts/linux/run_tests.sh` | `PASS: pytest cpu`, `PASS: pytest gpu` (lbmpy CUDA vs CPU within 1e-4, **never run yet**) |
| 3 | `scripts\windows\build_fluidx3d.ps1` | builds `third_party\FluidX3D_aeroswarm\bin\FluidX3D.exe` and runs a coarse smoke job (about a minute) |
| 4 | `scripts\windows\run_fluidx3d_batch.ps1 -DryRun` then without `-DryRun` | 24 jobs (3 layouts x 8 directions), ~5 min each on the Mac GPU, `fields on disk: 2.76 GB (< 3 GB)`; resumable - rerun to continue |
| 5 | `scripts\windows\demo.ps1` | service up in < 30 s, all `tools\demo_check.py` checks PASS, viewer opens; then do the manual checklist items |
| 6 | `scripts\windows\bench.ps1` and `wsl bash scripts/linux/bench.sh` | MLUPS tables (+ % of bandwidth ceiling), swarm step time vs N, experiments on every tier -> `results\...` |
| 7 | `docs\xr.md` walkthrough | XR items of `TESTING_CHECKLIST_WINDOWS.md` |

### Things most likely to need a fix (GPU code that could not be executed on the Mac)
* `engine/swarm/grid.py: SEPARATION_KERNEL_SRC` / `separation_gpu` - a cupy `RawKernel` written but never compiled. Test: `tests/test_p3_swarm.py::test_gpu_kernel_matches_xp_path`.
  Use `long long` offsets already; if NVRTC complains look at integer/float literal types first.
* `engine/wind/lbmpy_solver.py` GPU target - velocity stays on the device (`compute_velocity_in_every_step`), `sample()` reads `dh.gpu_arrays[...]`. Parity test:
  `tests/test_p10_lbmpy.py::test_cpu_and_gpu_agree_within_1e4_after_50_steps`. On GPU the initial velocity is written on the CPU array and the PDFs are uploaded by `pre_run()`.
* Real Tier 1 grid: construct with `dx_m=2.0` (default). CPU-only boxes fall back to 8 m in the service automatically; on GPU the service uses 2 m.
* FluidX3D MSBuild invocation (`tools/fluidx3d/batch.py::build`, `PlatformToolset=v143` overrides the .vcxproj's v142).
* If lbmpy blows up (NaN): print lattice inflow speed and tau (they are logged at start), keep inflow <= 0.08, tau > 0.51, Smagorinsky on; the solver already starts from the log-law profile instead of a ramp.

Rules for fixes (from `AGENTS.md`): touch only the files of the task, read the *installed* lbmpy/cupy source before using their APIs,
every change ships a test, no silent GPU fallbacks, commit per task on branch `windows-gpu` with message `P<n>: ...`, never rewrite history.

## 4. What the results mean (state the tier!)
Every table and plot must name the wind tier that produced it. Tier 2 numbers are FluidX3D's, not the team's own kernels. FluidX3D licence:
non-commercial, no military use, no AI training on its source, cite its papers, and if results from our *altered* build are published, publish the altered
source (this repo's `tools/fluidx3d/setup.cpp.template` + `patch_defines`). See `CREDITS.md`.

## 5. Reporting back
1. Commit logs/tables/plots you want to keep under `results\windows\<date>\` (the folder is gitignored except `.gitkeep`: add what matters with `git add -f`).
   Share the full `data/fields` set via a release asset or shared drive, **not** in git (the Mac demo set is committed; new dirs are ignored on purpose).
2. Update `PROGRESS.md` (tags, gate results), the status table in this file and the "Results" section of `README.md`; freeze `pip freeze > requirements.windows.lock` and `requirements.linux.lock`.
3. Push branch `windows-gpu`, open a pull request. Final message: what passed, key numbers (MLUPS + % of ceiling per tier and grid, St, step times, FPS), open issues.
