# Reads a Plaid credential back from Windows Credential Manager via the native
# CredRead API and prints ONLY whether it was found and its length — never the value.
# Used to verify which account context (e.g. SYSTEM vs the current user) can see
# the stored credentials.
#
#   powershell -ExecutionPolicy Bypass -File deploy\read-plaid-credential.ps1 -Target plaid_client_id

param(
    [Parameter(Mandatory = $true)][string]$Target
)

$ErrorActionPreference = "Stop"

if (-not ("PlaidCredRead.CredApi" -as [type])) {
    Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;

namespace PlaidCredRead {
    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    public struct CREDENTIAL {
        public uint Flags;
        public uint Type;
        public string TargetName;
        public string Comment;
        public System.Runtime.InteropServices.ComTypes.FILETIME LastWritten;
        public uint CredentialBlobSize;
        public IntPtr CredentialBlob;
        public uint Persist;
        public uint AttributeCount;
        public IntPtr Attributes;
        public string TargetAlias;
        public string UserName;
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

$ptr = [IntPtr]::Zero
$ok = [PlaidCredRead.CredApi]::CredRead($Target, 1, 0, [ref]$ptr)  # 1 = GENERIC
if (-not $ok) {
    $err = [System.Runtime.InteropServices.Marshal]::GetLastWin32Error()
    Write-Host "NOT FOUND for '$Target' as $([System.Security.Principal.WindowsIdentity]::GetCurrent().Name) (Win32 $err)"
    exit 1
}
try {
    $cred = [System.Runtime.InteropServices.Marshal]::PtrToStructure($ptr, [type]"PlaidCredRead.CREDENTIAL")
    $len = [int]($cred.CredentialBlobSize / 2)  # Unicode bytes -> chars
    Write-Host "FOUND '$Target' as $([System.Security.Principal.WindowsIdentity]::GetCurrent().Name); secret length = $len chars"
} finally {
    [PlaidCredRead.CredApi]::CredFree($ptr)
}
