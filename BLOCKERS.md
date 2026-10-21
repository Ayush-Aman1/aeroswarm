# Blockers and known limits

## B1 - docs/explainer.pdf was not provided (open, needs a human)
The guide refers to `docs/explainer.pdf` (the Phase 1 explainer) for "the 1D worked example" of a BGK collision (P2) and as the simulator's concept source. It is not in the repo.
Fallback taken: `tests/validation/test_collision_conservation.py::test_1d_worked_example` reproduces a standard D1Q3 hand-computed example exactly.
**To close:** a teammate adds the PDF to `docs/` and extends that test with the explainer's numbers.

## B2 - Node version
The guide asks for Node 20 LTS; the Mac that built this had Node 26. The viewer builds and tests with both. `viewer/dist` is committed so Node is only needed to rebuild.

## B3 - Tier 1 (lbmpy) cannot run on native Windows (pystencils 2.0 has no Windows CPU JIT)
Found by reading the installed pystencils source (`jit/cpu/compiler_info.py` knows only Gcc/Clang/AppleClang). lbmpy also compiles its macroscopic getter/setter on the CPU for the GPU target.
Mitigation: run Tier 1 under WSL2 Ubuntu / native Ubuntu (`scripts/linux/*.sh`); `LbmpySolver.available()` returns False on win32 with the reason; lbmpy tests skip there.
A native-Windows alternative would be a custom `CompilerInfo` + a `.pyd` suffix patch or overriding `LatticeBoltzmannStep._compile_macroscopic_setter_and_getter` to use GPU kernels - untested idea.

## B4 - never executed on a GPU (needs the NVIDIA laptop)
`engine/swarm/grid.py::separation_gpu` (cupy RawKernel), the lbmpy CUDA target, `scripts/windows/*.ps1`, `scripts/linux/*.sh`, the XR session. Tests are written (`-m gpu`) and skip cleanly elsewhere.

## B5 - macOS JIT workaround
pystencils links every extension module against libpython; with statically linked interpreters (uv / python-build-standalone) that segfaults on import. `engine/wind/jitfix.py` links with `-undefined dynamic_lookup` instead (no-op on other platforms).

## B6 - Tier 3 wake is much weaker than CFD
`tools/compare_winds.py`: Tier 2 vs Tier 3 wake ratio 5.2 (see TEAM_GUIDE section 3). Calibrate `engine/wind/synthetic.py` (WAKE_DEFICIT, wake width) against Tier 2 before quantitative claims.
