# Blockers

## B1 — docs/explainer.pdf was not provided (open, needs a human)
The guide refers to `docs/explainer.pdf` (the Phase 1 explainer) for "the 1D worked example" of a BGK collision (P2) and as the simulator's concept source. It is not in the repo. Fallback taken: `tests/validation/test_collision_conservation.py::test_1d_worked_example` reproduces a standard D1Q3 hand-computed example exactly. **To close:** a teammate adds the PDF to `docs/` and replaces/extends that test with the explainer's numbers.

## B2 — Node version
The guide asks for Node 20 LTS; the Mac that built this has Node 26. The viewer builds with both (Vite 5+/6). Use Node 20 on Windows as documented.
