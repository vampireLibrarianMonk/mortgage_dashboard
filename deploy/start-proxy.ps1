# Starts the Caddy reverse proxy using the generated Caddyfile.
# Caddy listens on :80 and routes each app.<name> hostname to its high port.
#
#   powershell -ExecutionPolicy Bypass -File deploy\start-proxy.ps1
#
# Caddy resolution order:
#   1. deploy\caddy.exe (drop the binary here for a self-contained setup)
#   2. caddy on the system PATH
#
# Binding to :80 requires the process to have permission; the Task Scheduler
# boot task runs as SYSTEM, which satisfies this. For manual runs, use an
# elevated prompt if you hit an access error.

$ErrorActionPreference = "Stop"

$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$caddyfile = Join-Path $here "Caddyfile"

if (-not (Test-Path $caddyfile)) {
    throw "Caddyfile not found. Run deploy\generate-caddyfile.ps1 first."
}

$localCaddy = Join-Path $here "caddy.exe"
if (Test-Path $localCaddy) {
    $caddy = $localCaddy
} else {
    $onPath = Get-Command caddy -ErrorAction SilentlyContinue
    if ($onPath) {
        $caddy = $onPath.Source
    } else {
        throw "Caddy not found. Place caddy.exe in deploy\ or install it on PATH (e.g. 'winget install CaddyServer.Caddy')."
    }
}

Write-Host "Starting Caddy ($caddy) with $caddyfile ..."
& $caddy run --config $caddyfile --adapter caddyfile
