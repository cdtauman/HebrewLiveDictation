$ErrorActionPreference = "Stop"
$env:PYTHONDONTWRITEBYTECODE = "1"
$env:PYTHONPATH = "src"

python -m pip install -r requirements.txt
python -m unittest discover -s tests
python scripts\release_audit.py

$nativeBuild = Join-Path $PSScriptRoot "native\tsf_hello_peer\build_local.ps1"
if ((Test-Path -LiteralPath $nativeBuild) -and (Get-Command cmake -ErrorAction SilentlyContinue)) {
    powershell -ExecutionPolicy Bypass -File $nativeBuild -Configuration Release
} elseif (Test-Path -LiteralPath $nativeBuild) {
    Write-Warning "cmake was not found; packaging Python app without compiled TSF native peer."
}

# Clean build and dist directories robustly before packaging
python -c "import pathlib, shutil, os, stat; [shutil.rmtree(p, onexc=lambda f,pt,ex: (os.chmod(pt, stat.S_IWRITE), f(pt))) for p in [pathlib.Path('build'), pathlib.Path('dist')] if p.exists()]"

python -m PyInstaller HebrewLiveDictation.spec --noconfirm

Write-Host "Build complete. Check the dist\\HebrewLiveDictation folder."

