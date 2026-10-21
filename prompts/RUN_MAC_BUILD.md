Build AeroSwarm on this Mac as far as it can possibly go, autonomously, then prepare a clean handoff for teammates who have NVIDIA Windows laptops. Follow AGENTS.md exactly. Do not ask me for confirmation between tasks. If blocked: write BLOCKERS.md, run tools/notify.sh, take the documented fallback, continue.

STEP 0 — Resume or start
- If PROGRESS.md exists: continue from the first unchecked item (re-run its tests first if code already exists).
- Else: `git init`; `bash tools/docx_to_md.sh`; read docs/md/INDEX.txt; then read by heading: purpose/tiers, architecture, download checklist, repos to clone, pick list, build order and gates, master context prompt, every module prompt P0–P12, demo/testing checklist, troubleshooting. Create PROGRESS.md: one line per task with its tag ([MAC] / [MAC+GPU] / [WINDOWS], rules in AGENTS.md), its gate, and status.

STEP 1 — Environment (Mac)
- Python 3.11 venv at .venv with numpy, scipy, aiohttp, pytest, matplotlib, meshio, pyvista, plus lbmpy/pystencils for the CPU target (and osmnx/geopandas/shapely only if the guide's optional extension is in scope). No cupy.
- Node 20 for viewer/ (Vite + three.js).
- Clone the guide's reference repos into third_party/ with --depth 1.
- If an install needs network access, request it. If a package truly cannot install on macOS, mark the dependent tests gpu/windows and record it in BLOCKERS.md.

STEP 2 — Build every task, P0 → P12, in order
For each task: re-read its module prompt → implement exactly that scope → tests + one-line demo command → run `pytest -m "not gpu and not fluidx3d" -q` (plus `npm run build` and a headless check for viewer work) → fix → tick PROGRESS.md → commit "P<n>: …".
- [MAC] tasks: complete fully.
- [MAC+GPU] tasks: complete code for both backends via the xp switch; CPU path tested here; GPU tests written, marked, skipping cleanly.
- [WINDOWS] tasks: scripts, configs, converters (tested on synthetic fixtures), docs. Never fake results.
- At every gate in the guide's build order: run the full Mac suite and the CPU demo end to end, record the gate result in PROGRESS.md, notify.

STEP 3 — Experiments that can run here
Run the guide's P12 experiments on the tiers available on this Mac (synthetic wind; lbmpy CPU on small grids): naive vs wind-aware routing, seeds 1–5 — via tools/bg.sh if long. Tables + plots to experiments/results/mac/, clearly marked "CPU tiers only". Write the GPU benchmark harness (MLUPS vs bandwidth ceiling, FluidX3D benchmark mode, swarm step-time vs N for CPU vs GPU and naive vs grid search) so it runs unchanged on Windows.

STEP 4 — Handoff package (details in AGENTS.md "Windows handoff")
HANDOFF_WINDOWS.md, scripts/windows/*.ps1, TESTING_CHECKLIST_WINDOWS.md, docs/xr.md, docs/protocol.md (current), README.md (overview, Mermaid architecture, quick start for Mac and Windows, tier matrix, results so far), CREDITS.md. The bar: a teammate goes from `git clone` to GPU results by following HANDOFF_WINDOWS.md alone, with prompts/WINDOWS_AGENT_PROMPT.md for their own coding agent.

STEP 5 — Final check and report
From a fresh shell: setup + `pytest -m "not gpu and not fluidx3d"` + the CPU demo (service + viewer build) all pass. `bash tools/notify.sh "AeroSwarm: Mac build DONE" "Ready for Windows handoff"`. Final reply: per-task status table, what teammates must do (in order), known issues, demo command.
