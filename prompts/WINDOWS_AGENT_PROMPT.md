You are finishing AeroSwarm on an NVIDIA Windows laptop. Everything that doesn't need CUDA or FluidX3D was already built and tested on a Mac. Read AGENTS.md (skip its "This machine: Apple-silicon Mac" section — everything else applies), HANDOFF_WINDOWS.md, PROGRESS.md and BLOCKERS.md first. Work autonomously; don't ask for confirmation between steps.

1. Run scripts/windows/setup.ps1, then scripts/windows/verify_gpu.ps1. Fix environment problems (driver, CUDA 12.x, VS 2022 C++ workload, conda env `aeroswarm`, cupy-cuda12x, lbmpy[gpu]) until verify_gpu.ps1 prints PASS.
2. Run scripts/windows/run_tests.ps1. Fix failures in GPU paths only — do not rewrite Mac-tested CPU code unless a test proves it wrong.
3. Complete every task tagged [MAC+GPU] or [WINDOWS] in PROGRESS.md, in order:
   - GPU backend parity: CPU vs GPU results within 1e-4 relative.
   - Tier 1 lbmpy live solver on GPU: cylinder Strouhal test, MLUPS measurement, relayout swap.
   - Tier 2 FluidX3D: build, batch-export the layout presets × 8 directions (total under 3 GB), convert to .npy, WindSource on the real fields.
   - Swarm GPU path and the P12 benchmarks and experiments on all tiers.
4. Run scripts/windows/demo.ps1 and every item in TESTING_CHECKLIST_WINDOWS.md; save logs, tables and plots under results/windows/<date>/.
5. Update PROGRESS.md, the status table in HANDOFF_WINDOWS.md and the README results; commit per task on a branch named `windows-gpu`; push and open a pull request. Final report: what passed, the key numbers, open issues.
