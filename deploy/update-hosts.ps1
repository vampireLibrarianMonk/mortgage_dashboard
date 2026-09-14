# Adds/updates the app.* hostname entries in the Windows hosts file from apps.json.
# REQUIRES AN ELEVATED (Administrator) PowerShell prompt.
#
#   powershell -ExecutionPolicy Bypass -File deploy\update-hosts.ps1
#   powershell -ExecutionPolicy Bypass -File deploy\update-hosts.ps1 -Remove
#
# Entries are wrapped in a managed block so re-running is idempotent and the
# block can be cleanly removed with -Remove without touching your other hosts.

param(
    [switch]$Remove
)

$ErrorActionPreference = "Stop"

# --- Require admin ---
$isAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()
    ).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    throw "This script must be run from an elevated (Administrator) PowerShell prompt to edit the hosts file."
}

$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$registryPath = Join-Path $here "apps.json"
$hostsPath = Join-Path $env:SystemRoot "System32\drivers\etc\hosts"

$BEGIN = "# BEGIN mortgage_dashboard local-apps (managed)"
$END = "# END mortgage_dashboard local-apps (managed)"

$registry = Get-Content $registryPath -Raw | ConvertFrom-Json

# Read current hosts and strip any existing managed block.
$content = if (Test-Path $hostsPath) { Get-Content $hostsPath -Raw } else { "" }
$pattern = "(?ms)\r?\n?" + [regex]::Escape($BEGIN) + ".*?" + [regex]::Escape($END) + "\r?\n?"
$content = [regex]::Replace($content, $pattern, "`n")
$content = $content.TrimEnd() + "`n"

if (-not $Remove) {
    $block = @($BEGIN)
    foreach ($app in $registry.apps) {
        $block += "127.0.0.1`t$($app.hostname)"
    }
    $block += $END
    $content = $content + ($block -join "`n") + "`n"
}

Set-Content -Path $hostsPath -Value $content -Encoding ASCII

if ($Remove) {
    Write-Host "Removed managed hosts block."
} else {
    Write-Host "Updated hosts file with $($registry.apps.Count) entrie(s):"
    foreach ($app in $registry.apps) { Write-Host "  127.0.0.1  $($app.hostname)" }
}
