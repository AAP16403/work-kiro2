@echo off
setlocal EnableExtensions

echo Repairing WSL registry entries (Lxss)...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0fix_wsl.ps1" -Force
if errorlevel 1 (
  echo ERROR: Repair failed. Try running:
  echo   powershell -ExecutionPolicy Bypass -File android\\fix_wsl.ps1 -Force
  exit /b 1
)

echo Repair complete.
exit /b 0


