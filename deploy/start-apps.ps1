# Starts every app defined in apps.json (each on its own high port).
# Used both for manual startup and by the Task Scheduler boot task.
#
#   powershell -ExecutionPolicy Bypass -File deploy\start-apps.ps1
#
# Each app is launched as a background process from its working_dir. If a
# health_path is set, we poll it and report readiness.

$ErrorActionPreference = "Stop"

$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$repo = Split-Path -Parent $here
$registry = Get-Content (Join-Path $here "apps.json") -Raw | ConvertFrom-Json

foreach ($app in $registry.apps) {
    $workingDir = Join-Path $repo $app.working_dir
    Write-Host "Starting $($app.name) on port $($app.port)..."

    # Split the start command into executable + argument string.
    $cmd = $app.start_command
    $exe, $argline = $cmd -split ' ', 2

    Start-Process -FilePath $exe -ArgumentList $argline -WorkingDirectory $workingDir -WindowStyle Hidden

    if ($app.health_path) {
        $url = "http://127.0.0.1:$($app.port)$($app.health_path)"
        $ready = $false
        for ($i = 0; $i -lt 30; $i++) {
            Start-Sleep -Milliseconds 500
            try {
                $resp = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 2
                if ($resp.StatusCode -eq 200) { $ready = $true; break }
            } catch { }
        }
        if ($ready) {
            Write-Host "  $($app.name) is healthy at $url"
        } else {
            Write-Warning "  $($app.name) did not become healthy at $url within timeout"
        }
    }
}

Write-Host "All apps launched."
