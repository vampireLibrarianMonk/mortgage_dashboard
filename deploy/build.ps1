# Builds the production frontend into frontend/dist, which FastAPI serves.
# Run this once after setup and again whenever the frontend changes.
#
#   powershell -ExecutionPolicy Bypass -File deploy\build.ps1

$ErrorActionPreference = "Stop"

$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$repo = Split-Path -Parent $here
$frontend = Join-Path $repo "frontend"

Write-Host "Installing frontend dependencies..."
Push-Location $frontend
try {
    npm install
    Write-Host "Building frontend (npm run build)..."
    npm run build
} finally {
    Pop-Location
}

$dist = Join-Path $frontend "dist"
if (Test-Path (Join-Path $dist "index.html")) {
    Write-Host "Build complete: $dist"
} else {
    throw "Build did not produce $dist\index.html"
}
