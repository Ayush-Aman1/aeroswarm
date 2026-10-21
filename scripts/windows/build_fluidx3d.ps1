<#
.SYNOPSIS  Build FluidX3D (a patched COPY: third_party\FluidX3D_aeroswarm) with MSBuild and run the one-job smoke test.
           FluidX3D's own files are not modified; see tools\fluidx3d\README.md.
#>
. "$PSScriptRoot\_common.ps1"
$log = Join-Path $ResultsDir 'build_fluidx3d.log'
if (-not (Test-Path 'third_party\FluidX3D\src\lbm.cpp')) { Fail 'third_party\FluidX3D missing (run setup.ps1)'; Finish 'build_fluidx3d' }
Invoke-Py -m tools.fluidx3d.batch --build-only 2>&1 | Tee-Object -FilePath $log | Select-Object -Last 5
if ($LASTEXITCODE -eq 0 -and (Test-Path 'third_party\FluidX3D_aeroswarm\bin\FluidX3D.exe')) { Pass 'FluidX3D built: third_party\FluidX3D_aeroswarm\bin\FluidX3D.exe' }
else { Fail "FluidX3D build failed - see $log and third_party\FluidX3D_aeroswarm\build.log" ; Finish 'build_fluidx3d' }
Invoke-Py -W ignore -m pytest -m fluidx3d -rs 2>&1 | Tee-Object -FilePath (Join-Path $ResultsDir 'fluidx3d_smoke.log') | Select-Object -Last 6
if ($LASTEXITCODE -eq 0 -and (Get-Content (Join-Path $ResultsDir 'fluidx3d_smoke.log') -Raw) -match '1 passed') { Pass 'FluidX3D smoke job ran and converted to .npy' }
else { Fail 'FluidX3D smoke job failed or was skipped (is an OpenCL device visible? run verify_gpu.ps1)' }
Finish 'build_fluidx3d'
