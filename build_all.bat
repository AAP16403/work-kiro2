@echo off
setlocal enableextensions

cd /d "%~dp0"
set "APP_NAME=Plouto"
set "SPEC_FILE=kiro2_game.spec"
set "PY_EXE=.venv\Scripts\python.exe"
set "BUILD_PS1=build_exe.ps1"
set "PS_EXE=powershell"
set "DIST_DIR=dist\%APP_NAME%"
set "DIST_EXE=%DIST_DIR%\%APP_NAME%.exe"

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
  if not exist "%PY_EXE%" (
    echo ERROR: Virtual environment creation did not produce %PY_EXE%
    goto :fail
  )
)

if not exist "%SPEC_FILE%" (
  echo ERROR: Missing spec file: %SPEC_FILE%
  goto :fail
)
if not exist "%BUILD_PS1%" (
  echo ERROR: Missing build script: %BUILD_PS1%
  goto :fail
)
where %PS_EXE% >nul 2>nul
if errorlevel 1 (
  echo ERROR: PowerShell not found. Required for build and zip steps.
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
"%PY_EXE%" -m pip install -U pip panda3d pyinstaller
if errorlevel 1 goto :fail

echo.
echo Cleaning stale build outputs...
if exist "build\kiro2_game" rmdir /s /q "build\kiro2_game"
if exist "dist\Kiro2Game" rmdir /s /q "dist\Kiro2Game"
if exist "dist\Kiro2Game.zip" del /f /q "dist\Kiro2Game.zip"
if exist "dist\%APP_NAME%" rmdir /s /q "dist\%APP_NAME%"
if exist "dist\%APP_NAME%.zip" del /f /q "dist\%APP_NAME%.zip"

echo.
echo Running quick syntax validation...
"%PY_EXE%" -c "import pathlib, py_compile; [py_compile.compile(str(p), doraise=True) for p in pathlib.Path('.').rglob('*.py') if '.venv' not in p.parts and 'build' not in p.parts and 'dist' not in p.parts and '__pycache__' not in p.parts]"
if errorlevel 1 goto :fail

echo.
echo Building executable ^(PyInstaller^)...
%PS_EXE% -NoProfile -ExecutionPolicy Bypass -File ".\%BUILD_PS1%"
if errorlevel 1 goto :fail

if not exist "%DIST_DIR%" (
  echo ERROR: Build completed but output folder is missing: %DIST_DIR%
  goto :fail
)
if not exist "%DIST_EXE%" (
  echo ERROR: Build completed but executable is missing: %DIST_EXE%
  goto :fail
)

echo.
echo Creating .zip...
%PS_EXE% -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference = 'Stop'; Push-Location '%CD%\\dist'; try { if (Test-Path '.\\%APP_NAME%.zip') { Remove-Item -Force '.\\%APP_NAME%.zip' }; $ok = $false; for ($i = 1; $i -le 5; $i++) { try { Compress-Archive -Path '.\\%APP_NAME%' -DestinationPath '.\\%APP_NAME%.zip' -Force; $ok = $true; break } catch { if ($i -eq 5) { throw }; Start-Sleep -Milliseconds (300 * $i) } }; if (-not $ok) { throw 'ZIP creation failed.' }; if (-not (Test-Path '.\\%APP_NAME%.zip')) { throw 'ZIP file not found after creation.' } } finally { Pop-Location }"
if errorlevel 1 goto :fail

echo.
echo SUCCESS.
echo Output folder: %CD%\dist\%APP_NAME%\
echo EXE: %CD%\dist\%APP_NAME%\%APP_NAME%.exe
echo ZIP: %CD%\dist\%APP_NAME%.zip
echo.
if not defined NO_PAUSE pause
exit /b 0

:fail
echo.
echo FAILED. Scroll up for the first error message.
echo.
if not defined NO_PAUSE pause
exit /b 1
