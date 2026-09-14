# Registers (or removes) Windows Task Scheduler tasks that start the apps and the
# Caddy reverse proxy at boot, BEFORE any user logs in.
# REQUIRES AN ELEVATED (Administrator) PowerShell prompt.
#
#   powershell -ExecutionPolicy Bypass -File deploy\register-startup.ps1
#   powershell -ExecutionPolicy Bypass -File deploy\register-startup.ps1 -Remove
#
# Two tasks are created, both triggered "At startup" and run as SYSTEM:
#   MortgageDashboard-Apps   -> deploy\start-apps.ps1  (launches uvicorn on 9001)
#   MortgageDashboard-Proxy  -> deploy\start-proxy.ps1 (Caddy on :80)
# Running as SYSTEM lets Caddy bind :80 and lets everything come up pre-login.

param(
    [switch]$Remove
)

$ErrorActionPreference = "Stop"

$isAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()
    ).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    throw "This script must be run from an elevated (Administrator) PowerShell prompt to register scheduled tasks."
}

$here = Split-Path -Parent $MyInvocation.MyCommand.Path

$appsTask = "MortgageDashboard-Apps"
$proxyTask = "MortgageDashboard-Proxy"

if ($Remove) {
    foreach ($name in @($appsTask, $proxyTask)) {
        if (Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue) {
            Unregister-ScheduledTask -TaskName $name -Confirm:$false
            Write-Host "Removed task: $name"
        }
    }
    return
}

function Register-BootTask($name, $scriptPath) {
    $psExe = "powershell.exe"
    $args = "-NoProfile -ExecutionPolicy Bypass -File `"$scriptPath`""
    $action = New-ScheduledTaskAction -Execute $psExe -Argument $args
    $trigger = New-ScheduledTaskTrigger -AtStartup
    $principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)

    if (Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $name -Confirm:$false
    }
    Register-ScheduledTask -TaskName $name -Action $action -Trigger $trigger -Principal $principal -Settings $settings | Out-Null
    Write-Host "Registered task: $name -> $scriptPath"
}

Register-BootTask $appsTask (Join-Path $here "start-apps.ps1")
Register-BootTask $proxyTask (Join-Path $here "start-proxy.ps1")

Write-Host ""
Write-Host "Done. Tasks will run at next boot. To start now without rebooting:"
Write-Host "  Start-ScheduledTask -TaskName $appsTask"
Write-Host "  Start-ScheduledTask -TaskName $proxyTask"
