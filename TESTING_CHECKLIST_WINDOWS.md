# Testing checklist - NVIDIA Windows laptop (mirrors the guide's "Demo and testing checklist")

Run it once in early December and again the week before the deadline, **with Wi-Fi off**. Tick a box only with evidence:
save the log / screenshot under `results\windows\<date>\` and note the tier that produced it.
Items marked (auto) are executed by a script; the rest are manual. Where the Mac build already passed the CPU
equivalent, the Mac result is listed so you know what to expect.

## Correctness
- [ ] (auto) `scripts\windows\run_tests.ps1` passes on CPU (`AEROSWARM_FORCE_CPU=1`) **and** on GPU
  - Mac reference: `pytest -m "not gpu and not fluidx3d"` -> all green; GPU tests skip there. On Windows a *skipped* GPU test is a failure.
- [ ] (auto) 2D cylinder Strouhal number in [0.16, 0.22] and vorticity PNG saved
  - Mac: numpy baseline St = 0.163, lbmpy CPU D2Q9 St = 0.181 (`tests/validation`); PNG in `docs/img/cylinder_vorticity.png`.
  - On GPU repeat the lbmpy cylinder with `target="gpu"`: `python -c "from tests.validation.lbmpy_cylinder_2d import run_lbmpy_cylinder as r; print(r(target='gpu')['strouhal'])"`
- [ ] (auto) collision conserves mass and momentum; 1D worked example (**needs `docs/explainer.pdf`**, see BLOCKERS.md B1)
- [ ] (auto) grid neighbour search == naive search for 2k drones - `pytest tests/test_p3_swarm.py` incl. the `gpu` RawKernel test
- [ ] (auto) same scenario + seed give identical metrics twice - `pytest tests/test_p5_runner.py -k same_seed`
  - GPU path: identical within 1e-4 relative (run the runner twice with the GPU backend and diff `metrics.csv`)
- [ ] (auto) CPU vs GPU lbmpy agree within 1e-4 after 50 steps - `pytest -m gpu tests/test_p10_lbmpy.py`

## Demo flow (rehearse in this order) - `scripts\windows\demo.ps1`
- [ ] (auto) `python -m service.server --scenario scenarios/block_small.json --wind <best tier>` is up in **< 30 s**
- [ ] 1k drones + 8k tracers + wind slice at **50+ FPS**: start with `--scenario scenarios/stress_1k.json`, read the HUD "FPS (view / server)"
- [ ] (auto) move a building: wind re-settles, layout version bumps, no drone ends up inside it - `tools\demo_check.py`
- [ ] (auto) drop a building on a depot: rejected with a reason, nothing changes - `tools\demo_check.py`
- [ ] (auto) rotate the inflow 45 degrees: wakes swing, swarm replans - `tools\demo_check.py` (and watch it in the viewer)
- [ ] toggle naive vs wind-aware routing and show the live metric difference (HUD "Metrics so far")
- [ ] enter XR in the emulator, ride a drone, grab a building - follow `docs\xr.md`
- [ ] repeat the whole flow on **every** tier available: Tier 3 `synthetic`, Tier 2 `fluidx3d`, Tier 1 `lbmpy` (HUD tier selector)

## Evidence for the report (`scripts\windows\bench.ps1` produces all tables)
- [ ] MLUPS table with percentage of the bandwidth ceiling, per tier and grid size (`mlups_lbmpy.csv`, `mlups_fluidx3d.csv`)
  - Mac reference (CPU lbmpy, single thread): see `experiments/results/mac/mlups_lbmpy.csv`; FluidX3D on M1 Pro: `mlups_fluidx3d.csv`
- [ ] swarm step time vs N (100 / 1k / 10k), CPU vs GPU, naive vs grid (`swarm_step_time.csv` + png)
- [ ] naive vs aware over 5 seeds and 3 layouts: delivery time, energy proxy, drift, near-collisions (`experiments\RESULTS.md`), per tier
- [ ] a recorded screen video of the full demo flow, in case the laptop fails on the day
- [ ] CREDITS.md complete and matching the guide's table; every licence row confirmed against the repo's LICENSE file

## Tier 2 data
- [ ] `scripts\windows\run_fluidx3d_batch.ps1` finished: 3 layouts x 8 directions, `data\fields` < 3 GB, no FAIL lines
- [ ] wake behind the tallest building visible in `slice_z(30)` of the real fields (run `pytest tests/test_p9_fluidx3d.py`; look at `docs/img/tier2_vs_tier3_slice.png` for what it should look like)
