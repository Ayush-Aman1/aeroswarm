<#
.SYNOPSIS  All benchmarks and experiments, written to results\windows\<date>\ :
           lbmpy MLUPS (64^3, 128^3, 256x128x128) with % of the bandwidth ceiling, FluidX3D benchmark mode,
           swarm step time vs N (CPU vs GPU, naive vs grid) and naive-vs-aware experiments on every tier.
#>
param([switch]$SkipExperiments)
. "$PSScriptRoot\_common.ps1"
$out = Join-Path $ResultsDir 'bench'
New-Item -ItemType Directory -Force -Path $out | Out-Null

# lbmpy (Tier 1) MLUPS needs Linux (pystencils 2.0 has no Windows CPU JIT): run  wsl bash scripts/linux/bench.sh
Info 'lbmpy MLUPS + Tier 1 experiments: run  wsl bash scripts/linux/bench.sh  (results land in results/linux/<date>)'

Invoke-Py -W ignore -m bench.fluidx3d_bench --out $out 2>&1 | Tee-Object -FilePath (Join-Path $out 'mlups_fluidx3d.log')
if ($LASTEXITCODE -eq 0) { Pass 'FluidX3D benchmark mode' } else { Fail 'FluidX3D benchmark failed (build it first: build_fluidx3d.ps1)' }

Invoke-Py -W ignore -m bench.swarm_bench --out $out 2>&1 | Tee-Object -FilePath (Join-Path $out 'swarm_gpu.log')
if ($LASTEXITCODE -eq 0) { Pass 'swarm step time vs N (GPU backend, grid vs naive)' } else { Fail 'swarm benchmark failed' }
$env:AEROSWARM_FORCE_CPU = '1'
Invoke-Py -W ignore -m bench.swarm_bench --out (Join-Path $out 'cpu') 2>&1 | Tee-Object -FilePath (Join-Path $out 'swarm_cpu.log')
if ($LASTEXITCODE -eq 0) { Pass 'swarm step time vs N (CPU backend)' } else { Fail 'CPU swarm benchmark failed' }
Remove-Item Env:\AEROSWARM_FORCE_CPU

if (-not $SkipExperiments) {
    Invoke-Py -W ignore -m experiments.run_experiments --tiers synthetic fluidx3d lbmpy --out (Join-Path $ResultsDir 'experiments') 2>&1 |
        Tee-Object -FilePath (Join-Path $ResultsDir 'experiments.log') | Select-Object -Last 8
    if ($LASTEXITCODE -eq 0) { Pass 'naive vs aware experiments (5 seeds x 3 layouts x available tiers)' } else { Fail 'experiments failed' }
}
Info "results in $ResultsDir  - copy the tables and plots into your report; label each with its wind tier."
Finish 'bench'
