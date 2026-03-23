param()

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $Root ".venv\\Scripts\\python.exe"
if (-not (Test-Path $Python)) {
    $Python = "python"
}

$DistRoot = Join-Path $Root "dist"
$GuiDist = Join-Path $DistRoot "affitto_gui"
$BuildRoot = Join-Path $Root "build\\pyinstaller"
$GuiSpec = Join-Path $Root "packaging\\affitto_gui.spec"
$CliSpec = Join-Path $Root "packaging\\affitto_cli.spec"
$CliExe = Join-Path $DistRoot "affitto_cli.exe"
$CliTarget = Join-Path $GuiDist "affitto_cli.exe"

Write-Host "Python:" $Python
Write-Host "Root:" $Root

if (Test-Path $GuiDist) {
    Remove-Item $GuiDist -Recurse -Force
}
if (Test-Path $CliExe) {
    Remove-Item $CliExe -Force
}
if (Test-Path $BuildRoot) {
    Remove-Item $BuildRoot -Recurse -Force
}

Push-Location $Root
try {
    & $Python -m PyInstaller --noconfirm --clean --distpath $DistRoot --workpath $BuildRoot $GuiSpec
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }

    & $Python -m PyInstaller --noconfirm --clean --distpath $DistRoot --workpath $BuildRoot $CliSpec
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
}
finally {
    Pop-Location
}

if (-not (Test-Path $CliExe)) {
    throw "Companion CLI build missing: $CliExe"
}
if (-not (Test-Path $GuiDist)) {
    throw "GUI dist folder missing: $GuiDist"
}

Move-Item $CliExe $CliTarget -Force

Write-Host ""
Write-Host "Bundle pronto:" $GuiDist
Write-Host "GUI exe:" (Join-Path $GuiDist "affitto_gui.exe")
Write-Host "CLI companion:" $CliTarget
