#!/usr/bin/env bash
# Tier 1 + swarm benchmarks and the experiments on this machine (CUDA via cupy). FluidX3D's own benchmark runs on Windows.
source "$(dirname "$0")/_common.sh"
OUT="$RESULTS/bench"; mkdir -p "$OUT"
python -W ignore -m bench.mlups --out "$OUT" 2>&1 | tee "$OUT/mlups_lbmpy.log" && pass "lbmpy MLUPS table" || fail "lbmpy MLUPS"
python -W ignore -m bench.swarm_bench --out "$OUT" 2>&1 | tee "$OUT/swarm_gpu.log" && pass "swarm step time (GPU)" || fail "swarm bench GPU"
AEROSWARM_FORCE_CPU=1 python -W ignore -m bench.swarm_bench --out "$OUT/cpu" 2>&1 | tee "$OUT/swarm_cpu.log" && pass "swarm step time (CPU)" || fail "swarm bench CPU"
if [ "${1:-}" != "--skip-experiments" ]; then
  python -W ignore -m experiments.run_experiments --tiers synthetic fluidx3d lbmpy --out "$RESULTS/experiments" 2>&1 | tail -6 && pass "experiments" || fail "experiments"
fi
finish bench
