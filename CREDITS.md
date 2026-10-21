# Credits and licences

Format: `Adapted from <repo URL> (<licence>), <what was taken>`. Every result in reports must say which
wind tier produced it (Tier 3 synthetic · Tier 2 FluidX3D · Tier 1 lbmpy).

| Source | Used for | Licence | How it is used here |
|--------|----------|---------|--------------------|
| FluidX3D — https://github.com/ProjectPhysX/FluidX3D | Tier 2 wind fields | Custom, free for non-commercial use | External tool, never vendored; only `setup.cpp` is templated (tools/fluidx3d/) |
| lbmpy / pystencils — https://pypi.org/project/lbmpy/ | Tier 1 wind solver | GPL-3.0 (lbmpy), AGPL-3.0 (pystencils) — copyleft | pip dependency only, not vendored. Check before any redistribution beyond the course. |
| latticeboltzmann-python — https://github.com/pmocz/latticeboltzmann-python | 2D validation idea | GPL-3.0 | **Reference only.** The D2Q9 code in `tests/validation/` is written from the standard algorithm, no code copied (GPL would infect this repo). |
| cuda_d2q9_flow_over_cylinder — https://github.com/akdemironur/cuda_d2q9_flow_over_cylinder | 2D CUDA reference for parity | check | Reference only (not cloned or used on the Mac) |
| urban-wind-lab — https://github.com/arch85-km/urban-wind-lab | Colour-map / slice / tracer ideas | MIT | Ideas only |
| NVIDIA cuda-samples (particles) — https://github.com/NVIDIA/cuda-samples | Uniform-grid neighbour search sequence | BSD-3-Clause style | `engine/swarm/grid.py`: hist → scan → scatter and 27-cell loop re-implemented; the CuPy RawKernel is modelled on `particles` |
| GPU-CUDA-Flocking — https://github.com/LinDadaism/GPU-CUDA-Flocking | Scattered vs coherent grid comparison method | check | Reference only (bench method) |
| three.js — https://github.com/mrdoob/three.js | Viewer, editor, XR | MIT | npm dependency; OrbitControls, TransformControls, VRButton from `three/examples/jsm`; controller-grab pattern adapted from the `webxr_xr_dragging` example (MIT) |
| webgl-wind — https://github.com/mapbox/webgl-wind | Fading particle-trail idea | ISC | Idea only; the trail shader in `viewer/src/layers/tracers.js` is written fresh |
| matplotlib viridis colour map | Wind slice colours | CC0 | Control points sampled into `viewer/src/colormap.js` |
| Immersive Web Emulator — https://github.com/meta-quest/immersive-web-emulator | XR testing | MIT | Browser extension only |
| RP-A* paper — https://isprs-archives.copernicus.org/articles/XLIX-B4-2026/453/2026/ | Planner cost design (direction-dependent wind risk) | Open access | Cited in `engine/planner/astar.py` |
| Reynolds 1987, "Flocks, herds and schools" | Separation rule | – | Cited in `engine/swarm/drones.py` |
