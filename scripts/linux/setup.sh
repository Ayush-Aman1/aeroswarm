#!/usr/bin/env bash
# One-time setup on native Ubuntu 22.04/24.04 or WSL2 Ubuntu with an NVIDIA GPU (CUDA visible via nvidia-smi).
# Tier 1 (lbmpy) needs Linux: pystencils 2.0 has no Windows CPU JIT. WSL2 shares the Windows NVIDIA driver; do NOT install
# a Linux GPU driver inside WSL2. FluidX3D (OpenCL) is NOT available inside WSL2 - build/run it natively on Windows.
source "$(dirname "$0")/_common.sh"
command -v nvidia-smi >/dev/null && pass "nvidia-smi present" || fail "nvidia-smi missing (WSL2: update the Windows NVIDIA driver; Ubuntu: install the driver)"
command -v g++ >/dev/null && pass "g++ present" || { info "installing build tools"; sudo apt-get update -y && sudo apt-get install -y build-essential git ocl-icd-opencl-dev python3.11 python3.11-venv curl && pass "build-essential installed" || fail "apt install failed"; }
if ! command -v conda >/dev/null 2>&1; then
  info "no conda: using python3.11 venv in .venv"
  python3.11 -m venv .venv && source .venv/bin/activate && pass "venv .venv created" || fail "venv creation failed"
else
  conda env list | grep -q '^aeroswarm ' || conda create -n aeroswarm python=3.11 -y
  eval "$(conda shell.bash hook)"; conda activate aeroswarm
fi
python -m pip install --upgrade pip && python -m pip install -r requirements.txt && pass "base requirements" || fail "pip install -r requirements.txt"
python -m pip install cupy-cuda12x "lbmpy[gpu]" && pass "cupy-cuda12x + lbmpy[gpu]" || fail "GPU packages (check the CUDA version vs the cupy wheel)"
python -m pip freeze > "$RESULTS/requirements.linux.lock"; info "pip freeze saved to $RESULTS/requirements.linux.lock"
command -v node >/dev/null && pass "node $(node --version)" || info "Node.js 20 not found (only needed to rebuild the viewer; viewer/dist is committed)"
mkdir -p third_party
[ -d third_party/FluidX3D ] || git clone --depth 1 https://github.com/ProjectPhysX/FluidX3D.git third_party/FluidX3D || fail "clone FluidX3D"
finish setup
