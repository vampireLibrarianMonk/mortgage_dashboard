# Generates deploy/Caddyfile from deploy/apps.json.
# Run this whenever you add or change an app in the registry.
#
#   powershell -ExecutionPolicy Bypass -File deploy\generate-caddyfile.ps1
#
# The generated Caddyfile makes Caddy listen on the configured HTTP port (80)
# and reverse-proxy each app's hostname to its loopback high port.

$ErrorActionPreference = "Stop"

$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$registryPath = Join-Path $here "apps.json"
$caddyfilePath = Join-Path $here "Caddyfile"

if (-not (Test-Path $registryPath)) {
    throw "Registry not found: $registryPath"
}

$registry = Get-Content $registryPath -Raw | ConvertFrom-Json
$httpPort = $registry.proxy.http_port
if (-not $httpPort) { $httpPort = 80 }

$lines = @()
$lines += "# AUTO-GENERATED from deploy/apps.json by generate-caddyfile.ps1."
$lines += "# Do not edit by hand; edit apps.json and re-run the generator."
$lines += ""
$lines += "{"
$lines += "`tadmin off"
$lines += "}"
$lines += ""

foreach ($app in $registry.apps) {
    $hostname = $app.hostname
    $port = $app.port
    $lines += "http://${hostname}:${httpPort} {"
    $lines += "`treverse_proxy 127.0.0.1:${port}"
    $lines += "}"
    $lines += ""
}

Set-Content -Path $caddyfilePath -Value ($lines -join "`n") -Encoding UTF8
Write-Host "Wrote $caddyfilePath ($($registry.apps.Count) app(s))."
