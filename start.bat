@echo off
rem ============================================================
rem  Click-to-run for Windows:
rem    - detect env (.venv or vendor\)
rem    - if nothing installed, run setup.ps1
rem    - then launch run.py
rem ============================================================
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"
chcp 65001 >nul

set "PY="
set "PYTHONPATH="

if exist ".venv\Scripts\python.exe" (
    set "PY=.venv\Scripts\python.exe"
)

if not defined PY if exist "vendor" (
    set "PY=python"
    set "PYTHONPATH=%CD%\vendor"
)

if defined PY goto :run

if not exist "requirements.txt" (
    echo requirements.txt not found in the project folder.
    echo Please run: powershell -ExecutionPolicy Bypass -File setup.ps1
    pause
    exit /b 1
)

echo Dependencies not installed. Installing (this may take a few minutes)...
powershell -ExecutionPolicy Bypass -File setup.ps1
if errorlevel 1 (
    echo Installation failed. Please run manually: powershell -ExecutionPolicy Bypass -File setup.ps1
    pause
    exit /b 1
)

if exist ".venv\Scripts\python.exe" (
    set "PY=.venv\Scripts\python.exe"
) else if exist "python\python.exe" (
    set "PY=python\python.exe"
) else (
    set "PY=python"
    set "PYTHONPATH=%CD%\vendor"
)

:run
"%PY%" run.py
if errorlevel 1 pause
endlocal