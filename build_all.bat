@echo off
setlocal

cd /d "%~dp0lifx_control_panel" || exit /b 1
set PYTHONOPTIMIZE=1

if exist "%~dp0.venv\Scripts\python.exe" (
    "%~dp0.venv\Scripts\python.exe" -m PyInstaller build_all.spec
) else (
    python -m PyInstaller build_all.spec
)
set EXIT_CODE=%ERRORLEVEL%

cd /d "%~dp0"
exit /b %EXIT_CODE%
