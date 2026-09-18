<#
.SYNOPSIS
  Run the pre-commit security/quality scans directly against the backend venv.

.DESCRIPTION
  Runs, in order:
    1. detect-secrets  - secret scan against .secrets.baseline (fails on NEW secrets)
    2. ruff            - Python lint + flake8-bandit security rules (backend/)
    3. bandit          - Python SAST (backend/, excludes venv+tests)
    4. pip-audit       - dependency vulnerability audit (backend/requirements.txt)
    5. npm audit       - frontend dependency vulnerability audit
    6. eslint          - frontend lint

  Does NOT modify anything. Prints a per-tool PASS/FAIL summary and exits non-zero
  if any scan reports findings, so it can gate a commit or CI step.

.NOTES
  Requires backend/requirements-dev.txt installed into backend/venv, and
  frontend/node_modules present (npm install).
#>
[CmdletBinding()]
param(
    [switch]$SkipFrontend
)

$ErrorActionPreference = 'Continue'
$repo = Split-Path -Parent $PSScriptRoot
$venv = Join-Path $repo 'backend\venv\Scripts'
$results = [ordered]@{}

function Invoke-Scan {
    param([string]$Name, [scriptblock]$Body)
    Write-Host "`n===== $Name =====" -ForegroundColor Cyan
    & $Body
    $results[$Name] = ($LASTEXITCODE -eq 0)
    if ($LASTEXITCODE -eq 0) {
        Write-Host "$Name : PASS" -ForegroundColor Green
    } else {
        Write-Host "$Name : FINDINGS (exit $LASTEXITCODE)" -ForegroundColor Yellow
    }
}

Push-Location $repo
try {
    Invoke-Scan 'detect-secrets' {
        & "$venv\detect-secrets.exe" scan --baseline .secrets.baseline `
            --exclude-files 'backend/venv/.*' `
            --exclude-files 'frontend/node_modules/.*' `
            --exclude-files 'frontend/dist/.*' `
            --exclude-files '.*\.enc$' `
            --exclude-files 'backend/txn_data/.*' `
            --exclude-files 'frontend/package-lock.json'
    }

    Invoke-Scan 'ruff' {
        & "$venv\ruff.exe" check backend --config backend\pyproject.toml
    }

    Invoke-Scan 'bandit' {
        & "$venv\bandit.exe" -c backend\pyproject.toml -r backend -q
    }

    Invoke-Scan 'pip-audit' {
        & "$venv\pip-audit.exe" -r backend\requirements.txt
    }

    if (-not $SkipFrontend) {
        Invoke-Scan 'npm-audit' {
            Push-Location (Join-Path $repo 'frontend')
            try { npm audit --omit=dev } finally { Pop-Location }
        }
        Invoke-Scan 'eslint' {
            Push-Location (Join-Path $repo 'frontend')
            try { npm run lint } finally { Pop-Location }
        }
    }
}
finally {
    Pop-Location
}

Write-Host "`n===== SUMMARY =====" -ForegroundColor Cyan
$anyFail = $false
foreach ($k in $results.Keys) {
    if ($results[$k]) {
        Write-Host ("  {0,-16} PASS" -f $k) -ForegroundColor Green
    } else {
        Write-Host ("  {0,-16} FINDINGS" -f $k) -ForegroundColor Yellow
        $anyFail = $true
    }
}
if ($anyFail) { exit 1 } else { exit 0 }
