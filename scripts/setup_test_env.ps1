param(
    [switch]$SkipPlaywright
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = Split-Path -Parent $scriptDir
Set-Location $projectRoot

$venvPython = Join-Path $projectRoot ".venv\\Scripts\\python.exe"

if (-not (Test-Path $venvPython)) {
    Write-Host "[setup] Creating virtual environment..."
    python -m venv .venv
}

Write-Host "[setup] Upgrading pip..."
& $venvPython -m pip install --upgrade pip

Write-Host "[setup] Installing requirements..."
& $venvPython -m pip install -r requirements.txt

if (-not $SkipPlaywright) {
    Write-Host "[setup] Installing Playwright Chromium..."
    & $venvPython -m playwright install chromium
}

Write-Host "[setup] Done."
Write-Host "[setup] Activate with: .\\.venv\\Scripts\\Activate.ps1"
