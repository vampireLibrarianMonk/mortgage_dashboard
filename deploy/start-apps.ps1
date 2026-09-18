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

# --- Load Plaid credentials from Windows Credential Manager into env vars ------
# The app reads PLAID_CLIENT_ID / PLAID_SECRET from the environment; we read them
# here (never printed) and set them for the launched process. Start-Process
# inherits this process's environment, so uvicorn sees them. Credentials live in
# the store of whichever account runs this script (SYSTEM at boot), matching how
# they were stored (see deploy/store-plaid-credentials.ps1).
if (-not ("PlaidCredRead.CredApi" -as [type])) {
    Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
namespace PlaidCredRead {
    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    public struct CREDENTIAL {
        public uint Flags; public uint Type; public string TargetName; public string Comment;
        public System.Runtime.InteropServices.ComTypes.FILETIME LastWritten;
        public uint CredentialBlobSize; public IntPtr CredentialBlob; public uint Persist;
        public uint AttributeCount; public IntPtr Attributes; public string TargetAlias; public string UserName;
    }
    public static class CredApi {
        [DllImport("advapi32.dll", SetLastError = true, CharSet = CharSet.Unicode)]
        public static extern bool CredRead(string target, uint type, uint flags, out IntPtr credential);
        [DllImport("advapi32.dll", SetLastError = true)]
        public static extern void CredFree(IntPtr buffer);
    }
}
"@
}

function Get-StoredSecret([string]$target) {
    $ptr = [IntPtr]::Zero
    if (-not [PlaidCredRead.CredApi]::CredRead($target, 1, 0, [ref]$ptr)) { return $null }
    try {
        $cred = [System.Runtime.InteropServices.Marshal]::PtrToStructure($ptr, [type]"PlaidCredRead.CREDENTIAL")
        if ($cred.CredentialBlobSize -eq 0) { return "" }
        $bytes = New-Object byte[] $cred.CredentialBlobSize
        [System.Runtime.InteropServices.Marshal]::Copy($cred.CredentialBlob, $bytes, 0, $cred.CredentialBlobSize)
        return [System.Text.Encoding]::Unicode.GetString($bytes)
    } finally {
        [PlaidCredRead.CredApi]::CredFree($ptr)
    }
}

# Prefer production credentials when present (real banks); otherwise fall back to
# sandbox (fake test banks). This lets the same startup work in either mode with
# no code change -- storing a production secret is what flips it to production.
$prodClientId = Get-StoredSecret "plaid_production_client_id"
$prodSecret = Get-StoredSecret "plaid_production_secret"
$sandboxClientId = Get-StoredSecret "plaid_client_id"
$sandboxSecret = Get-StoredSecret "plaid_sandbox_secret"

if ($prodClientId -and $prodSecret) {
    $env:PLAID_CLIENT_ID = $prodClientId
    $env:PLAID_SECRET = $prodSecret
    $env:PLAID_ENV = "production"
    Write-Host "Plaid credentials loaded from Credential Manager (env=production)."
} elseif ($sandboxClientId -and $sandboxSecret) {
    $env:PLAID_CLIENT_ID = $sandboxClientId
    $env:PLAID_SECRET = $sandboxSecret
    $env:PLAID_ENV = "sandbox"
    Write-Host "Plaid credentials loaded from Credential Manager (env=sandbox)."
} else {
    Write-Warning "Plaid credentials not found in Credential Manager; the app will report Plaid as unconfigured."
}

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
