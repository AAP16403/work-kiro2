@echo off
setlocal enableextensions

cd /d "%~dp0"
set "APP_NAME=Plouto"
set "SPEC_FILE=kiro2_game.spec"
set "PY_EXE=.venv\Scripts\python.exe"

echo === %APP_NAME%: full build ===
echo Working dir: %CD%
echo.

where py >nul 2>nul
if errorlevel 1 (
  echo ERROR: Python launcher ^(py.exe^) not found.
  echo Install Python and ensure "py" works in a new terminal.
  goto :fail
)

if not exist "%PY_EXE%" (
  echo Creating virtual environment...
  py -m venv .venv
  if errorlevel 1 goto :fail
)

if not exist "%SPEC_FILE%" (
  echo ERROR: Missing spec file: %SPEC_FILE%
  goto :fail
)

echo Verifying bundled font assets...
if not exist "assets\fonts\Orbitron-Variable.ttf" (
  echo ERROR: Missing font file: assets\fonts\Orbitron-Variable.ttf
  goto :fail
)
if not exist "assets\fonts\Rajdhani-Regular.ttf" (
  echo ERROR: Missing font file: assets\fonts\Rajdhani-Regular.ttf
  goto :fail
)
if not exist "assets\fonts\Rajdhani-SemiBold.ttf" (
  echo ERROR: Missing font file: assets\fonts\Rajdhani-SemiBold.ttf
  goto :fail
)

echo Installing/updating dependencies...
"%PY_EXE%" -m pip install -U pip pyglet pyinstaller
if errorlevel 1 goto :fail

echo.
echo Cleaning stale build outputs...
if exist "build\kiro2_game" rmdir /s /q "build\kiro2_game"
if exist "dist\Kiro2Game" rmdir /s /q "dist\Kiro2Game"
if exist "dist\Kiro2Game.zip" del /f /q "dist\Kiro2Game.zip"

echo.
echo Running quick syntax validation...
"%PY_EXE%" -m py_compile main.py game.py enemy.py level.py rpg.py menu.py fonts.py
if errorlevel 1 goto :fail

echo.
echo Building executable ^(PyInstaller^)...
powershell -NoProfile -ExecutionPolicy Bypass -File ".\build_exe.ps1"
if errorlevel 1 goto :fail

echo.
echo Creating .zip...
powershell -NoProfile -ExecutionPolicy Bypass -Command "Push-Location '%CD%\\dist'; if (Test-Path '.\\%APP_NAME%.zip') { Remove-Item -Force '.\\%APP_NAME%.zip' }; Compress-Archive -Path '.\\%APP_NAME%' -DestinationPath '.\\%APP_NAME%.zip' -Force; Pop-Location"
if errorlevel 1 goto :fail

echo.
echo SUCCESS.
echo Output folder: %CD%\dist\%APP_NAME%\
echo EXE: %CD%\dist\%APP_NAME%\%APP_NAME%.exe
echo ZIP: %CD%\dist\%APP_NAME%.zip
echo.
pause
exit /b 0

:fail
echo.
echo FAILED. Scroll up for the first error message.
echo.
pause
exit /b 1
