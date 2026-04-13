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
$LegacyPreviewZip = Join-Path $DistRoot "affitto_2_2_preview_bundle.zip"
$LegacyStableZip = Join-Path $DistRoot "affitto_2_2_stable_bundle.zip"
$ReleaseZip = Join-Path $DistRoot "affitto_2_3_stable_bundle.zip"
$ZipTarget = $ReleaseZip

Write-Host "Python:" $Python
Write-Host "Root:" $Root

if (Test-Path $GuiDist) {
    Remove-Item $GuiDist -Recurse -Force
}
if (Test-Path $CliExe) {
    Remove-Item $CliExe -Force
}
if (Test-Path $ReleaseZip) {
    try {
        Remove-Item $ReleaseZip -Force
    }
    catch {
        $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
        $ZipTarget = Join-Path $DistRoot ("affitto_2_3_stable_bundle_" + $stamp + ".zip")
        Write-Warning "Release zip locked, fallback target: $ZipTarget"
    }
}
if (Test-Path $LegacyPreviewZip) {
    Remove-Item $LegacyPreviewZip -Force
}
if (Test-Path $LegacyStableZip) {
    Remove-Item $LegacyStableZip -Force
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

if (-not (Test-Path $GuiDist)) {
    throw "GUI dist folder missing: $GuiDist"
}

$CliExeItem = Get-ChildItem -Path $DistRoot -Recurse -Filter "affitto_cli.exe" -File -ErrorAction SilentlyContinue |
    Sort-Object FullName |
    Select-Object -First 1
if ($null -eq $CliExeItem) {
    throw "Companion CLI build missing under dist: $DistRoot"
}
if (Test-Path $CliTarget) {
    Remove-Item $CliTarget -Force
}
Copy-Item $CliExeItem.FullName $CliTarget -Force
if (-not (Test-Path $CliTarget)) {
    throw "Companion CLI copy missing at target: $CliTarget"
}
if ($CliExeItem.FullName -ne $CliTarget -and (Test-Path $CliExeItem.FullName)) {
    Remove-Item $CliExeItem.FullName -Force
}
$ZipEntries = Get-ChildItem -Path $GuiDist -Force | Select-Object -ExpandProperty FullName
if (-not $ZipEntries) {
    throw "GUI dist folder is empty: $GuiDist"
}
Compress-Archive -Path $ZipEntries -DestinationPath $ZipTarget -Force

Write-Host ""
Write-Host "Bundle pronto:" $GuiDist
Write-Host "GUI exe:" (Join-Path $GuiDist "affitto_gui.exe")
Write-Host "CLI companion:" $CliTarget
Write-Host "Release zip:" $ZipTarget
