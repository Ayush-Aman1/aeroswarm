#!/usr/bin/env bash
source "$(dirname "$0")/_common.sh"
nvidia-smi && pass "nvidia-smi works" || fail "nvidia-smi failed"
python -c "import cupy; cupy.show_config()" && pass "cupy imports" || fail "cupy import failed (wheel vs CUDA driver version)"
python -c "import cupy as cp; x=cp.arange(1000000,dtype=cp.float32); assert abs(float(x.sum())-499999500000.0)/499999500000.0<1e-3" && pass "cupy launches a CUDA kernel" || fail "cupy kernel launch failed"
python -c "from engine import backend; print('backend =', backend.backend_name); raise SystemExit(0 if backend.is_gpu else 1)" && pass "AeroSwarm backend = cupy" || fail "AeroSwarm fell back to numpy"
python -c "from engine.wind.lbmpy_solver import LbmpySolver as L; r=L.unavailable_reason(); print(r or 'ok'); raise SystemExit(1 if r else 0)" && pass "Tier 1 (lbmpy) can run here" || fail "Tier 1 unavailable (see reason above)"
finish verify_gpu
