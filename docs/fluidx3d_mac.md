# FluidX3D on macOS - outcome of the time-boxed attempt

**Result: it works** (Apple M1 Pro, macOS, OpenCL 1.2 "Apple" platform, Xcode command-line tools).

* `make macOS` links X11 which is not installed on a stock Mac, so the build uses the other recipe from FluidX3D's
  own `make.sh`, `g++ src/*.cpp -o bin/FluidX3D -std=c++17 -pthread -O -Wno-comment -I./src/OpenCL/include -framework OpenCL`
  (what `tools/fluidx3d/batch.py::build` does on Darwin). Compile time ~7 s with `-j`, ~1 min single core. OpenCL on macOS is
  deprecated (compiler warnings) but functional.
* Device found: `Apple M1 Pro, 14 CUs, 12 GB, OpenCL C 1.2`. Max single buffer 2273 MB, plenty for the 7.4 M-cell domain (~410 MB).
* The AeroSwarm template (`tools/fluidx3d/setup.cpp.template`) ran end to end: 4 real production jobs (block_small 0/90 deg,
  street_canyon 0 deg, tower_cluster 0 deg) at full resolution (400x288x64 cells, dx = 2 m, 43 889 steps, 16 snapshots), ~4.5-5 min each.
* Comparison of its z=30 m wind slice with the synthetic Tier 3 field: `docs/img/tier2_vs_tier3_slice.png`.
* FluidX3D benchmark mode (256^3, FP16S) on this GPU: see `experiments/results/mac/mlups_fluidx3d.csv`.

Caveats: fields for the other 5 directions of every layout were not computed on the Mac (budget of time, not of ability);
run `scripts\windows\run_fluidx3d_batch.ps1` on the NVIDIA laptop to complete the set (8 directions x 3 layouts).
