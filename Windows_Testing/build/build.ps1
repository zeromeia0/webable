# Webable Windows build — run on Windows 10/11 with Python 3.12+.
#
#   Set-ExecutionPolicy -Scope Process Bypass
#   .\build\build.ps1              # release build (no console)
#   .\build\build.ps1 -Debug       # console debug build
#   .\build\build.ps1 -Installer     # release + Inno Setup

param(
    [switch]$Installer,
    [switch]$Debug,
    [switch]$DevRun,
    [string]$Python = "python"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

function Get-AppVersion {
    $v = Get-Content -Path (Join-Path $Root "VERSION") -TotalCount 1
    return ($v -replace '\s', '').Trim()
}

Write-Host "==> Webable Windows build (root: $Root)"

if ($DevRun) {
    Write-Host "==> Dev run (no PyInstaller)"
    if (-not (Test-Path (Join-Path $Root ".venv-win"))) {
        & $Python -m venv (Join-Path $Root ".venv-win")
    }
    $py = Join-Path $Root ".venv-win\Scripts\python.exe"
    $pip = Join-Path $Root ".venv-win\Scripts\pip.exe"
    & $pip install -q -r requirements-windows.txt
    & $py windows_launcher.py
    exit $LASTEXITCODE
}

$venv = Join-Path $Root ".venv-win"
if (-not (Test-Path $venv)) {
    & $Python -m venv $venv
}
$pip = Join-Path $venv "Scripts\pip.exe"
$py = Join-Path $venv "Scripts\python.exe"

Write-Host "==> Installing dependencies..."
& $pip install -U pip wheel
& $pip install -r requirements-windows.txt

Write-Host "==> Generating icon..."
& $py assets\generate_icon.py

$version = Get-AppVersion
Write-Host "==> Version: $version"

$spec = if ($Debug) { "webable-debug.spec" } else { "webable.spec" }
Write-Host "==> PyInstaller ($spec)..."
Remove-Item -Recurse -Force dist, build -ErrorAction SilentlyContinue
& $py -m PyInstaller --noconfirm --clean $spec

if ($Debug) {
    $distApp = Join-Path $Root "dist\Webable-Debug\Webable-Debug.exe"
} else {
    $distApp = Join-Path $Root "dist\Webable\Webable.exe"
}
if (-not (Test-Path $distApp)) {
    throw "Build failed: $distApp not found"
}
Write-Host "==> Built: $distApp"

Write-Host "==> Verifying bundle..."
& $py scripts\verify_bundle.py

if (-not $Debug) {
    $zipName = Join-Path $Root "dist\Webable-$version-portable-win64.zip"
    if (Test-Path $zipName) { Remove-Item $zipName -Force }
    Compress-Archive -Path (Join-Path $Root "dist\Webable\*") -DestinationPath $zipName
    Write-Host "==> Portable zip: $zipName"
}

if ($Installer -and -not $Debug) {
    $iscc = @(
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
        "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
    ) | Where-Object { Test-Path $_ } | Select-Object -First 1
    if (-not $iscc) {
        throw "Inno Setup 6 not found. Install from https://jrsoftware.org/isinfo.php"
    }
    Write-Host "==> Inno Setup installer..."
    & $iscc "/DAppVersion=$version" "installer\WebableSetup.iss"
    $setup = Join-Path $Root "dist\installer\Webable-Setup-$version.exe"
    if (Test-Path $setup) {
        Write-Host "==> Installer: $setup"
    } else {
        throw "Installer build failed"
    }
}

Write-Host ""
if ($Debug) {
    Write-Host "Debug build ready. Run from a console:"
    Write-Host "  dist\Webable-Debug\Webable-Debug.exe"
    Write-Host "Tracebacks print to console AND %LOCALAPPDATA%\Webable\logs\webable.log"
} else {
    Write-Host "Release build ready:"
    Write-Host "  dist\Webable\Webable.exe"
}
