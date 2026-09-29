# Health check + self-heal for the mortgage dashboard.
#
# Verifies the app (uvicorn on its high port) and the Caddy proxy (:80) are up,
# and relaunches whichever is down using the existing start-apps.ps1 /
# start-proxy.ps1 launchers. Idempotent: if everything is healthy it does
# nothing, so it is safe to run on a schedule (e.g. every few minutes) and at
# boot.
#
#   powershell -ExecutionPolicy Bypass -File deploy\health-check.ps1
#   powershell -ExecutionPolicy Bypass -File deploy\health-check.ps1 -Verbose
#   powershell -ExecutionPolicy Bypass -File deploy\health-check.ps1 -AppsOnly
#
# Notes:
# - RUN THIS AS THE SAME USER THE APP RUNS AS. The app reads Plaid credentials +
#   each bank's access token from that user's Windows Credential Manager vault, so
#   relaunching it in a different context (e.g. SYSTEM) would start a *sandbox*
#   instance with no banks. The scheduled MortgageDashboard-HealthCheck task is
#   registered to run as the app user and passes -AppsOnly for exactly this reason.
# - -AppsOnly skips the proxy check/relaunch. The proxy (Caddy on :80) has its own
#   SYSTEM boot task + restart-on-failure; a user-context health check normally
#   cannot rebind :80 anyway, so it stays out of the proxy's lane.
# - Without -AppsOnly, the proxy relaunch only fires when running elevated/SYSTEM;
#   otherwise it just logs a warning (not a hard failure).
# - Reads apps.json for each app's port + health_path, so it covers every app,
#   not just the mortgage dashboard.

param(
    [switch]$AppsOnly,   # skip the proxy check (e.g. when run non-elevated)
    [int]$TimeoutSec = 5
)

$ErrorActionPreference = "Stop"

$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$logDir = Join-Path $here "logs"
$logFile = Join-Path $logDir "health-check.log"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

function Write-Log([string]$msg) {
    $line = "{0}  {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $msg
    Add-Content -Path $logFile -Value $line
    Write-Verbose $line
}

# --- Load the app registry ----------------------------------------------------
$registry = Get-Content (Join-Path $here "apps.json") -Raw | ConvertFrom-Json
$proxyPort = 80
if ($registry.proxy -and $registry.proxy.http_port) { $proxyPort = [int]$registry.proxy.http_port }

# --- Helpers ------------------------------------------------------------------

# True if something is listening on the given local TCP port.
function Test-PortListening([int]$port) {
    $null -ne (Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue |
        Select-Object -First 1)
}

# True if the app answers HTTP 200 at its health path (or root when none).
function Test-AppHealthy($app) {
    $path = if ($app.health_path) { $app.health_path } else { "/" }
    $url = "http://127.0.0.1:$($app.port)$path"
    try {
        $resp = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec $TimeoutSec
        return ($resp.StatusCode -eq 200)
    } catch {
        return $false
    }
}

# Launch a helper script detached so this script returns promptly. The launched
# process inherits SYSTEM when we run under the scheduled task, which is what
# lets Caddy bind :80 and lets start-apps.ps1 read the machine-scope creds.
function Start-Detached([string]$scriptName) {
    $script = Join-Path $here $scriptName
    Start-Process -FilePath "powershell.exe" `
        -ArgumentList "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "`"$script`"" `
        -WindowStyle Hidden
}

# --- App check + recover ------------------------------------------------------
$anyAppDown = $false
foreach ($app in $registry.apps) {
    $listening = Test-PortListening $app.port
    $healthy = if ($listening) { Test-AppHealthy $app } else { $false }
    if ($healthy) {
        Write-Log "OK    app '$($app.name)' healthy on :$($app.port)"
    } else {
        $state = if ($listening) { "listening but unhealthy" } else { "not listening" }
        Write-Log "DOWN  app '$($app.name)' $state on :$($app.port) - relaunching"
        $anyAppDown = $true
    }
}
if ($anyAppDown) {
    Write-Log "ACTION starting apps via start-apps.ps1"
    Start-Detached "start-apps.ps1"
}

# --- Proxy check + recover ----------------------------------------------------
if (-not $AppsOnly) {
    if (Test-PortListening $proxyPort) {
        Write-Log "OK    proxy (Caddy) listening on :$proxyPort"
    } else {
        Write-Log "DOWN  proxy (Caddy) not listening on :$proxyPort - relaunching"
        $isAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()
            ).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
        $isSystem = ([Security.Principal.WindowsIdentity]::GetCurrent()).IsSystem
        if ($isAdmin -or $isSystem) {
            Write-Log "ACTION starting proxy via start-proxy.ps1"
            Start-Detached "start-proxy.ps1"
        } else {
            Write-Log "WARN  proxy is down but this session is not elevated; binding :$proxyPort needs admin/SYSTEM. Run elevated or rely on the scheduled task (runs as SYSTEM)."
        }
    }
}

# Give a freshly-launched app a moment, then report a one-line status for the
# common (mortgage) app so an interactive run shows the outcome.
if ($anyAppDown) { Start-Sleep -Seconds 3 }
$primary = $registry.apps | Select-Object -First 1
if ($primary) {
    $ok = Test-AppHealthy $primary
    $summary = if ($ok) { "healthy" } else { "still not healthy (check $logFile / Task Scheduler)" }
    Write-Log "SUMMARY primary app '$($primary.name)': $summary"
    Write-Host "mortgage dashboard ($($primary.name)) on :$($primary.port): $summary"
}
