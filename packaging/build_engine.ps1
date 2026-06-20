<#
.SYNOPSIS
  Build the headless engine sidecar into a standalone engine.exe (PyInstaller onedir).

.DESCRIPTION
  Local packaged proof — NOT the final release. The final beta artifact must be reproducible
  through GitHub Actions / GitHub Release; this script is the dev-machine equivalent that
  validates the freeze + packaged launch seam.

  Output: dist/engine/engine.exe (+ dist/engine/_internal/...). Copy the whole dist/engine
  folder next to VoiceType.exe as an `engine\` subfolder; RepoPaths then spawns it directly
  (falling back to `python -m hebrew_live_dictation.bridge` when no packaged engine is present).

.PARAMETER StageInto
  Optional path to a shell output dir; if given, the built dist/engine is copied to
  <StageInto>\engine so a packaged-layout self-test can run immediately.
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
& $py -m PyInstaller --noconfirm --clean "packaging\engine.spec"
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed (exit $LASTEXITCODE)" }

$engineExe = Join-Path $repo "dist\engine\engine.exe"
if (-not (Test-Path $engineExe)) { throw "Expected $engineExe not found" }
Write-Host "Built: $engineExe" -ForegroundColor Green

if ($StageInto -ne "") {
  $dest = Join-Path $StageInto "engine"
  if (Test-Path $dest) { Remove-Item -Recurse -Force $dest }
  Copy-Item -Recurse -Force (Join-Path $repo "dist\engine") $dest
  Write-Host "Staged packaged engine into: $dest" -ForegroundColor Green
}
