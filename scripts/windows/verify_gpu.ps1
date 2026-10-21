<#
.SYNOPSIS  Check driver, CUDA toolkit, cupy and the AeroSwarm backend. Prints PASS only when the GPU path can run.
#>
. "$PSScriptRoot\_common.ps1"
$log = Join-Path $ResultsDir 'verify_gpu.log'
Start-Transcript -Path $log -Force | Out-Null

nvidia-smi
if ($LASTEXITCODE -eq 0) { Pass 'nvidia-smi works (driver installed)' } else { Fail 'nvidia-smi failed - install/update the NVIDIA driver' }
$q = nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader 2>$null
if ($q) { Info "GPU: $q" }

nvcc --version
if ($LASTEXITCODE -eq 0) { Pass 'nvcc found (CUDA toolkit installed)' } else { Fail 'nvcc not found - install CUDA Toolkit 12.x and reopen the shell' }

Invoke-Py -c "import cupy; cupy.show_config()"
if ($LASTEXITCODE -eq 0) { Pass 'cupy imports and show_config() runs' } else { Fail 'cupy import failed - install the cupy wheel matching the driver CUDA version' }

Invoke-Py -c "import cupy as cp; x = cp.arange(1000000, dtype=cp.float32); assert abs(float(x.sum()) - 499999500000.0) / 499999500000.0 < 1e-3; print('cupy kernel launch ok')"
if ($LASTEXITCODE -eq 0) { Pass 'cupy launches a CUDA kernel' } else { Fail 'cupy kernel launch failed' }

Invoke-Py -c "from engine import backend; print('backend =', backend.backend_name); raise SystemExit(0 if backend.is_gpu else 1)"
if ($LASTEXITCODE -eq 0) { Pass 'AeroSwarm backend selected cupy (engine/backend.py)' } else { Fail 'AeroSwarm fell back to numpy - see the ERROR lines above' }

Invoke-Py -c "import lbmpy, pystencils; print('lbmpy', lbmpy.__version__, 'pystencils', pystencils.__version__)"
if ($LASTEXITCODE -eq 0) { Pass 'lbmpy + pystencils import (Tier 1 itself must run under WSL2/Ubuntu: scripts/linux/verify_gpu.sh)' } else { Fail 'lbmpy/pystencils import failed' }

# FluidX3D needs an OpenCL device; the NVIDIA driver ships the OpenCL runtime (OpenCL.dll).
if (Test-Path "$env:windir\System32\OpenCL.dll") { Pass 'OpenCL runtime present (System32\OpenCL.dll)' } else { Fail 'OpenCL.dll missing - reinstall the NVIDIA driver (full package)' }

Stop-Transcript | Out-Null
Finish 'verify_gpu'
