# Registers (or removes) Windows Task Scheduler tasks that start the app and the
# Caddy reverse proxy. REQUIRES AN ELEVATED (Administrator) PowerShell prompt.
#
#   powershell -ExecutionPolicy Bypass -File deploy\register-startup.ps1
#   powershell -ExecutionPolicy Bypass -File deploy\register-startup.ps1 -WithHealthCheck
#   powershell -ExecutionPolicy Bypass -File deploy\register-startup.ps1 -Remove
#
# Tasks created:
#   MortgageDashboard-Apps   -> deploy\start-apps.ps1  (uvicorn on 9001)
#       Runs AS THE INVOKING USER, triggered at that user's logon.
#   MortgageDashboard-Proxy  -> deploy\start-proxy.ps1 (Caddy on :80)
#       Runs as SYSTEM at startup (so Caddy can bind :80 pre-login).
#
# WHY THE APP RUNS AS THE USER (not SYSTEM):
#   Plaid credentials AND each linked bank's access token live in the INVOKING
#   USER's Windows Credential Manager vault (created when you linked banks and ran
#   store-plaid-credentials.ps1 as yourself). SYSTEM has a SEPARATE vault that does
#   not contain them, so a SYSTEM-run app silently falls back to Plaid *sandbox*
#   (env=sandbox, "no banks connected"). Running the app as the user points it at
#   the vault that actually has the production creds + bank tokens. The proxy has
#   no such dependency, so it stays SYSTEM for the :80 bind.
#   To run the app as SYSTEM instead, you must first copy the Plaid creds AND every
#   plaid_item_<slug>_access_token / _cursor into SYSTEM's vault.
#
# Optional self-heal task (-WithHealthCheck):
#   MortgageDashboard-HealthCheck -> deploy\health-check.ps1 (at logon + every N min)
#       ALSO runs as the invoking user, so when it relaunches the app it uses the
#       same (correct) user vault. If it ran as SYSTEM it would relaunch a sandbox
#       instance and fight the real one.
#
# -Remove takes down all three tasks.

param(
    [switch]$Remove,
    [switch]$WithHealthCheck,
    [int]$HealthCheckMinutes = 5,
    # The account the app + health-check run as. Defaults to the invoking user,
    # which is normally correct (its vault holds the Plaid creds + bank tokens).
    [string]$AppUser = ([Security.Principal.WindowsIdentity]::GetCurrent().Name)
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
$healthTask = "MortgageDashboard-HealthCheck"

if ($Remove) {
    foreach ($name in @($appsTask, $proxyTask, $healthTask)) {
        if (Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue) {
            Unregister-ScheduledTask -TaskName $name -Confirm:$false
            Write-Host "Removed task: $name"
        }
    }
    return
}

# The PROXY runs as SYSTEM at startup so Caddy can bind :80 before any login.
function Register-ProxyTask($name, $scriptPath) {
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
    Write-Host "Registered task: $name -> $scriptPath (SYSTEM, at startup)"
}

# The APP runs AS THE USER at that user's logon, so it reads the user's Plaid
# vault (production creds + bank tokens). Interactive logon type; no stored
# password needed (it starts when the user signs in).
function Register-AppTask($name, $scriptPath, $user) {
    $psExe = "powershell.exe"
    $args = "-NoProfile -ExecutionPolicy Bypass -File `"$scriptPath`""
    $action = New-ScheduledTaskAction -Execute $psExe -Argument $args
    $trigger = New-ScheduledTaskTrigger -AtLogOn -User $user
    $principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Highest
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)

    if (Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $name -Confirm:$false
    }
    Register-ScheduledTask -TaskName $name -Action $action -Trigger $trigger -Principal $principal -Settings $settings | Out-Null
    Write-Host "Registered task: $name -> $scriptPath (user '$user', at logon)"
}

# A recurring self-heal task: at the user's logon AND every N minutes, run
# health-check.ps1 (checks the app + proxy, relaunches whatever is down). Runs AS
# THE USER so its app relaunch uses the same user vault the app needs (a SYSTEM
# relaunch would start a sandbox instance). The proxy portion can only warn if it
# can't bind :80 as the user; the proxy's own SYSTEM task + restart handles that.
function Register-HealthCheckTask($name, $scriptPath, $everyMinutes, $user) {
    $psExe = "powershell.exe"
    $args = "-NoProfile -ExecutionPolicy Bypass -File `"$scriptPath`" -AppsOnly"
    $action = New-ScheduledTaskAction -Execute $psExe -Argument $args

    $logonTrigger = New-ScheduledTaskTrigger -AtLogOn -User $user
    $repeatTrigger = New-ScheduledTaskTrigger -Once -At (Get-Date) `
        -RepetitionInterval (New-TimeSpan -Minutes $everyMinutes)

    $principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Highest
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
        -StartWhenAvailable -MultipleInstances IgnoreNew `
        -ExecutionTimeLimit (New-TimeSpan -Minutes 5)

    if (Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $name -Confirm:$false
    }
    Register-ScheduledTask -TaskName $name -Action $action `
        -Trigger @($logonTrigger, $repeatTrigger) -Principal $principal -Settings $settings | Out-Null
    Write-Host "Registered task: $name -> $scriptPath (user '$user', at logon + every $everyMinutes min)"
}

Register-AppTask $appsTask (Join-Path $here "start-apps.ps1") $AppUser
Register-ProxyTask $proxyTask (Join-Path $here "start-proxy.ps1")

if ($WithHealthCheck) {
    Register-HealthCheckTask $healthTask (Join-Path $here "health-check.ps1") $HealthCheckMinutes $AppUser
}

Write-Host ""
Write-Host "Done. App runs as '$AppUser' at logon; proxy as SYSTEM at startup."
Write-Host "To start now without waiting for a logon/reboot:"
Write-Host "  Start-ScheduledTask -TaskName $appsTask"
Write-Host "  Start-ScheduledTask -TaskName $proxyTask"
if ($WithHealthCheck) {
    Write-Host "  Start-ScheduledTask -TaskName $healthTask   # runs the health check immediately"
} else {
    Write-Host ""
    Write-Host "Tip: add -WithHealthCheck to also register a self-heal task (runs as the"
    Write-Host "     same user) that restarts the app if it dies between logons."
}
