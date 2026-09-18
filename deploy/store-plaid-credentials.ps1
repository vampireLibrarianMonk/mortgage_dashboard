# Stores the Plaid client_id and sandbox_secret from the repo-root .env file into
# Windows Credential Manager (Generic credentials, persisted at LocalMachine so the
# SYSTEM boot task can read them). Secrets are read straight from .env into memory
# and written via the native Windows Credential API (CredWrite) — they are never
# passed on a command line, echoed, or written to shell history.
#
#   powershell -ExecutionPolicy Bypass -File deploy\store-plaid-credentials.ps1
#
# Target names created:
#   plaid_client_id
#   plaid_sandbox_secret

$ErrorActionPreference = "Stop"

$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$repo = Split-Path -Parent $here
$envPath = Join-Path $repo ".env"

if (-not (Test-Path $envPath)) {
    throw ".env not found at $envPath"
}

# Parse .env into a hashtable without printing any values.
$vals = @{}
foreach ($line in Get-Content $envPath) {
    $trimmed = $line.Trim()
    if ($trimmed -eq "" -or $trimmed.StartsWith("#")) { continue }
    $idx = $trimmed.IndexOf("=")
    if ($idx -lt 1) { continue }
    $k = $trimmed.Substring(0, $idx).Trim()
    $v = $trimmed.Substring($idx + 1).Trim().Trim('"')
    $vals[$k] = $v
}

# Map recognized .env keys to their Credential Manager target names. Any key that
# is absent from .env is simply skipped. production_client_id is optional; if it is
# not supplied, the shared client_id is reused for production (Plaid uses the same
# client_id across environments for a given team).
$mapping = @{
    "client_id"            = "plaid_client_id"
    "sandbox_secret"       = "plaid_sandbox_secret"
    "production_client_id" = "plaid_production_client_id"
    "production_secret"    = "plaid_production_secret"
}
if (-not $vals.ContainsKey("client_id")) {
    throw ".env must contain at least client_id"
}

# Native Windows Credential API (advapi32) so secrets never touch the command line.
if (-not ("PlaidCred.CredApi" -as [type])) {
    Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;

namespace PlaidCred {
    public enum CRED_TYPE : uint { GENERIC = 1 }
    public enum CRED_PERSIST : uint { SESSION = 1, LOCAL_MACHINE = 2, ENTERPRISE = 3 }

    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    public struct CREDENTIAL {
        public uint Flags;
        public CRED_TYPE Type;
        public string TargetName;
        public string Comment;
        public System.Runtime.InteropServices.ComTypes.FILETIME LastWritten;
        public uint CredentialBlobSize;
        public IntPtr CredentialBlob;
        public CRED_PERSIST Persist;
        public uint AttributeCount;
        public IntPtr Attributes;
        public string TargetAlias;
        public string UserName;
    }

    public static class CredApi {
        [DllImport("advapi32.dll", SetLastError = true, CharSet = CharSet.Unicode)]
        public static extern bool CredWrite(ref CREDENTIAL credential, uint flags);
    }
}
"@
}

function Store-Secret([string]$target, [string]$user, [string]$secret) {
    $bytes = [System.Text.Encoding]::Unicode.GetBytes($secret)
    $blob = [System.Runtime.InteropServices.Marshal]::AllocHGlobal($bytes.Length)
    try {
        [System.Runtime.InteropServices.Marshal]::Copy($bytes, 0, $blob, $bytes.Length)
        $cred = New-Object PlaidCred.CREDENTIAL
        $cred.Type = [PlaidCred.CRED_TYPE]::GENERIC
        $cred.TargetName = $target
        $cred.UserName = $user
        $cred.CredentialBlob = $blob
        $cred.CredentialBlobSize = [uint32]$bytes.Length
        $cred.Persist = [PlaidCred.CRED_PERSIST]::LOCAL_MACHINE
        if (-not [PlaidCred.CredApi]::CredWrite([ref]$cred, 0)) {
            $err = [System.Runtime.InteropServices.Marshal]::GetLastWin32Error()
            throw "CredWrite failed for '$target' (Win32 error $err)"
        }
    } finally {
        [System.Runtime.InteropServices.Marshal]::ZeroFreeGlobalAllocUnicode([IntPtr]::Zero) 2>$null
        [System.Runtime.InteropServices.Marshal]::FreeHGlobal($blob)
    }
}

$stored = @()
foreach ($key in $mapping.Keys) {
    if ($vals.ContainsKey($key) -and $vals[$key]) {
        Store-Secret -target $mapping[$key] -user "plaid" -secret $vals[$key]
        $stored += $mapping[$key]
    }
}

# If no explicit production_client_id was given but a production_secret was, reuse
# the shared client_id for production.
if ($vals.ContainsKey("production_secret") -and $vals["production_secret"] -and -not ($vals.ContainsKey("production_client_id") -and $vals["production_client_id"])) {
    Store-Secret -target "plaid_production_client_id" -user "plaid" -secret $vals["client_id"]
    $stored += "plaid_production_client_id (from shared client_id)"
}

# Clear the in-memory copies.
foreach ($k in @($vals.Keys)) { $vals[$k] = $null }
$vals.Clear()

Write-Host "Stored the following in Windows Credential Manager (LocalMachine persist):"
foreach ($t in $stored) { Write-Host "  $t" }
Write-Host "Values were read from .env and never printed."
