#!/usr/bin/env bash
# Shared helpers for the Linux / WSL2 scripts (source this). Same conventions as scripts/windows: PASS:/FAIL: lines,
# logs in results/linux/<date>/, exit code 1 when any step failed.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
DATE="$(date +%F)"
RESULTS="$ROOT/results/linux/$DATE"
mkdir -p "$RESULTS"
FAILURES=0
pass() { printf '\033[32mPASS:\033[0m %s\n' "$*"; }
fail() { printf '\033[31mFAIL:\033[0m %s\n' "$*"; FAILURES=$((FAILURES+1)); }
info() { printf '\033[36mINFO:\033[0m %s\n' "$*"; }
# use the conda env `aeroswarm` if it exists, else the repo's .venv, else whatever python3 is on PATH
if command -v conda >/dev/null 2>&1 && conda env list | grep -q '^aeroswarm '; then
  eval "$(conda shell.bash hook)"; conda activate aeroswarm
elif [ -f "$ROOT/.venv/bin/activate" ]; then
  source "$ROOT/.venv/bin/activate"
fi
finish() {
  if [ "$FAILURES" -eq 0 ]; then printf '\nRESULT: %s PASS\n' "$1"; exit 0
  else printf '\nRESULT: %s FAIL (%s step(s) failed) - logs in %s\n' "$1" "$FAILURES" "$RESULTS"; exit 1; fi
}
