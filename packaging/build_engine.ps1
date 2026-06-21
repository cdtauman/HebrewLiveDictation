<#
.SYNOPSIS
  Build the headless engine sidecar into a standalone engine.exe (PyInstaller onedir).

.DESCRIPTION
  Local packaged proof -- NOT the final release. The final beta artifact must be reproducible
  through GitHub Actions / GitHub Release; this script is the dev-machine equivalent that
  validates the freeze + packaged launch seam.

  Output: dist/engine/engine.exe (+ dist/engine/_internal/...). Copy the whole dist/engine
  folder next to VoiceType.exe as an `engine\` subfolder; RepoPaths then spawns it directly
  (falling back to `python -m hebrew_live_dictation.bridge` when no packaged engine is present).

.PARAMETER StageInto
  Optional path to a shell output dir; if given, the built dist/engine is copied to
  <StageInto>\engine so a packaged-layout self-test can run immediately.

  NOTE: ASCII-only on purpose. Windows PowerShell 5.1 mis-decodes non-ASCII (em dashes, smart
  quotes) in a UTF-8 file and fails to parse, so keep this script ASCII.
#>
param(
  [string]$StageInto = ""
)

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot   # packaging\ -> repo root
Set-Location $repo

$py = Join-Path $repo ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { $py = "python" }

Write-Host "Building engine.exe with PyInstaller..." -ForegroundColor Cyan
# Pre-clean PyInstaller's build AND dist output dirs ourselves. PyInstaller cleans both with
# shutil.rmtree, which fails on Windows when a previously-collected file is read-only (WinError 5
# seen on build\engine\localpycs and dist\engine\_internal\av\audio). Remove-Item -Force clears the
# read-only attribute and succeeds, so we remove them here and DON'T pass --clean.
foreach ($d in @((Join-Path $repo "build\engine"), (Join-Path $repo "dist\engine"))) {
  if (Test-Path $d) { Remove-Item -Recurse -Force $d -ErrorAction SilentlyContinue }
}

# PyInstaller writes progress to stderr; under ErrorActionPreference=Stop, Windows PowerShell 5.1
# treats the first native-stderr line as a terminating error. Scope Continue around the call and
# detect real failure via the exit code instead.
$prevEAP = $ErrorActionPreference
$ErrorActionPreference = "Continue"
& $py -m PyInstaller --noconfirm "packaging\engine.spec"
$code = $LASTEXITCODE
$ErrorActionPreference = $prevEAP
if ($code -ne 0) { throw "PyInstaller failed (exit $code)" }

$engineExe = Join-Path $repo "dist\engine\engine.exe"
if (-not (Test-Path $engineExe)) { throw "Expected $engineExe not found" }
Write-Host "Built: $engineExe" -ForegroundColor Green

if ($StageInto -ne "") {
  # Guardrails before any Remove-Item: only stage into a real shell output dir, and only delete a
  # pre-existing engine\ we recognize as a prior staging (contains engine.exe), so a mistyped
  # -StageInto can never recursively delete an unrelated 'engine' directory.
  if (-not (Test-Path -PathType Container $StageInto)) {
    throw "-StageInto '$StageInto' is not an existing directory."
  }
  if (-not (Test-Path (Join-Path $StageInto "VoiceType.exe"))) {
    throw "-StageInto '$StageInto' does not contain VoiceType.exe; refusing to stage into a non-shell dir."
  }
  $dest = Join-Path $StageInto "engine"
  if (Test-Path $dest) {
    if (-not (Test-Path (Join-Path $dest "engine.exe"))) {
      throw "Refusing to delete '$dest': not a recognized engine staging dir (no engine.exe)."
    }
    Remove-Item -Recurse -Force $dest
  }
  Copy-Item -Recurse -Force (Join-Path $repo "dist\engine") $dest
  Write-Host "Staged packaged engine into: $dest" -ForegroundColor Green
}
