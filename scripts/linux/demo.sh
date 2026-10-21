#!/usr/bin/env bash
# Usage: scripts/linux/demo.sh [tier] [scenario]   (default tier: lbmpy on GPU, else synthetic)
source "$(dirname "$0")/_common.sh"
TIER="${1:-}"; SCEN="${2:-scenarios/block_small.json}"; PORT=8080
if [ -z "$TIER" ]; then python -c "from engine import backend; raise SystemExit(0 if backend.is_gpu else 1)" && TIER=lbmpy || TIER=synthetic; fi
info "tier=$TIER scenario=$SCEN"
T0=$(date +%s)
python -m service.server --scenario "$SCEN" --wind "$TIER" --port $PORT > "$RESULTS/service.log" 2>&1 &
PID=$!; trap 'kill $PID 2>/dev/null' EXIT
for i in $(seq 1 120); do curl -sf "http://127.0.0.1:$PORT/api/state" >/dev/null 2>&1 && break; sleep 0.5; done
SECS=$(( $(date +%s) - T0 ))
curl -sf "http://127.0.0.1:$PORT/api/state" >/dev/null && { [ "$SECS" -lt 30 ] && pass "service up in ${SECS}s (<30 s)" || fail "service took ${SECS}s"; } || fail "service did not start ($RESULTS/service.log)"
python tools/demo_check.py --url "ws://127.0.0.1:$PORT/ws" | tee "$RESULTS/demo_check.log" && pass "scripted demo-flow checks" || fail "demo_check"
info "viewer: http://127.0.0.1:$PORT  (WSL2: open it in the Windows browser). Ctrl-C to stop."
[ "${NO_WAIT:-0}" = "1" ] || wait $PID
finish demo
