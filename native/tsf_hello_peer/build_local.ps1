param(
    [ValidateSet("Debug", "Release")]
    [string]$Configuration = "Release",

    [switch]$RunRegistrationDryRun,
    [switch]$CommitExperimentalRegistration,
    [switch]$Unregister
)

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$BuildDir = Join-Path $Root "build"
$Exe = Join-Path $BuildDir "$Configuration\VoiceTypeTsfHelloPeer.exe"
$Dll = Join-Path $BuildDir "$Configuration\VoiceTypeTsfTextService.dll"

if (-not (Get-Command cmake -ErrorAction SilentlyContinue)) {
    throw "cmake was not found. Run this from a Visual Studio Developer PowerShell with CMake installed."
}

cmake -S $Root -B $BuildDir -G "Visual Studio 17 2022" -A x64
cmake --build $BuildDir --config $Configuration

if ($RunRegistrationDryRun -or $CommitExperimentalRegistration) {
    $action = if ($Unregister) { "--unregister-tsf" } else { "--register-tsf" }
    $arguments = @($action)
    if ($CommitExperimentalRegistration) {
        $arguments += "--commit-registration"
        $arguments += "--i-understand-experimental-tsf-registration"
    }
    if ($CommitExperimentalRegistration -and (Test-Path -LiteralPath $Dll)) {
        if ($Unregister) {
            regsvr32.exe /s /u $Dll
        } else {
            regsvr32.exe /s $Dll
        }
    }
    & $Exe @arguments
}

Write-Host "Native build completed: $Exe"
Write-Host "Native TSF DLL: $Dll"
