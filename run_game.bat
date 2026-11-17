@echo off
setlocal enableextensions
cd /d "%~dp0"

set "RELEASE_EXE=%~dp0release\Plouto\Plouto.exe"
if exist "%RELEASE_EXE%" (
  "%RELEASE_EXE%" %*
  if errorlevel 1 (
    echo.
    echo The game exited with an error.
    if not defined NO_PAUSE pause
    exit /b 1
  )
  exit /b 0
)

where cargo >nul 2>&1
if errorlevel 1 (
  echo [ERROR] Rust and Cargo were not found.
  echo Install the stable Rust toolchain, then launch the game again.
  pause
  exit /b 1
)

cargo run --bin plouto -- %*
if errorlevel 1 (
  echo.
  echo The game exited with an error.
  if not defined NO_PAUSE pause
  exit /b 1
)
