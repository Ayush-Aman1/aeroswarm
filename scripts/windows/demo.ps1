<#
.SYNOPSIS  Start the service with the best available tier, time the start-up (< 30 s), run the scripted demo-flow
           checks, then restart the service on a fresh scene, open the viewer, and stop when you press Enter.
.EXAMPLE   .\demo.ps1                       # best tier: fluidx3d if fields exist, else lbmpy (GPU), else synthetic
           .\demo.ps1 -Tier synthetic -Scenario scenarios\block_small.json
           .\demo.ps1 -Scenario scenarios\stress_1k.json -NoCheck      # 1000 drones, straight to the viewer
           .\demo.ps1 -NoBrowser            # checks only (CI / rehearsal), no viewer, no prompt
           .\demo.ps1 -Cpu                  # force the numpy backend (e.g. to show the CPU/GPU difference live)
.NOTES     The service uses cupy when a CUDA device works (engine/backend.py), else numpy. Measured on an RTX 5070 Ti
           laptop, stress_1k on Tier 2, 600 ticks: cupy median 7.4 ms / p95 13.4 ms per tick, numpy 9.5 / 16.3 ms.
#>
param([string]$Tier = '', [string]$Scenario = 'scenarios\block_small.json', [int]$Port = 8080,
      [switch]$NoBrowser, [switch]$NoCheck, [switch]$Cpu)
. "$PSScriptRoot\_common.ps1"
if ($Cpu) { $env:AEROSWARM_FORCE_CPU = '1'; Info 'backend: numpy (forced with -Cpu)' }
else { Remove-Item Env:\AEROSWARM_FORCE_CPU -ErrorAction SilentlyContinue; Info 'backend: cupy if a CUDA device works, else numpy' }
if (-not $Tier) {
    if (Test-Path 'data\fields\block_small\dir_000\meta.json') { $Tier = 'fluidx3d' }
    else {
        Invoke-Py -c "from engine import backend; raise SystemExit(0 if backend.is_gpu else 1)"
        $Tier = if ($LASTEXITCODE -eq 0) { 'lbmpy' } else { 'synthetic' }
    }
}
Info "tier = $Tier, scenario = $Scenario, python = $Py"
if (-not (Test-Path 'viewer\dist\index.html')) { Fail 'viewer\dist missing: cd viewer; npm ci; npm run build' }

try { $busy = Invoke-RestMethod "http://127.0.0.1:$Port/api/state" -TimeoutSec 1 } catch { $busy = $null }
if ($busy) { Fail "port $Port is already serving AeroSwarm - stop that service first (or pass -Port)"; Finish 'demo' }

$svcLog = Join-Path $ResultsDir 'service.log'

function Start-AeroService([string]$label) {
    # Returns the process if the service answers /api/state within 60 s, else $null. Logs: service[-label].log(.err)
    $log = if ($label) { $svcLog -replace '\.log$', "-$label.log" } else { $svcLog }
    $t0 = Get-Date
    $proc = Start-Process -FilePath $Py -ArgumentList @('-m', 'service.server', '--scenario', $Scenario, '--wind', $Tier, '--port', $Port) `
            -RedirectStandardOutput $log -RedirectStandardError "$log.err" -PassThru -WindowStyle Hidden
    for ($i = 0; $i -lt 120; $i++) {
        Start-Sleep -Milliseconds 500
        try { $r = Invoke-RestMethod "http://127.0.0.1:$Port/api/state" -TimeoutSec 2; if ($r.hello.type -eq 'hello') { break } } catch { }
        if ($proc.HasExited) { break }
    }
    $script:StartSecs = ((Get-Date) - $t0).TotalSeconds
    if ($proc.HasExited -or $i -ge 120) { Fail "service did not start - see $log and $log.err"; return $null }
    return $proc
}

$p = Start-AeroService ''
if ($p) {
    if ($StartSecs -lt 30) { Pass ("service up in {0:N1} s (< 30 s)" -f $StartSecs) } else { Fail ("service up but took {0:N1} s (> 30 s)" -f $StartSecs) }
}

if ($p -and -not $NoCheck) {
    Invoke-Py tools\demo_check.py --url "ws://127.0.0.1:$Port/ws" 2>&1 | Tee-Object -FilePath (Join-Path $ResultsDir 'demo_check.log')
    if ($LASTEXITCODE -eq 0) { Pass 'scripted demo-flow checks (routing toggle, move/reject building, rotate inflow, metrics)' } else { Fail 'scripted demo-flow check failed - see demo_check.log' }
    if (-not $NoBrowser) {
        # The check moved a building and rotated the wind: restart so the audience sees the original scene.
        Stop-Process -Id $p.Id -Force; $p.WaitForExit()
        $p = Start-AeroService 'live'
        if ($p) { Pass 'service restarted on a fresh scene for the live demo' }
    }
}
if ($p -and -not $NoBrowser) {
    Start-Process "http://127.0.0.1:$Port"
    Info "Viewer open at http://127.0.0.1:$Port . Do the manual items of TESTING_CHECKLIST_WINDOWS.md (FPS, XR, screen recording), then press Enter here to stop."
    [void](Read-Host)
}
if ($p -and -not $p.HasExited) { Stop-Process -Id $p.Id -Force }
Finish 'demo'
