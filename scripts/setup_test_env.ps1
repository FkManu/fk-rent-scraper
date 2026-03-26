param(
    [Alias("SkipPlaywright")]
    [switch]$SkipCamoufoxFetch
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

if (-not $SkipCamoufoxFetch) {
    Write-Host "[setup] Fetching Camoufox browser..."
    & $venvPython -m camoufox fetch
}

Write-Host "[setup] Done."
Write-Host "[setup] Activate with: .\\.venv\\Scripts\\Activate.ps1"
