@echo off
setlocal EnableDelayedExpansion

pushd "%~dp0\.."

for /f "tokens=2 delims=" %%a in ('findstr /B /C:"version" pyproject.toml') do (
    set "_line=%%a"
    set "VERSION=!_line:~9,-1!"
    goto :versionfound
)
:versionfound

set ARCH=%PROCESSOR_ARCHITECTURE%
set OS=windows

if "!ARCH!"=="AMD64" set ARCH=amd64
if "!ARCH!"=="x86" set ARCH=386

echo === ops CLI binary build ===
echo   OS: !OS!
echo   Arch: !ARCH!
echo   Version: !VERSION!

python -m venv .venv
.venv\Scripts\pip install -q -e ".[build]"

python -m PyInstaller --name ops \
    --onefile \
    --add-data "src\ops\blueprints;ops\blueprints" \
    --hidden-import proxmoxer.backends.https \
    --hidden-import keyring.backends.Windows \
    src\ops\cli.py

echo === Build complete ===
echo Binary: dist\ops.exe
echo To run: dist\ops.exe --help

popd
