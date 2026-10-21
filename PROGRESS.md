# AeroSwarm - progress (state file; agents resume from here)

Tags: [MAC] fully built + tested on the Mac · [MAC+GPU] code for numpy + cupy, CPU path tested here, GPU tests written and skipping cleanly · [WINDOWS] needs CUDA / FluidX3D on the NVIDIA laptop: scripts + converters tested here, real run pending.
Last update: 2026-10-21 (Mac build). Next owner: the Windows/Linux GPU session, see `HANDOFF_WINDOWS.md`.

| Task | Tag | Gate | Status |
|------|-----|------|--------|
| P0 scaffold, schema, backend, protocol | [MAC] | - | [x] done, tested |
| P1 Tier 3 synthetic wind | [MAC] | - | [x] done, tested |
| P2 validation baselines | [MAC] | Gate 1: vortex shedding (St 0.16-0.22) | [x] **Gate 1 passed**: numpy St = 0.163, lbmpy St = 0.181; collision conservation; 1D worked example is a stand-in (BLOCKERS B1) |
| P3 drones + swarm grid | [MAC+GPU] | - | [x] CPU path tested; cupy RawKernel written, `gpu` test pending on Windows |
| P4 wind-aware A* | [MAC] | - | [x] done, tested |
| P5 scenarios, metrics, replay | [MAC] | - | [x] done, deterministic |
| P6 live service | [MAC] | - | [x] done, tested |
| P7 viewer | [MAC] (50 FPS on the NVIDIA laptop: [WINDOWS]) | Gate 2: full desktop demo on Tier 3 | [x] **Gate 2 (Mac, Tier 3 + Tier 2 + Tier 1-CPU): scripted demo flow 13/13 PASS**; FPS on the laptop pending |
| P8 building editor | [MAC] | - | [x] done; accept/reject verified in a real browser |
| P9 Tier 2 FluidX3D fields | [WINDOWS] (pipeline [MAC], ran on Apple GPU) | - | [~] pipeline + adapter done; 4 real jobs committed; full 3 x 8 set + MSVC build + RTX benchmark pending |
| P10 Tier 1 lbmpy solver | [MAC+GPU] | - | [~] CPU path done (needs Linux/macOS); CUDA path + MLUPS on GPU pending (WSL2 on Windows) |
| P11 WebXR | [MAC] build + logic; session [WINDOWS] | - | [~] built, rig/grab logic unit-tested; emulator walkthrough pending |
| P12 benchmarks + experiments | [MAC+GPU] | Gate 3 | [~] harness done; Mac results (all 3 tiers) in `experiments/results/mac`; GPU runs pending |
| Linking (native adapter) | [MAC] | Jan-10 swap decision | [x] ABI + adapter + mock + compare tool; the real CUDA engine is the team's work |
| Windows handoff package | [MAC] | - | [x] HANDOFF_WINDOWS.md, scripts/windows, scripts/linux, checklist, TEAM_GUIDE |

## Gate log
* Gate 1 (vortex shedding): passed - St 0.163 (numpy D2Q9), 0.181 (lbmpy D2Q9).
* Gate 2 (full desktop demo): Mac - `tools/demo_check.py` 13/13 on Tier 3; Tier 2 and Tier 1 (CPU, 8 m grid) verified through the service in tests; manual XR + 50 FPS pending on the laptop.
* Gate 3 (evidence): Mac tables done; GPU tables pending.
