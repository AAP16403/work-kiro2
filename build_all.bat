@echo off
setlocal enableextensions

cd /d "%~dp0"

echo === Kiro2Game: build .exe ===
echo Working dir: %CD%
echo.

where py >nul 2>nul
if errorlevel 1 (
  echo ERROR: Python launcher ^(py.exe^) not found.
  echo Install Python from python.org and ensure "py" works in a new terminal.
  goto :fail
)

if not exist ".venv\Scripts\python.exe" (
  echo Creating virtual environment...
  py -m venv .venv
  if errorlevel 1 goto :fail
)

echo Installing/updating dependencies...
".venv\Scripts\python.exe" -m pip install -U pip pyglet pyinstaller
if errorlevel 1 goto :fail

echo.
echo Building executable ^(PyInstaller^)...
powershell -NoProfile -ExecutionPolicy Bypass -File ".\build_exe.ps1"
if errorlevel 1 goto :fail

echo.
echo SUCCESS.
echo Output folder: %CD%\dist\Kiro2Game\
echo EXE: %CD%\dist\Kiro2Game\Kiro2Game.exe
echo.
pause
exit /b 0

:fail
echo.
echo FAILED. Scroll up for the first error message.
echo.
pause
exit /b 1

