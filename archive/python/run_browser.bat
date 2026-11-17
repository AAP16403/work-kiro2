@echo off
setlocal enableextensions
cd /d "%~dp0"

set "PY_EXE="

if exist ".venv\Scripts\python.exe" (
    set "PY_EXE=.venv\Scripts\python.exe"
    goto :start_web
)

where py >nul 2>&1
if %ERRORLEVEL% equ 0 (
    set "PY_EXE=py"
    goto :start_web
)

where python >nul 2>&1
if %ERRORLEVEL% equ 0 (
    set "PY_EXE=python"
    goto :start_web
)

echo [ERROR] Neither .venv nor Python was found on your system.
pause
exit /b 1

:start_web
echo Starting local web server on http://localhost:8000 ...
start http://localhost:8000
"%PY_EXE%" -m http.server 8000 --directory vercel_site
