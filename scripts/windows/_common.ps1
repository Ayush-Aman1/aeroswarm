# Shared helpers for the AeroSwarm Windows scripts (dot-source: . "$PSScriptRoot\_common.ps1").
# Conventions: run from anywhere; everything happens at the repo root; every step prints one PASS:/FAIL: line;
# logs go to results\windows\<date>\ ; the script exit code is 1 if any step failed.
$ErrorActionPreference = 'Continue'
$script:Root = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
Set-Location $script:Root
$script:Date = Get-Date -Format 'yyyy-MM-dd'
$script:ResultsDir = Join-Path $script:Root "results\windows\$($script:Date)"
New-Item -ItemType Directory -Force -Path $script:ResultsDir | Out-Null
$script:Failures = 0

function Pass([string]$msg) { Write-Host "PASS: $msg" -ForegroundColor Green }
function Fail([string]$msg) { Write-Host "FAIL: $msg" -ForegroundColor Red; $script:Failures++ }
function Info([string]$msg) { Write-Host "INFO: $msg" -ForegroundColor Cyan }

# Use the aeroswarm conda env for everything below (activated in-process so quoting of `python -c "..."` is plain
# PowerShell, not conda-run quoting). Falls back to whatever `python` is on PATH (e.g. an already activated env).
if (Get-Command conda -ErrorAction SilentlyContinue) {
    (& conda shell.powershell hook) | Out-String | Invoke-Expression
    conda activate aeroswarm 2>$null
}
# Deliberately a plain function (no param block): $args passes -c, -m, -W straight through to python.
function Invoke-Py { & python @args }

function Finish([string]$name) {
    if ($script:Failures -eq 0) { Write-Host "`nRESULT: $name PASS" -ForegroundColor Green; exit 0 }
    else { Write-Host "`nRESULT: $name FAIL ($($script:Failures) step(s) failed) - logs in $($script:ResultsDir)" -ForegroundColor Red; exit 1 }
}
