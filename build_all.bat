@echo off
setlocal enableextensions

cd /d "%~dp0"

echo === Plouto: full build ===
echo Working dir: %CD%
echo.

where py >nul 2>nul
if errorlevel 1 (
  echo ERROR: Python launcher ^(py.exe^) not found.
  echo Install Python and ensure "py" works in a new terminal.
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
echo Running quick syntax validation...
".venv\Scripts\python.exe" -m py_compile main.py game.py enemy.py level.py rpg.py menu.py fonts.py
if errorlevel 1 goto :fail

echo.
echo Building executable ^(PyInstaller^)...
powershell -NoProfile -ExecutionPolicy Bypass -File ".\build_exe.ps1"
if errorlevel 1 goto :fail

echo.
echo Creating .zip...
powershell -NoProfile -ExecutionPolicy Bypass -Command "Push-Location '%CD%\\dist'; if (Test-Path '.\\Plouto.zip') { Remove-Item -Force '.\\Plouto.zip' }; Compress-Archive -Path '.\\Plouto' -DestinationPath '.\\Plouto.zip' -Force; Pop-Location"
if errorlevel 1 goto :fail

echo.
echo SUCCESS.
echo Output folder: %CD%\dist\Plouto\
echo EXE: %CD%\dist\Plouto\Plouto.exe
echo ZIP: %CD%\dist\Plouto.zip
echo.
pause
exit /b 0

:fail
echo.
echo FAILED. Scroll up for the first error message.
echo.
pause
exit /b 1
