# AeroSwarm — progress

Tags: [MAC] fully built + tested on the Mac · [MAC+GPU] code for numpy + cupy, CPU path tested here, GPU tests skip cleanly · [WINDOWS] needs CUDA / FluidX3D: scripts + converters tested on synthetic fixtures, real run pending.

| Task | Tag | Gate | Status |
|------|-----|------|--------|
| P0 scaffold, schema, protocol | [MAC] | – | [x] |
| P1 Tier 3 synthetic wind | [MAC] | – | [x] |
| P2 validation baselines | [MAC] | Gate 1: vortex shedding (St 0.16-0.22) | [x] St = 0.163 |
| P3 drones + swarm grid | [MAC+GPU] | – | [x] |
| P4 wind-aware A* | [MAC] | – | [x] |
| P5 scenarios, metrics, replay | [MAC] | – | [x] |
| P6 live service | [MAC] | – | [x] |
| P7 viewer | [MAC] (50 FPS check [WINDOWS]) | Gate 2: full desktop demo on Tier 3 | [x] |
| P8 building editor | [MAC] | – | [x] |
| P9 Tier 2 FluidX3D fields | [WINDOWS] (converter + field adapter [MAC]) | – | [x] |
| P10 Tier 1 lbmpy solver | [MAC+GPU] | – | [x] |
| P11 WebXR | [MAC] build + logic, headset/emulator [WINDOWS] | – | [x] |
| P12 benchmarks + experiments | [MAC+GPU] | Gate 3 | [ ] |
