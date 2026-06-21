<#
.SYNOPSIS
  Verify a built beta layout OUT-OF-REPO. Proves it runs with no repo/dev env, that the packaged
  self-test report lands INSIDE the package, and that the hard packaged gate fails when the bundled
  engine.exe is missing.

.DESCRIPTION
  Copies the beta to %TEMP%\vt-beta-verify (so RepoPaths cannot find src\+winui\, hence no dev
  fallback and the packaged report path applies), then:
    [1] POSITIVE: VoiceType.exe --selftest --expect-packaged-engine  -> all checks pass, the report
        exists at <package>\winui_runtime_report.txt, engine.launch.mode PASS.
    [2] NEGATIVE: rename engine\engine.exe away, re-run  -> engine.launch.mode must FAIL.
  ASCII-only (PS 5.1).

.PARAMETER Beta
  Beta layout dir (default dist\beta\VoiceType-beta).
#>
param([string]$Beta = "")

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo
if ($Beta -eq "") { $Beta = Join-Path $repo "dist\beta\VoiceType-beta" }

$marker = "READ-ME-BETA.txt"
if (-not (Test-Path (Join-Path $Beta "VoiceType.exe"))) { throw "No VoiceType.exe in '$Beta'." }
if (-not (Test-Path (Join-Path $Beta $marker)))        { throw "'$Beta' is missing $marker; not a beta layout." }

$work = Join-Path $env:TEMP "vt-beta-verify"
if (Test-Path $work) {
  if (-not (Test-Path (Join-Path $work $marker))) { throw "Refusing to clear '$work' (missing $marker)." }
  Remove-Item -Recurse -Force $work
}
Write-Host "Copying beta out-of-repo to $work ..." -ForegroundColor Cyan
robocopy $Beta $work /E /NFL /NDL /NJH /NJS /NP | Out-Null
if ($LASTEXITCODE -ge 8) { throw "robocopy failed ($LASTEXITCODE)" }
if (Test-Path (Join-Path $work "src")) { throw "verify dir unexpectedly contains a repo (src\)." }

$exe    = Join-Path $work "VoiceType.exe"
$report = Join-Path $work "winui_runtime_report.txt"   # packaged report path = package root
$engine = Join-Path $work "engine\engine.exe"

function Kill-Work {
  Get-Process VoiceType,engine -ErrorAction SilentlyContinue |
    Where-Object { $_.Path -like "$work*" } | Stop-Process -Force -ErrorAction SilentlyContinue
}

function Run-Selftest {
  if (Test-Path $report) { Remove-Item -Force $report }
  Kill-Work
  Start-Sleep -Seconds 1
  Start-Process -FilePath $exe -ArgumentList "--selftest","--expect-packaged-engine" | Out-Null
  for ($i = 0; $i -lt 20; $i++) { Start-Sleep -Seconds 2; if (Test-Path $report) { break } }
  if (-not (Test-Path $report)) { throw "No self-test report written at $report" }
  return Get-Content $report
}

$fail = $false

Write-Host "`n[1] POSITIVE: packaged self-test (--expect-packaged-engine)" -ForegroundColor Cyan
$r = Run-Selftest
$resultLine = ($r | Select-String -Pattern "^result:").Line
$launchLine = ($r | Select-String -Pattern "engine.launch.mode").Line
Write-Host "  $resultLine"
Write-Host "  $launchLine"
Write-Host "  report at: $report (exists: $(Test-Path $report))"
$allPass = ($resultLine -match "result: (\d+)/(\d+) passed") -and ($Matches[1] -eq $Matches[2])
if (-not $allPass)                  { Write-Host "  POSITIVE FAILED: not all checks passed" -ForegroundColor Red; $fail = $true }
if ($launchLine -notmatch "^\[PASS\]") { Write-Host "  POSITIVE FAILED: engine.launch.mode not PASS" -ForegroundColor Red; $fail = $true }

Write-Host "`n[2] NEGATIVE: rename engine.exe away, expect hard-gate FAIL" -ForegroundColor Cyan
Rename-Item $engine "engine.exe.off"
try { $r2 = Run-Selftest }
finally {
  Kill-Work
  $off = Join-Path $work "engine\engine.exe.off"
  if (Test-Path $off) { Rename-Item $off "engine.exe" }
}
$resultLine2 = ($r2 | Select-String -Pattern "^result:").Line
$launchLine2 = ($r2 | Select-String -Pattern "engine.launch.mode").Line
Write-Host "  $resultLine2"
Write-Host "  $launchLine2"
if ($launchLine2 -notmatch "^\[FAIL\]") { Write-Host "  NEGATIVE FAILED: engine.launch.mode should FAIL when engine.exe is missing" -ForegroundColor Red; $fail = $true }

Kill-Work
if ($fail) { Write-Host "`nBETA VERIFY: FAILED" -ForegroundColor Red; exit 1 }
Write-Host "`nBETA VERIFY: PASSED (out-of-repo positive packaged self-test + negative hard-gate)" -ForegroundColor Green
exit 0   # authoritative: don't let a prior native exit code (e.g. robocopy's 1 = files copied) leak out
