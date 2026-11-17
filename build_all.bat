@echo off
setlocal enableextensions
cd /d "%~dp0"

where cargo >nul 2>&1
if errorlevel 1 (
  echo [ERROR] Rust and Cargo were not found.
  echo Install the stable Rust toolchain, then run this build again.
  goto :fail
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\build_release.ps1"
if errorlevel 1 goto :fail

echo.
echo Rust release build and both archives are ready in %~dp0release
if not defined NO_PAUSE pause
exit /b 0

:fail
echo.
echo Build failed. Existing release archives were preserved unless publication completed.
if not defined NO_PAUSE pause
exit /b 1
