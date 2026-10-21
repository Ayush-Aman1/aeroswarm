# AeroSwarm — agent rules (Codex reads this file automatically)

## Project in one paragraph
Wind-aware drone swarm simulator for the RVCE PAGP + CGVR course. An urban wind field
(lattice-Boltzmann CFD) drives a drone swarm that compares naive vs wind-aware routing. A Vite +
three.js viewer shows the city, wind slices/tracers and drones, supports live building edits
(relayout) and a WebXR drone's-eye view. Wind comes from three tiers behind one `WindSource`
interface: Tier 3 synthetic (analytic, CPU), Tier 2 FluidX3D precomputed fields (offline, OpenCL,
built on the NVIDIA laptop), Tier 1 live lbmpy solver (CUDA via cupy). Python service ↔ viewer share
`docs/protocol.md`. Target in the guide: full desktop demo by Dec 20, 2026.

## Source of truth
`docs/md/*.md`, converted from `docs/*.docx` by `bash tools/docx_to_md.sh`. Read by heading via
`docs/md/INDEX.txt` (~150 lines around a heading), never the whole file. The guide's tasks P0–P12, its
build-order gates and its master context prompt define the work. On scope/technical detail the guide
wins; on the Mac/Windows split, handoff and cost rules, this file wins.

## Guide rules (restated — follow them)
1. Work only in the folders the current task names. Never refactor others.
2. Before using lbmpy, pystencils, cupy, three.js or FluidX3D APIs, read the INSTALLED version's
   source or docs. Do not rely on memory; versions drift.
3. Every module ships pytest tests (or a headless check for viewer code) and a one-line demo command.
   Run them before reporting.
4. Deterministic: same scenario + seed ⇒ same metrics (CPU path exactly, GPU path within 1e-4 relative).
5. Code borrowed/adapted from third_party/ gets a comment with source URL + licence and a CREDITS.md line.
6. No silent fallbacks: if the GPU path fails, log it loudly; continue on numpy only when config allows.
7. LBM stability: lattice inflow speed ≤ 0.08, tau > 0.51, Smagorinsky on.
8. Each task ends with a short report: files changed, tests run + results, demo command, known issues.

## This machine: Apple-silicon Mac, no CUDA
- Run everything with the numpy backend (`AEROSWARM_FORCE_CPU=1` semantics). Do not install cupy here.
- Tag every guide task in PROGRESS.md:
  - [MAC] — fully buildable and testable here.
  - [MAC+GPU] — write all code here (numpy and cupy paths via engine/backend.py's `xp`); test the CPU
    path here; GPU tests written, marked, and skipping cleanly.
  - [WINDOWS] — needs CUDA or a FluidX3D build: write scripts, configs and converters (tested on
    synthetic fixtures here) plus step-by-step docs. Never fake GPU results.
- pytest markers `gpu` (needs CUDA/cupy), `fluidx3d` (needs a built FluidX3D), `slow` — registered in
  pyproject.toml. `pytest -m "not gpu and not fluidx3d"` must be green on this Mac; GPU tests skip
  (never fail) when CUDA is absent.
- lbmpy (Tier 1): lbmpy also has a CPU target. Implement against the installed API and test small grids
  on CPU here (disable OpenMP on macOS if the compiler lacks it); keep `Target.GPU` behind config.
- FluidX3D (Tier 2): write tools/fluidx3d/ (header generation, batch runner, VTK → float16 .npy
  converter). Test the converter on a small synthetic VTK fixture you generate. Optional, time-boxed to
  15 minutes: try building FluidX3D on macOS (OpenCL); record the outcome in docs/fluidx3d_mac.md either
  way, then move on.
- WebXR (P11): verify what can be checked headlessly (build, XR button wiring, unit tests of the camera
  rig logic); write docs/xr.md with the manual Immersive Web Emulator steps for a human.

## Windows handoff — must exist when the Mac build finishes
- `HANDOFF_WINDOWS.md`: task status table (done on Mac / needs Windows); exact setup (NVIDIA driver,
  CUDA 12.x, VS 2022 "Desktop development with C++" for FluidX3D, Miniconda env `aeroswarm` with
  Python 3.11, cupy-cuda12x, lbmpy[gpu], Node 20, Chrome + Immersive Web Emulator); commands to run in
  order; expected outputs; how to report results back.
- `scripts/windows/`: setup.ps1, verify_gpu.ps1 (nvidia-smi, nvcc, cupy show_config), run_tests.ps1
  (all markers), build_fluidx3d.ps1, run_fluidx3d_batch.ps1, bench.ps1, demo.ps1. Plain PowerShell,
  clear PASS/FAIL lines, logs to results/windows/<date>/.
- `TESTING_CHECKLIST_WINDOWS.md`: checkboxes mirroring the guide's demo/testing checklist.
- `prompts/WINDOWS_AGENT_PROMPT.md` (already provided): keep script names and paths consistent with it;
  update it if you rename anything.

## Workflow and cost
- State files are your memory; resume from them: `PROGRESS.md` (tasks, tags, gate, status),
  `BLOCKERS.md`, `CREDITS.md`.
- Commit after each task: "P<n>: <summary>". Never force-push or rewrite history.
- Keep output small: logs to files, `tail -n 60`, quiet flags, never print big arrays or JSON.
- Long runs (> ~5 min): `bash tools/bg.sh <label> "<cmd>"` (detached, notifies on finish); continue
  other tasks; check `runs/<label>/STATUS` once when needed. No polling loops.
- third_party/ repos are read-only references (gitignored); clone with `--depth 1`.
- Notify with `bash tools/notify.sh "<title>" "<msg>"` at each gate, at blockers needing a human, and
  at completion.
