@echo off
setlocal enableextensions
cd /d "%~dp0"

set "PY_EXE="

if exist ".venv\Scripts\python.exe" (
    set "PY_EXE=.venv\Scripts\python.exe"
    goto :run
)

where py >nul 2>&1
if %ERRORLEVEL% equ 0 (
    set "PY_EXE=py"
    goto :run
)

where python >nul 2>&1
if %ERRORLEVEL% equ 0 (
    set "PY_EXE=python"
    goto :run
)

echo [ERROR] Neither .venv nor Python was found on your system.
echo Please install Python or set up the virtual environment in .venv.
pause
exit /b 1

:run
echo Starting game using: %PY_EXE%
"%PY_EXE%" main.py %*
if %ERRORLEVEL% neq 0 (
    echo.
    echo Game exited with error code %ERRORLEVEL%.
    pause
)
