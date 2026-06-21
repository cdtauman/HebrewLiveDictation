<#
.SYNOPSIS
  Verify a built beta layout OUT-OF-REPO. Proves it runs with no repo/dev env, that the packaged
  self-test report lands INSIDE the package, and that the hard packaged gate fails when the bundled
  engine.exe is missing.

.DESCRIPTION
  Copies the beta to %TEMP%\vt-beta-verify (so RepoPaths cannot find src\+winui\, hence no dev
  fallback and the packaged report path applies), then:
    [1] POSITIVE: VoiceType.exe --selftest --expect-packaged-engine  -> all NON-ADVISORY checks pass,
        the report exists at <package>\winui_runtime_report.txt, engine.launch.mode PASS.
    [2] NEGATIVE: rename engine\engine.exe away, re-run  -> engine.launch.mode must FAIL.
  ASCII-only (PS 5.1).

  BUILD/ARTIFACT vs GUI FOCUS split (P4 review decision):
  The focus-safety checks (focus.no_steal, hud.surface.no_steal) are environment-sensitive: they fail
  whenever ANY unrelated window holds/takes the foreground while the test runs (the report shows
  fgAfter != hud, i.e. a THIRD window grabbed focus, not our HUD). On a busy desktop or a shared/headless
  CI runner this is non-deterministic (observed 39/37/38 across back-to-back runs, different foreground
  thief each time). So this script HARD-GATES only the deterministic, packaging-relevant checks (engine
  launch mode, packaged layout, XAML/PRI rendering, etc.) and treats the two focus checks as ADVISORY:
  they still run and are recorded in the report, but they do NOT fail packaged verification here.
  Authoritative focus-safety is the P5 real-hardware focus matrix (dictate into Word/Gmail/WhatsApp).

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
$report = Join-Path $work "winui_runtime_report.txt"   # packaged report path = package root (overwritten each run)
$engine = Join-Path $work "engine\engine.exe"

# The app always writes the one canonical $report; each run overwrites the last. To preserve BOTH proofs
# we copy the canonical report to a distinct name after each phase, so CI can upload both:
#   .positive.txt -> the packaged positive run (non-focus checks pass)  .negative.txt -> missing-engine hard-gate FAIL
$reportPositive = Join-Path $work "winui_runtime_report.positive.txt"
$reportNegative = Join-Path $work "winui_runtime_report.negative.txt"
if (Test-Path $reportPositive) { Remove-Item -Force $reportPositive }
if (Test-Path $reportNegative) { Remove-Item -Force $reportNegative }

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

# Environment-sensitive GUI focus checks: reported but NOT hard-gated here (validated in the P5
# real-hardware focus matrix). See the .DESCRIPTION split note.
$advisory = @('focus.no_steal', 'hud.surface.no_steal')

Write-Host "`n[1] POSITIVE: packaged self-test (--expect-packaged-engine)" -ForegroundColor Cyan
$r = Run-Selftest
Copy-Item -Force $report $reportPositive   # preserve the positive proof before the negative run overwrites $report
$resultLine = ($r | Select-String -Pattern "^result:").Line
$launchLine = ($r | Select-String -Pattern "engine.launch.mode").Line
Write-Host "  $resultLine"
Write-Host "  $launchLine"
Write-Host "  positive report: $reportPositive (exists: $(Test-Path $reportPositive))"

# Split any FAIL lines into HARD (must pass) vs ADVISORY (focus, deferred to P5).
$hardFails = @(); $advisoryFails = @()
foreach ($fl in ($r | Select-String -Pattern "^\[FAIL\]")) {
  $name = if ($fl.Line -match "^\[FAIL\]\s+(\S+)") { $Matches[1] } else { $fl.Line }
  if ($advisory -contains $name) { $advisoryFails += $name } else { $hardFails += $name }
}
if ($launchLine -notmatch "^\[PASS\]") { Write-Host "  POSITIVE FAILED: engine.launch.mode not PASS" -ForegroundColor Red; $fail = $true }
if ($hardFails.Count -gt 0)            { Write-Host "  POSITIVE FAILED (hard checks): $($hardFails -join ', ')" -ForegroundColor Red; $fail = $true }
if ($advisoryFails.Count -gt 0)        { Write-Host "  ADVISORY (deferred to P5 real-hardware focus matrix): $($advisoryFails -join ', ') failed in this session (a non-HUD window held foreground) -- not gating packaged verification." -ForegroundColor Yellow }
if (-not $fail)                        { Write-Host "  POSITIVE OK: all hard checks passed + engine.launch.mode PASS." -ForegroundColor Green }

Write-Host "`n[2] NEGATIVE: rename engine.exe away, expect hard-gate FAIL" -ForegroundColor Cyan
Rename-Item $engine "engine.exe.off"
try { $r2 = Run-Selftest }
finally {
  Kill-Work
  $off = Join-Path $work "engine\engine.exe.off"
  if (Test-Path $off) { Rename-Item $off "engine.exe" }
}
if (Test-Path $report) { Copy-Item -Force $report $reportNegative }   # preserve the hard-gate FAIL proof
$resultLine2 = ($r2 | Select-String -Pattern "^result:").Line
$launchLine2 = ($r2 | Select-String -Pattern "engine.launch.mode").Line
Write-Host "  $resultLine2"
Write-Host "  $launchLine2"
Write-Host "  negative report: $reportNegative (exists: $(Test-Path $reportNegative))"
if ($launchLine2 -notmatch "^\[FAIL\]") { Write-Host "  NEGATIVE FAILED: engine.launch.mode should FAIL when engine.exe is missing" -ForegroundColor Red; $fail = $true }

Kill-Work
Write-Host "`nReports preserved:" -ForegroundColor Cyan
Write-Host "  positive (hard checks pass; focus advisory): $reportPositive"
Write-Host "  negative (hard-gate FAIL): $reportNegative"
if ($fail) { Write-Host "`nBETA VERIFY: FAILED" -ForegroundColor Red; exit 1 }
Write-Host "`nBETA VERIFY: PASSED (out-of-repo positive packaged self-test + negative hard-gate)" -ForegroundColor Green
exit 0   # authoritative: don't let a prior native exit code (e.g. robocopy's 1 = files copied) leak out
