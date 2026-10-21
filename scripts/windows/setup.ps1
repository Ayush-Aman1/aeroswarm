<#
.SYNOPSIS  One-time setup on the NVIDIA Windows laptop: conda env `aeroswarm`, GPU packages, viewer deps, reference repos.
.NOTES     Prerequisites (install by hand first, see HANDOFF_WINDOWS.md section 1): NVIDIA driver, CUDA 12.x toolkit,
           Visual Studio 2022 "Desktop development with C++", Miniconda, Git (+ Git LFS), Node.js 20 LTS.
           Usage:  powershell -ExecutionPolicy Bypass -File scripts\windows\setup.ps1 [-SkipThirdParty]
#>
param([switch]$SkipThirdParty)
. "$PSScriptRoot\_common.ps1"
$log = Join-Path $ResultsDir 'setup.log'
Start-Transcript -Path $log -Force | Out-Null

# --- prerequisites
foreach ($t in @(@('git', 'Git'), @('conda', 'Miniconda (add to PATH or run from an Anaconda Prompt)'), @('node', 'Node.js 20 LTS'),
                 @('npm', 'npm'), @('nvidia-smi', 'NVIDIA driver'))) {
    if (Get-Command $t[0] -ErrorAction SilentlyContinue) { Pass "$($t[1]) found" } else { Fail "$($t[1]) not found on PATH" }
}
if (Get-Command node -ErrorAction SilentlyContinue) {
    $major = [int]((node --version).TrimStart('v').Split('.')[0])
    if ($major -ge 20) { Pass "Node $(node --version) (guide wants 20 LTS)" } else { Fail "Node $(node --version) is older than 20" }
}
if (Get-Command git -ErrorAction SilentlyContinue) {
    git lfs version *> $null
    if ($LASTEXITCODE -eq 0) { Pass 'Git LFS installed' } else { Fail 'Git LFS missing (git lfs install)' }
}
$vswhere = "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe"
if (Test-Path $vswhere) {
    $vs = & $vswhere -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
    if ($vs) { Pass "Visual Studio C++ tools: $vs" } else { Fail 'Visual Studio 2022 "Desktop development with C++" workload missing' }
} else { Fail 'Visual Studio 2022 not found (needed to build FluidX3D)' }
if ($script:Failures -gt 0) { Stop-Transcript | Out-Null; Finish 'setup (prerequisites)' }

# --- conda env
$envs = conda env list
if ($envs -match '^\s*aeroswarm\s') { Pass 'conda env aeroswarm exists' }
else {
    conda create -n aeroswarm python=3.11 -y
    if ($LASTEXITCODE -eq 0) { Pass 'created conda env aeroswarm (Python 3.11)' } else { Fail 'conda create failed' }
}
conda run -n aeroswarm --no-capture-output python -m pip install --upgrade pip
conda run -n aeroswarm --no-capture-output python -m pip install -r requirements.txt
if ($LASTEXITCODE -eq 0) { Pass 'base requirements installed' } else { Fail 'pip install -r requirements.txt failed' }
conda run -n aeroswarm --no-capture-output python -m pip install cupy-cuda12x "lbmpy[gpu]"
if ($LASTEXITCODE -eq 0) { Pass 'cupy-cuda12x and lbmpy[gpu] installed' } else { Fail 'GPU packages failed (check CUDA version vs cupy wheel, see Troubleshooting)' }
# Freeze exactly what works so nobody drifts onto another lbmpy / cupy API (commit requirements.windows.lock afterwards).
conda run -n aeroswarm --no-capture-output python -m pip freeze | Out-File -Encoding ascii (Join-Path $ResultsDir 'requirements.windows.lock')
Info "pip freeze saved to $ResultsDir\requirements.windows.lock"

# --- viewer
Push-Location viewer
npm ci
if ($LASTEXITCODE -eq 0) { Pass 'viewer dependencies installed (npm ci)' } else { Fail 'npm ci failed' }
npm run build
if ($LASTEXITCODE -eq 0) { Pass 'viewer built (viewer\dist)' } else { Fail 'npm run build failed' }
Pop-Location

# --- third_party reference repos (read-only, gitignored)
if (-not $SkipThirdParty) {
    New-Item -ItemType Directory -Force -Path third_party | Out-Null
    $repos = @('ProjectPhysX/FluidX3D', 'pmocz/latticeboltzmann-python', 'akdemironur/cuda_d2q9_flow_over_cylinder',
               'arch85-km/urban-wind-lab', 'NVIDIA/cuda-samples', 'LinDadaism/GPU-CUDA-Flocking', 'mapbox/webgl-wind')
    foreach ($r in $repos) {
        $name = $r.Split('/')[1]
        if (Test-Path "third_party\$name") { Info "third_party\$name already present"; continue }
        git clone --depth 1 "https://github.com/$r.git" "third_party\$name"
        if ($LASTEXITCODE -eq 0) { Pass "cloned $r" } else { Fail "clone of $r failed (only FluidX3D is required)" }
    }
}
Stop-Transcript | Out-Null
Info 'Next: scripts\windows\verify_gpu.ps1'
Finish 'setup'
