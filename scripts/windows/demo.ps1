<#
.SYNOPSIS  Start the service with the best available tier, time the start-up (< 30 s), run the scripted demo-flow
           checks, open the viewer, and stop the service when you press Enter.
.EXAMPLE   .\demo.ps1                       # best tier: fluidx3d if fields exist, else lbmpy (GPU), else synthetic
           .\demo.ps1 -Tier synthetic -Scenario scenarios\block_small.json
#>
param([string]$Tier = '', [string]$Scenario = 'scenarios\block_small.json', [int]$Port = 8080, [switch]$NoBrowser)
. "$PSScriptRoot\_common.ps1"
if (-not $Tier) {
    if (Test-Path 'data\fields\block_small\dir_000\meta.json') { $Tier = 'fluidx3d' }
    else {
        Invoke-Py -c "from engine import backend; raise SystemExit(0 if backend.is_gpu else 1)"
        $Tier = if ($LASTEXITCODE -eq 0) { 'lbmpy' } else { 'synthetic' }
    }
}
Info "tier = $Tier, scenario = $Scenario"
if (-not (Test-Path 'viewer\dist\index.html')) { Fail 'viewer\dist missing: cd viewer; npm ci; npm run build' }

$py = (Get-Command python).Source
$svcLog = Join-Path $ResultsDir 'service.log'
$t0 = Get-Date
$p = Start-Process -FilePath $py -ArgumentList @('-m', 'service.server', '--scenario', $Scenario, '--wind', $Tier, '--port', $Port) `
        -RedirectStandardOutput $svcLog -RedirectStandardError "$svcLog.err" -PassThru -WindowStyle Hidden
$ready = $false
for ($i = 0; $i -lt 120; $i++) {
    Start-Sleep -Milliseconds 500
    try { $r = Invoke-RestMethod "http://127.0.0.1:$Port/api/state" -TimeoutSec 2; if ($r.hello.type -eq 'hello') { $ready = $true; break } } catch { }
    if ($p.HasExited) { break }
}
$secs = ((Get-Date) - $t0).TotalSeconds
if ($ready -and $secs -lt 30) { Pass ("service up in {0:N1} s (< 30 s)" -f $secs) }
elseif ($ready) { Fail ("service up but took {0:N1} s (> 30 s)" -f $secs) }
else { Fail "service did not start - see $svcLog and $svcLog.err" }

if ($ready) {
    Invoke-Py tools\demo_check.py --url "ws://127.0.0.1:$Port/ws" 2>&1 | Tee-Object -FilePath (Join-Path $ResultsDir 'demo_check.log')
    if ($LASTEXITCODE -eq 0) { Pass 'scripted demo-flow checks (routing toggle, move/reject building, rotate inflow, metrics)' } else { Fail 'scripted demo-flow check failed - see demo_check.log' }
    if (-not $NoBrowser) {
        Start-Process "http://127.0.0.1:$Port"
        Info 'Viewer open. Now do the manual items of TESTING_CHECKLIST_WINDOWS.md (FPS, XR, screen recording), then press Enter here to stop.'
        [void](Read-Host)
    }
}
if ($p -and -not $p.HasExited) { Stop-Process -Id $p.Id -Force }
Finish 'demo'
