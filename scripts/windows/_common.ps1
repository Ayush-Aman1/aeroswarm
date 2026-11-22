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

# Pick the Python interpreter, first match wins:
#   1. $env:AEROSWARM_PYTHON (full path to python.exe)
#   2. a venv at the repo root: .venv\Scripts\python.exe  (README quick start; may be a junction to a venv elsewhere)
#   3. the aeroswarm conda env (activated in-process so quoting of `python -c "..."` is plain PowerShell)
#   4. whatever `python` is on PATH (e.g. an already activated env)
$script:Py = $null
if ($env:AEROSWARM_PYTHON -and (Test-Path $env:AEROSWARM_PYTHON)) { $script:Py = $env:AEROSWARM_PYTHON }
elseif (Test-Path (Join-Path $script:Root '.venv\Scripts\python.exe')) { $script:Py = Join-Path $script:Root '.venv\Scripts\python.exe' }
elseif (Get-Command conda -ErrorAction SilentlyContinue) {
    (& conda shell.powershell hook) | Out-String | Invoke-Expression
    conda activate aeroswarm 2>$null
}
if (-not $script:Py) { $c = Get-Command python -ErrorAction SilentlyContinue; if ($c) { $script:Py = $c.Source } }
if (-not $script:Py) { Write-Host 'FAIL: no Python found (create .venv, set AEROSWARM_PYTHON, or install the conda env)' -ForegroundColor Red; exit 1 }
# Deliberately a plain function (no param block): $args passes -c, -m, -W straight through to python.
function Invoke-Py { & $script:Py @args }

function Finish([string]$name) {
    if ($script:Failures -eq 0) { Write-Host "`nRESULT: $name PASS" -ForegroundColor Green; exit 0 }
    else { Write-Host "`nRESULT: $name FAIL ($($script:Failures) step(s) failed) - logs in $($script:ResultsDir)" -ForegroundColor Red; exit 1 }
}
