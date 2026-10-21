# Linking the team's own CUDA engine ("native" adapter) and the swap decision

Everything in AeroSwarm sees wind only through `WindSource` (`engine/wind/base.py`). Your engine becomes the
**fourth adapter**; nothing else changes. The adapter and a working reference already exist:

| piece | file | status |
|-------|------|--------|
| C ABI contract | `native/aeroswarm_native.h` | done, ABI version 1 |
| ctypes adapter | `engine/wind/native.py` (`NativeWind`) | done, tested against the mock |
| reference/skeleton engine (not physics) | `native/mock/aero_mock.c` | done - copy it as the starting point |
| test of the whole contract | `tests/test_native_adapter.py` | passes on the mock; must pass on yours |
| tier comparison tool | `tools/compare_winds.py` | done; calibrated Tier 2 vs Tier 1 (below) |

## 1. Implement the ABI (CUDA side)
Export these functions from `aeroswarm_native.dll` (Windows) / `libaeroswarm_native.so` (Linux); see the header for
exact semantics. All arrays are host memory, `[nx][ny][nz]` row-major with k fastest, vectors float32 with 3 components innermost.

```
int          aero_abi_version(void);                                   // return 1
AeroEngine*  aero_create(int nx, int ny, int nz, float dx_m, float dt_s);
void         aero_destroy(AeroEngine*);
int          aero_reset(AeroEngine*, const uint8_t* solid, float speed, float dir_deg, float z0);
int          aero_step(AeroEngine*, int n);                            // n sim steps of dt_s
int          aero_sample(AeroEngine*, const float* pos, int n, float* out_vel);   // trilinear, zero in solids
int          aero_slice_z(AeroEngine*, float z_m, float* out);         // [nx][ny][3]
int          aero_relayout_begin(AeroEngine*, const uint8_t* solid, float speed, float dir_deg, float z0);
int          aero_relayout_ready(AeroEngine*);                         // 1 ready, 0 settling, <0 error
int          aero_relayout_commit(AeroEngine*);                        // at a step boundary
int          aero_stats(AeroEngine*, double* mlups, double* step_ms);
const char*  aero_last_error(void);
```
Units at the boundary are SI. Convert to lattice units inside the engine (keep lattice inflow <= 0.08, tau > 0.51,
Smagorinsky on - AGENTS.md rule 7). Grid: use the grid you are given (`nx,ny,nz` = scenario bounds / `dx_m`, 200x150x60 at 2 m for block_small).
Inflow: log-law `U(z) = speed * ln(z/z0) / ln(10/z0)` blowing toward `dir_deg` (CCW from +x; 0 = towards +x).
Relayout: `begin` must not disturb the running wind; `ready` becomes 1 once the new geometry has settled;
`commit` swaps atomically. `aero_sample` must return exactly zero inside solid cells.

Build (example): `nvcc -shared -o native\build\aeroswarm_native.dll your_engine.cu` (add `-Xcompiler /MD` on MSVC) or
`cl /LD native\mock\aero_mock.c /Fe:native\build\aeroswarm_native.dll` for the mock. Then:
```powershell
$env:AEROSWARM_NATIVE_LIB = "C:\path\to\aeroswarm_native.dll"
python -m service.server --wind native
```

## 2. Prove it (acceptance tests)
1. `pytest tests/test_native_adapter.py` with `AEROSWARM_NATIVE_LIB` pointing at your library: change the `lib` fixture to
   return that path instead of compiling the mock (the assertions about zero-in-solids, relayout protocol and
   error handling are the contract).
2. The **P2 tests on your kernels** (guide section "Jan 10 swap decision"): the collision-conservation test and the 2D
   cylinder Strouhal test (`tests/validation/*`) - expose a 2D/BGK entry point from your engine or run the same
   analysis (`tests/validation/lbm2d.strouhal`) on your solver's probe signal. Pass: 0.16 <= St <= 0.22.
3. **Match Tier 1 within tolerance**:
   `python tools\compare_winds.py scenarios\block_small.json lbmpy native --steps 2000 --cfg-a "{\"dx_m\": 2.0}" --out results\windows\<date>\compare`
   Default thresholds (change them as a team): relative L2 <= 0.30, speed correlation >= 0.90, mean speed within 10 %,
   wake strength within 25 %. Calibration from the Mac: **Tier 2 (FluidX3D, 2 m) vs Tier 1 (lbmpy, 4 m, CPU):
   rel L2 0.17, corr 0.93, speed ratio 1.06, wake ratio 1.14 -> pass**; Tier 2 vs Tier 3 (analytic): rel L2 0.36, corr 0.75,
   wake ratio 5.2 -> fail (the analytic wake is far weaker than CFD, see `docs/TEAM_GUIDE.md`).
4. Benchmarks on the same harness: `bench.mlups`-style numbers for your engine against the bandwidth ceiling.

## 3. Swap decision
Replace the fallback only if (a) the P2 tests pass on your kernels and (b) `compare_winds` passes against Tier 1 on all three layouts.
Otherwise the fallback (Tier 2 for the demo, Tier 1 for live edits) is the submission. The swap itself is one config value:
`--wind native` (service) / `--wind native` (runner). Keep Tier 1/2 results in the report labelled by tier.

## 4. Performance follow-ups once it runs
* `aero_sample` takes host pointers (simple, portable). If the PCIe copy shows up in the profile, add a device-pointer
  variant (`aero_sample_device`) and call it from `NativeWind.sample` with cupy device arrays (`__cuda_array_interface__`).
* Keep `aero_step` asynchronous on a CUDA stream and synchronise inside `aero_sample`/`aero_slice_z`.
* The swarm kernel (`engine/swarm/grid.py: separation_gpu`) already runs on cupy; a fully fused engine+swarm step is
  an optimisation, not a requirement.
