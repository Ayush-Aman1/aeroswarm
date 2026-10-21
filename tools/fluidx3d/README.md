# tools/fluidx3d - Tier 2 (FluidX3D precomputed wind)

```
python -m tools.fluidx3d.batch --dry-run          # jobs, VRAM and disk budget, nothing is run
python -m tools.fluidx3d.batch --build-only       # build the patched FluidX3D copy, print the binary path
python -m tools.fluidx3d.batch                    # all scenarios/*.json x 8 directions (resumable)
python -m tools.fluidx3d.batch --scenarios scenarios/block_small.json --directions 0 90
```
Output: `data/fields/<preset>/dir_<deg>/frame_00..15.npy` (float16 `[nx, ny, nz, 3]`, SI m/s, city frame, 2 m grid,
z up to 80 m) + `meta.json`. All presets x 8 directions = 2.76 GB (limit 3 GB). `engine/wind/fluidx3d_field.py` plays them back.

## What is (and is not) modified in FluidX3D
FluidX3D (https://github.com/ProjectPhysX/FluidX3D, custom licence, free for non-commercial use) stays in
`third_party/FluidX3D` untouched. `batch.py` copies it to `third_party/FluidX3D_aeroswarm/` and, in the copy only:
1. replaces `src/setup.cpp` with `setup.cpp.template` (the AeroSwarm `main_setup()`), and
2. flips extension switches in `src/defines.hpp` (`patch_defines`): **on** `D3Q19`, `SRT`, `FP16S`,
   `EQUILIBRIUM_BOUNDARIES`, `SUBGRID`; **off** `BENCHMARK`, `INTERACTIVE_GRAPHICS`, `GRAPHICS`, `FP16C`.
No core file (lbm.cpp, kernel.cpp, ...) is edited.

## Deviation from the guide, on purpose
The guide says `setup.cpp` reads a *generated header*. FluidX3D interprets `argv` as OpenCL device ids and a header
means recompiling for each of the 24 jobs, so the template reads `aeroswarm_case.txt` from beside the executable
instead (written by `tools/fluidx3d/case.py`). Same information, one build for all jobs.

## The case
* Wind always blows along +x of the lattice; **the city is rotated** by the wind direction (`cos_t`, `sin_t`), never the inflow.
* Domain: city bounding circle + 100 m upstream + 200 m downstream + 40 m sides, 128 m tall, dx = 2 m
  -> 400 x 288 x 64 = 7.4 M cells, ~410 MB VRAM (FP16S). Boundaries: x=0 inflow, x=max outflow, y and z=max free stream
  (all `TYPE_E`, log-law profile), z=0 and buildings `TYPE_S`.
* Units: 1 cell = 2 m; lattice speed of the 10 m reference wind chosen so the fastest inflow cell (+25 % speed-up headroom)
  is <= 0.07 (guide: <= 0.08); viscosity floored so tau = 0.5105 > 0.51; `SUBGRID` (Smagorinsky-Lilly) on.
* Run: settle 3 flow-throughs (~40 k steps), then 16 snapshots 2 s apart with `lbm.u.write_device_to_vtk()` (SI units).
* `convert.py`: VTK (big-endian float32 vectors, x fastest) -> trilinear resample on the 2 m city grid, **velocity rotated back**
  to the city frame, exact zeros inside buildings, float16.

## Verified on the Mac (Apple M1 Pro, OpenCL)
The template builds and runs on macOS (see `docs/fluidx3d_mac.md`); one full job (7.4 M cells, 44 k steps, 16 snapshots)
takes ~4.5-5 min. `tests/test_p9_fluidx3d.py` has a real smoke test (marker `fluidx3d`) plus converter tests on synthetic VTK.
`--solver fake` writes VTKs from the synthetic wind for plumbing tests only; its meta says `FAKE-TEST-ONLY`.
