#!/usr/bin/env bash
# One-time setup on native Ubuntu 22.04/24.04 or WSL2 Ubuntu with an NVIDIA GPU (CUDA visible via nvidia-smi).
# Tier 1 (lbmpy) needs Linux: pystencils 2.0 has no Windows CPU JIT. WSL2 shares the Windows NVIDIA driver; do NOT install
# a Linux GPU driver inside WSL2. FluidX3D (OpenCL) is NOT available inside WSL2 - build/run it natively on Windows.
source "$(dirname "$0")/_common.sh"
command -v nvidia-smi >/dev/null && pass "nvidia-smi present" || fail "nvidia-smi missing (WSL2: update the Windows NVIDIA driver; Ubuntu: install the driver)"
# Ubuntu 24.04 ships Python 3.12 (no python3.11 package): any python3 >= 3.11 is fine (lbmpy/pystencils 2.0 need >= 3.10).
PY=$(command -v python3.11 || command -v python3 || true)
if ! command -v g++ >/dev/null || [ -z "$PY" ] || ! "$PY" -c 'import ensurepip' 2>/dev/null; then
  info "installing build tools + python venv support (sudo asks for your Linux password)"
  sudo apt-get update -y && sudo apt-get install -y build-essential git ocl-icd-opencl-dev python3 python3-venv python3-dev curl \
    && pass "build tools installed" || fail "apt install failed"
  PY=$(command -v python3.11 || command -v python3)
fi
"$PY" -c 'import sys; raise SystemExit(sys.version_info < (3, 11))' && pass "python $("$PY" --version 2>&1 | cut -d' ' -f2)" \
  || fail "python >= 3.11 needed, found $("$PY" --version 2>&1)"
if ! command -v conda >/dev/null 2>&1; then
  info "no conda: venv in $VENV (Linux filesystem, not the Windows-shared repo)"
  { [ -f "$VENV/bin/activate" ] || "$PY" -m venv "$VENV"; } && source "$VENV/bin/activate" && pass "venv $VENV ready" || fail "venv creation failed"
else
  conda env list | grep -q '^aeroswarm ' || conda create -n aeroswarm python=3.11 -y
  eval "$(conda shell.bash hook)"; conda activate aeroswarm
fi
python -m pip install --upgrade pip && python -m pip install -r requirements.txt && pass "base requirements" || fail "pip install -r requirements.txt"
# cupy wheel matching the driver's CUDA major version; [ctk] pulls the CUDA runtime/NVRTC from pip (WSL2 has no toolkit).
# Not "lbmpy[gpu]": that extra depends on plain `cupy`, which pip would try to build from source.
CUDA_MAJOR=$(nvidia-smi 2>/dev/null | sed -n 's/.*CUDA Version: *\([0-9]*\).*/\1/p' | head -1)
CUPY="cupy-cuda12x"; [ "${CUDA_MAJOR:-12}" -ge 13 ] && CUPY="cupy-cuda13x"
python -m pip install "$CUPY[ctk]" && pass "$CUPY[ctk] (driver CUDA ${CUDA_MAJOR:-?})" || fail "GPU packages ($CUPY[ctk]; check nvidia-smi's CUDA version)"
python -m pip freeze > "$RESULTS/requirements.linux.lock"; info "pip freeze saved to $RESULTS/requirements.linux.lock"
command -v node >/dev/null && pass "node $(node --version)" || info "Node.js 20 not found (only needed to rebuild the viewer; viewer/dist is committed)"
mkdir -p third_party
[ -d third_party/FluidX3D ] || git clone --depth 1 https://github.com/ProjectPhysX/FluidX3D.git third_party/FluidX3D || fail "clone FluidX3D"
finish setup
