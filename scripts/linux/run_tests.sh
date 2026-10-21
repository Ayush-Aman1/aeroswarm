#!/usr/bin/env bash
# CPU path, GPU path (incl. lbmpy CUDA vs CPU parity, cupy RawKernel), viewer JS tests.
source "$(dirname "$0")/_common.sh"
run() { local label="$1"; shift; python -W ignore -m pytest "$@" -rs 2>&1 | tee "$RESULTS/pytest_$label.log" | tail -8
  if grep -qE '[0-9]+ failed' "$RESULTS/pytest_$label.log"; then fail "pytest $label (see log)"
  elif ! grep -qE '[0-9]+ passed' "$RESULTS/pytest_$label.log"; then fail "pytest $label: nothing passed"
  else pass "pytest $label"; fi; }
AEROSWARM_FORCE_CPU=1 run cpu -m "not gpu and not fluidx3d"
run gpu -m gpu
if grep -qE '[0-9]+ skipped' "$RESULTS/pytest_gpu.log"; then fail "GPU tests were SKIPPED - the GPU path is not working (see log)"; fi
[ -d viewer/node_modules ] && (cd viewer && npx vitest run 2>&1 | tail -5 && pass "viewer vitest") || info "viewer/node_modules missing: npm ci to run the JS tests"
finish run_tests
