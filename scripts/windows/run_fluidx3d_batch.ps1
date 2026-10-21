<#
.SYNOPSIS  Tier 2: the three layout presets (block_small, street_canyon, tower_cluster) x 8 wind directions -> data\fields\<preset>\dir_XXX\*.npy
           (float16, 2 m grid, SI, 16 frames; the whole set stays under 3 GB). Resumable: finished jobs are skipped.
.EXAMPLE   .\run_fluidx3d_batch.ps1                         # the full set (about 2-3 h on an RTX 3060)
           .\run_fluidx3d_batch.ps1 -Quick                  # block_small x {0,90} only
#>
param([switch]$Quick, [switch]$DryRun)
. "$PSScriptRoot\_common.ps1"
$log = Join-Path $ResultsDir 'fluidx3d_batch.log'
$args2 = @('-m', 'tools.fluidx3d.batch')
if ($Quick) { $args2 += @('--scenarios', 'scenarios\block_small.json', '--directions', '0', '90') }
if ($DryRun) { $args2 += '--dry-run' }
Invoke-Py @args2 2>&1 | Tee-Object -FilePath $log | Select-Object -Last 12
if ($LASTEXITCODE -eq 0) { Pass 'FluidX3D batch finished' } else { Fail "FluidX3D batch reported failures - see $log" }
if (-not $DryRun -and (Test-Path 'data\fields')) {
    $gb = ((Get-ChildItem data\fields -Recurse -Filter *.npy | Measure-Object Length -Sum).Sum) / 1e9
    if ($gb -lt 3) { Pass ("fields on disk: {0:N2} GB (< 3 GB)" -f $gb) } else { Fail ("fields on disk: {0:N2} GB exceeds the 3 GB budget" -f $gb) }
}
Finish 'run_fluidx3d_batch'
