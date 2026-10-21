<#
.SYNOPSIS  Run every test marker: CPU path, GPU path, FluidX3D smoke test and the viewer's JS tests.
           A GPU test that is SKIPPED on this machine counts as a FAILURE here (it means cupy/CUDA is not working).
#>
. "$PSScriptRoot\_common.ps1"

function Run-Pytest([string]$label, [string[]]$pyArgs, [bool]$mustNotSkip) {
    $log = Join-Path $ResultsDir "pytest_$label.log"
    Info "pytest $label ..."
    Invoke-Py -W ignore -m pytest @pyArgs -rs 2>&1 | Tee-Object -FilePath $log | Select-Object -Last 8
    $text = Get-Content $log -Raw
    if ($text -match '(\d+) failed') { Fail "pytest $label : $($Matches[1]) test(s) failed (see $log)"; return }
    if ($text -notmatch '(\d+) passed') { Fail "pytest $label : no tests passed (see $log)"; return }
    if ($mustNotSkip -and $text -match '(\d+) skipped') { Fail "pytest $label : $($Matches[1]) skipped on a GPU machine - GPU not usable? (see $log)"; return }
    Pass "pytest $label"
}

$env:AEROSWARM_FORCE_CPU = '1'
Run-Pytest 'cpu' @('-m', 'not gpu and not fluidx3d') $false
Remove-Item Env:\AEROSWARM_FORCE_CPU
# GPU tests that can run on native Windows: the cupy swarm kernel. The lbmpy CUDA tests (CPU-vs-GPU parity, Tier 1) need
# Linux because pystencils 2.0 has no Windows CPU JIT: run scripts/linux/run_tests.sh inside WSL2/Ubuntu for those.
Run-Pytest 'gpu_swarm' @('-m', 'gpu', 'tests/test_p3_swarm.py') $true
Info 'lbmpy GPU tests: run  wsl bash scripts/linux/run_tests.sh  (Tier 1 needs Linux, see HANDOFF_WINDOWS.md)'
Run-Pytest 'fluidx3d' @('-m', 'fluidx3d') $true

Push-Location viewer
npx vitest run 2>&1 | Tee-Object -FilePath (Join-Path $ResultsDir 'vitest.log') | Select-Object -Last 6
if ($LASTEXITCODE -eq 0) { Pass 'viewer vitest' } else { Fail 'viewer vitest' }
Pop-Location

Finish 'run_tests'
