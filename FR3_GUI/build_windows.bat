@echo off
REM Rebuilds the packaged FR3-Board-Control.exe from source (fr3_gui.spec),
REM picking up any changes to the Python code or bundled data files (e.g.
REM data\lo_suppression.csv, data\am3153_sparams). Run from anywhere - it
REM cd's to its own location first. See build_linux_arm64.sh for the Linux
REM (Jetson-class ARM64) equivalent.

cd /d "%~dp0"

call ".\venv\Scripts\python.exe" -m PyInstaller fr3_gui.spec --noconfirm
if errorlevel 1 (
    echo.
    echo Build FAILED.
    pause
    exit /b 1
)

echo.
echo Build succeeded: dist\FR3-Board-Control\FR3-Board-Control.exe
pause
