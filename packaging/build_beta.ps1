<#
.SYNOPSIS
  Assemble a LOCAL, UNSIGNED beta package layout: the self-contained unpackaged WinUI shell plus
  the bundled engine\engine.exe, in one folder a user could run WITHOUT the repo or a dev env.

.DESCRIPTION
  This is NOT a release and NOT signed. Unsigned binaries trigger a Windows SmartScreen
  "unknown publisher" warning (and possible AV friction). The shippable artifact must later be
  produced reproducibly by GitHub Actions / GitHub Release (P4) and signed; this script is the
  local dev-machine equivalent that proves the package SHAPE.

  Steps:
    1. dotnet publish the shell self-contained + WindowsAppSDK self-contained (bundles the .NET
       runtime AND the Windows App Runtime, so the target needs neither installed).
    2. Build the frozen engine (packaging\build_engine.ps1 -> dist\engine).
    3. Assemble dist\beta\VoiceType-beta\ = published shell + engine\ subfolder + READ-ME-BETA.txt.

  ASCII-only on purpose (Windows PowerShell 5.1 mis-parses non-ASCII in a UTF-8 script).

.PARAMETER Config
  Build configuration (default Release).
.PARAMETER OutDir
  Target layout dir (default dist\beta\VoiceType-beta).
#>
param(
  [string]$Config = "Release",
  [string]$OutDir = ""
)

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo

$beta = if ($OutDir -ne "") { $OutDir } else { Join-Path $repo "dist\beta\VoiceType-beta" }

function Invoke-Native([scriptblock]$call, [string]$what) {
  # PyInstaller/dotnet write progress to stderr; under ErrorActionPreference=Stop, PS 5.1 treats
  # the first native-stderr line as terminating. Scope Continue and detect failure via exit code.
  $prev = $ErrorActionPreference
  $ErrorActionPreference = "Continue"
  & $call
  $code = $LASTEXITCODE
  $ErrorActionPreference = $prev
  if ($code -ne 0) { throw "$what failed (exit $code)" }
}

# 1) Publish the self-contained, unpackaged WinUI shell (bundles .NET + Windows App Runtime).
Write-Host "Publishing self-contained WinUI shell ($Config)..." -ForegroundColor Cyan
Invoke-Native { dotnet publish "winui\VoiceType.App\VoiceType.App.csproj" -c $Config -p:Platform=x64 `
  -r win-x64 --self-contained true -p:WindowsAppSDKSelfContained=true -p:WindowsPackageType=None } "dotnet publish"

$publishExe = Get-ChildItem -Recurse -Path "winui\VoiceType.App\bin\x64\$Config" -Filter "VoiceType.exe" |
  Where-Object { $_.DirectoryName -like "*\publish" } | Sort-Object LastWriteTime -Descending | Select-Object -First 1
if (-not $publishExe) { throw "Could not find published VoiceType.exe under the $Config publish tree." }
$publishDir = $publishExe.DirectoryName
Write-Host "Published shell: $publishDir" -ForegroundColor Green

# dotnet publish for UNPACKAGED WinUI drops the app's compiled resource index (VoiceType.pri) from
# the publish folder. Without it, XBF (compiled XAML) lookups fail at runtime and EVERY page/window
# throws XamlParseException 0x802B000A (the UI never comes up). The full PRI is produced by the
# publish's own build in the parent (non-publish) output dir; copy it in if publish omitted it.
$appPri = "VoiceType.pri"
if (-not (Test-Path (Join-Path $publishDir $appPri))) {
  $builtPri = Join-Path (Split-Path $publishDir -Parent) $appPri
  if (-not (Test-Path $builtPri)) {
    throw "Publish is missing $appPri and no built PRI at $builtPri; XAML would fail at runtime."
  }
  Copy-Item -Force $builtPri (Join-Path $publishDir $appPri)
  Write-Host "Recovered missing $appPri into publish output (WinUI unpackaged publish gap)." -ForegroundColor Yellow
}

# 2) Build the frozen engine (onedir -> dist\engine).
Write-Host "Building frozen engine..." -ForegroundColor Cyan
& "$PSScriptRoot\build_engine.ps1"
$engineSrc = Join-Path $repo "dist\engine"
if (-not (Test-Path (Join-Path $engineSrc "engine.exe"))) { throw "engine build did not produce dist\engine\engine.exe" }

# 3) Assemble the beta layout.
# Deletion guard: only ever remove a directory that is EMPTY or that we recognize as a prior beta
# layout by our own marker file (READ-ME-BETA.txt). VoiceType.exe alone is NOT sufficient — that
# could be any app folder. This prevents a mistyped -OutDir from deleting an arbitrary user folder.
$marker = "READ-ME-BETA.txt"
if (Test-Path $beta) {
  $isEmpty = -not (Get-ChildItem -Force $beta -ErrorAction SilentlyContinue | Select-Object -First 1)
  $hasMarker = Test-Path (Join-Path $beta $marker)
  if (-not $isEmpty -and -not $hasMarker) {
    throw "Refusing to delete '$beta': not empty and not a prior beta layout (missing $marker). Pass an empty dir or a previously-built beta folder."
  }
  Remove-Item -Recurse -Force $beta
}
New-Item -ItemType Directory -Force -Path $beta | Out-Null
Copy-Item -Recurse -Force (Join-Path $publishDir "*") $beta
Copy-Item -Recurse -Force $engineSrc (Join-Path $beta "engine")

# READ-ME for the end user, placed in the package root.
$readme = @"
VoiceType - UNSIGNED LOCAL BETA (not a release)

What this is
  A self-contained, unpackaged build: the WinUI shell (VoiceType.exe) plus the bundled Python
  engine (engine\engine.exe). It runs without Python, the repo, or a dev environment. The
  Windows App Runtime and the .NET runtime are bundled, so nothing extra needs installing.

How to run
  Double-click VoiceType.exe (or run it from a terminal).

SmartScreen / unknown publisher
  These binaries are NOT code-signed. Windows SmartScreen will show an
  "unknown publisher" / "Windows protected your PC" warning, and some antivirus may flag the
  unsigned exe. To run anyway: More info -> Run anyway. Signing is wired in a later phase.

Offline dictation
  The offline Whisper model is NOT bundled. Install it from the app (Engine room) before using
  offline dictation; it is never silently downloaded.

Status
  Beta. Not signed. Not a final release.
"@
Set-Content -Path (Join-Path $beta $marker) -Value $readme -Encoding UTF8

# 4) Report.
$size = (Get-ChildItem -Recurse $beta | Measure-Object Length -Sum).Sum
Write-Host ""
Write-Host "Beta layout assembled: $beta" -ForegroundColor Green
Write-Host ("Total size: {0:N0} MB" -f ($size / 1MB))
Write-Host "Engine present: $([bool](Test-Path (Join-Path $beta 'engine\engine.exe')))"
Write-Host ""
Write-Host "Smoke test (must pass):" -ForegroundColor Cyan
Write-Host "  & `"$beta\VoiceType.exe`" --selftest --expect-packaged-engine"
