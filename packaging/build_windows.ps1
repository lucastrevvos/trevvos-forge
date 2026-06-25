#Requires -Version 5.1
<#
.SYNOPSIS
    Build the Trevvos Forge standalone binary for Windows x64.

.DESCRIPTION
    Produces dist\trevvos\ (onedir) and packages it as a ZIP under release\.
    Run from the repo root. Requires Python 3.11+ in PATH or an active venv.

.EXAMPLE
    .\packaging\build_windows.ps1
#>

$ErrorActionPreference = "Stop"

$Version  = "0.1.0-alpha.1"
$AppName  = "trevvos"
$ZipName  = "trevvos-forge-v$Version-windows-x64.zip"
$ZipPath  = "release\$ZipName"

Write-Host ""
Write-Host "=== Trevvos Forge Binary Build — Windows x64 ==="
Write-Host "Version : $Version"
Write-Host "Output  : $ZipPath"
Write-Host ""

# ── 1. Install / refresh build deps ────────────────────────────────────────
Write-Host "--- Installing build dependencies..."
python -m pip install -U pip --quiet
python -m pip install -e . --quiet
python -m pip install pyinstaller --quiet

# ── 2. Clean previous outputs ───────────────────────────────────────────────
Write-Host "--- Cleaning previous build artefacts..."
foreach ($dir in @("build", "dist", "release")) {
    if (Test-Path $dir) { Remove-Item $dir -Recurse -Force }
}
New-Item -ItemType Directory -Force release | Out-Null

# ── 3. Build with PyInstaller ────────────────────────────────────────────────
Write-Host "--- Running PyInstaller..."
python -m PyInstaller `
    --name $AppName `
    --onedir `
    --clean `
    --noconfirm `
    --collect-all typer `
    --collect-all rich `
    --copy-metadata trevvos-forge `
    --add-data "trevvos_forge\local_api\static;trevvos_forge\local_api\static" `
    --add-data "README.md;." `
    --add-data "ALPHA.md;." `
    --add-data "docs;docs" `
    packaging\trevvos_entry.py

# ── 4. Smoke-test the binary ─────────────────────────────────────────────────
Write-Host ""
Write-Host "--- Validating binary..."
$Bin = "dist\$AppName\$AppName.exe"

Write-Host "  $Bin --version"
& $Bin --version

Write-Host "  $Bin version"
& $Bin version

Write-Host "  $Bin --help"
& $Bin --help | Select-Object -First 5

Write-Host "  $Bin setup --help"
& $Bin setup --help | Select-Object -First 3

Write-Host "  $Bin doctor --help"
& $Bin doctor --help | Select-Object -First 3

Write-Host "  $Bin api start --help"
& $Bin api start --help | Select-Object -First 3

# ── 5. Package as ZIP ────────────────────────────────────────────────────────
Write-Host ""
Write-Host "--- Creating ZIP..."

# Give Windows a moment to release files touched by the smoke-tested executable.
Start-Sleep -Seconds 2

# Avoid packaging directly from the PyInstaller output while Windows may still
# be releasing file handles from the validation commands.
$PackageRoot = "release\package"
$PackageAppDir = "$PackageRoot\$AppName"

if (Test-Path $PackageRoot) {
    Remove-Item $PackageRoot -Recurse -Force
}

New-Item -ItemType Directory -Force $PackageAppDir | Out-Null

Copy-Item -Path "dist\$AppName\*" -Destination $PackageAppDir -Recurse -Force

if (Test-Path $ZipPath) {
    Remove-Item $ZipPath -Force
}

Compress-Archive -Path "$PackageAppDir\*" -DestinationPath $ZipPath -Force
$SizeMB = [math]::Round((Get-Item $ZipPath).Length / 1MB, 1)
Write-Host ""
Write-Host "=== Done ==="
Write-Host "Release : $ZipPath ($SizeMB MB)"
Write-Host ""
Write-Host "Usage for testers (Windows):"
Write-Host "  Expand-Archive -Path $ZipName -DestinationPath trevvos"
Write-Host "  cd trevvos"
Write-Host "  .\$AppName.exe setup"
Write-Host "  .\$AppName.exe doctor"
Write-Host "  .\$AppName.exe api start --open"
