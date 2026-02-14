@echo off
setlocal EnableExtensions EnableDelayedExpansion

if /i "%APK_TRACE%"=="1" echo on

rem Builds Android APK via WSL + Buildozer.
rem Usage:
rem   android\build_apk.bat            (debug)
rem   android\build_apk.bat release    (release)
rem   android\build_apk.bat debug 1    (debug + clean)
rem   android\build_apk.bat setup      (installs prerequisites in WSL Ubuntu/Debian)
rem   android\build_apk.bat installwsl (attempts to install Ubuntu via WSL)
rem   android\build_apk.bat fixwsl     (tries to repair WSL)
rem   android\build_apk.bat updatewsl  (runs wsl --update)
rem   android\build_apk.bat repairlxss (repairs broken WSL registry entries)

rem Simple progress bar for visualization (best-effort; build itself can still take a long time).
set "PROG_TOTAL=6"
set "PROG_STEP=0"

goto :after_progress_defs

:prog_step
set /a PROG_STEP+=1
set "PROG_LABEL=%~1"
set /a PROG_PERCENT=(PROG_STEP*100)/PROG_TOTAL
set /a PROG_FILLED=(PROG_STEP*20)/PROG_TOTAL
set /a PROG_EMPTY=20-PROG_FILLED
set "PROG_BAR="
for /l %%I in (1,1,!PROG_FILLED!) do set "PROG_BAR=!PROG_BAR!#"
set "PROG_PAD="
for /l %%I in (1,1,!PROG_EMPTY!) do set "PROG_PAD=!PROG_PAD!-"
echo [!PROG_STEP!/!PROG_TOTAL!] [!PROG_BAR!!PROG_PAD!] !PROG_PERCENT!%% !PROG_LABEL!
echo [!PROG_STEP!/!PROG_TOTAL!] !PROG_LABEL! >> "%LOG_FILE%"
exit /b 0

:after_progress_defs

rem Log file (helps diagnose WSL/Buildozer issues).
set "SCRIPT_DIR_WIN=%~dp0"
set "LOG_DIR=%SCRIPT_DIR_WIN%_logs"
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%" >nul 2>nul
set "LOG_TS="
for /f "usebackq delims=" %%T in (`powershell -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmmss" 2^>nul`) do set "LOG_TS=%%T"
if not defined LOG_TS (
  set "LOG_TS=%DATE%_%TIME%"
  set "LOG_TS=%LOG_TS:/=-%"
  set "LOG_TS=%LOG_TS::=-%"
  set "LOG_TS=%LOG_TS: =0%"
)
set "LOG_FILE=%LOG_DIR%\build_apk_%LOG_TS%.log"
echo ==== android\build_apk.bat (%DATE% %TIME%) ==== > "%LOG_FILE%"
echo Args: "%*" >> "%LOG_FILE%"
echo CWD:  "%CD%" >> "%LOG_FILE%"
echo. >> "%LOG_FILE%"

set "MODE=%~1"
if "%MODE%"=="" set "MODE=debug"

set "CLEAN=%~2"
if "%CLEAN%"=="" set "CLEAN=0"

rem Which distro to use.
rem - If WSL_DISTRO is set, we always use it.
rem - Otherwise we run against the default WSL distro.
set "WSL_DISTRO_EFFECTIVE="
if defined WSL_DISTRO set "WSL_DISTRO_EFFECTIVE=%WSL_DISTRO%"
set "WSL_D="
if defined WSL_DISTRO_EFFECTIVE set "WSL_D=-d %WSL_DISTRO_EFFECTIVE%"

echo Logging to: "%LOG_FILE%"
if defined WSL_DISTRO_EFFECTIVE echo WSL_DISTRO=%WSL_DISTRO_EFFECTIVE% >> "%LOG_FILE%"
echo.

call :prog_step "Checking WSL availability"

rem Locate wsl.exe robustly (handles PATH issues and 32-bit redirection).
set "WSL_EXE="
if exist "%SystemRoot%\System32\wsl.exe" set "WSL_EXE=%SystemRoot%\System32\wsl.exe"
if exist "%SystemRoot%\Sysnative\wsl.exe" set "WSL_EXE=%SystemRoot%\Sysnative\wsl.exe"
if not defined WSL_EXE for /f "delims=" %%W in ('where wsl.exe 2^>nul') do if not defined WSL_EXE set "WSL_EXE=%%W"
if not defined WSL_EXE for /f "delims=" %%W in ('where wsl 2^>nul') do if not defined WSL_EXE set "WSL_EXE=%%W"
if not defined WSL_EXE (
  echo ERROR: WSL not found ^(wsl.exe missing^).
  echo - If you installed Ubuntu from the Store, you still need the WSL Windows feature enabled.
  echo - Try from an Admin PowerShell: wsl --install
  echo - Or enable: "Windows Subsystem for Linux" + "Virtual Machine Platform", then reboot.
  echo. >> "%LOG_FILE%"
  echo ERROR: wsl.exe not found. >> "%LOG_FILE%"
  echo SystemRoot=%SystemRoot% >> "%LOG_FILE%"
  echo PATH=!PATH! >> "%LOG_FILE%"
  echo. >> "%LOG_FILE%"
  echo === Diagnostics === >> "%LOG_FILE%"
  ver >> "%LOG_FILE%" 2>&1
  echo. >> "%LOG_FILE%"
  echo where wsl.exe >> "%LOG_FILE%"
  where wsl.exe >> "%LOG_FILE%" 2>&1
  echo where wsl >> "%LOG_FILE%"
  where wsl >> "%LOG_FILE%" 2>&1
  echo. >> "%LOG_FILE%"
  echo See log: "%LOG_FILE%"
  exit /b 1
)

if /i "%APK_TRACE%"=="1" echo Using WSL: "%WSL_EXE%"

echo WSL_EXE=%WSL_EXE% >> "%LOG_FILE%"
echo. >> "%LOG_FILE%"
echo === WSL status === >> "%LOG_FILE%"
"%WSL_EXE%" --status >> "%LOG_FILE%" 2>&1
echo. >> "%LOG_FILE%"
echo === WSL distros (wsl -l -v) === >> "%LOG_FILE%"
"%WSL_EXE%" -l -v >> "%LOG_FILE%" 2>&1
echo. >> "%LOG_FILE%"

call :prog_step "Validating WSL can start the distro"

rem Quick smoke test: can WSL actually start a shell?
if /i "%MODE%"=="installwsl" goto :after_smoke
if /i "%MODE%"=="fixwsl" goto :after_smoke
if /i "%MODE%"=="updatewsl" goto :after_smoke
if /i "%MODE%"=="repairlxss" goto :after_smoke
set "WSL_SMOKE_OUT=%TEMP%\wsl_smoke_%RANDOM%%RANDOM%.txt"
"%WSL_EXE%" %WSL_D% -e bash -lc "true" > "%WSL_SMOKE_OUT%" 2>&1
echo === WSL smoke test (bash -lc true) === >> "%LOG_FILE%"
type "%WSL_SMOKE_OUT%" >> "%LOG_FILE%" 2>&1
echo. >> "%LOG_FILE%"
powershell -NoProfile -Command "$t = Get-Content -Raw -Encoding Unicode '%WSL_SMOKE_OUT%'; if ($t -match 'Failed to attach disk|ext4\\.vhdx|ERROR_PATH_NOT_FOUND|CreateInstance') { exit 0 } else { exit 1 }" >nul 2>nul
if not errorlevel 1 (
  echo ERROR: WSL failed to start the Linux distro.
  echo This often means the distro disk image is missing/corrupted ^(e.g. ext4.vhdx path not found^).
  echo Fix: reinstall the Linux distro or unregister+reinstall it.
  echo --- WSL error ^(from log^) ---
  powershell -NoProfile -Command "Get-Content -Encoding Unicode '%WSL_SMOKE_OUT%' | Select-Object -First 8" 2>nul
  echo See log: "%LOG_FILE%"
  del /q "%WSL_SMOKE_OUT%" >nul 2>nul
  exit /b 1
)
del /q "%WSL_SMOKE_OUT%" >nul 2>nul
:after_smoke

call :prog_step "Checking distro registration"

rem Registry helpers (more reliable than parsing wsl.exe output on some systems).
set "LXSS_KEY=HKCU\Software\Microsoft\Windows\CurrentVersion\Lxss"
set "DEFAULT_GUID="
for /f "tokens=3" %%G in ('reg query "%LXSS_KEY%" /v DefaultDistribution 2^>nul ^| findstr /i "DefaultDistribution"') do set "DEFAULT_GUID=%%G"

set "RUN_OOBE="
if defined DEFAULT_GUID (
  for /f "tokens=3" %%R in ('reg query "%LXSS_KEY%\%DEFAULT_GUID%" /v RunOOBE 2^>nul ^| findstr /i "RunOOBE"') do set "RUN_OOBE=%%R"
)

echo === Lxss default distro registry (if present) === >> "%LOG_FILE%"
if defined DEFAULT_GUID (
  reg query "%LXSS_KEY%\%DEFAULT_GUID%" /v DistributionName >> "%LOG_FILE%" 2>&1
  reg query "%LXSS_KEY%\%DEFAULT_GUID%" /v BasePath >> "%LOG_FILE%" 2>&1
  reg query "%LXSS_KEY%\%DEFAULT_GUID%" /v Version >> "%LOG_FILE%" 2>&1
  reg query "%LXSS_KEY%\%DEFAULT_GUID%" /v State >> "%LOG_FILE%" 2>&1
) else (
  echo DefaultDistribution not found. >> "%LOG_FILE%"
)
echo. >> "%LOG_FILE%"

if /i "%MODE%"=="installwsl" (
  echo Installing WSL + Ubuntu; this may require a reboot...
  set "INSTALL_OK="
  echo === installwsl === >> "%LOG_FILE%"
  rem Prefer a pinned Ubuntu version if available, but keep a fallback.
  "%WSL_EXE%" --install -d Ubuntu-24.04
  if errorlevel 1 (
    rem Common case: Ubuntu already installed (Store app), but wsl --install returns ERROR_ALREADY_EXISTS.
    rem Verify Ubuntu exists via registry (DistributionName) or wsl list.
    "%WSL_EXE%" --install -d Ubuntu >nul 2>nul
    reg query "%LXSS_KEY%" /s /v DistributionName 1>nul 2>nul
    if errorlevel 1 (
      echo ERROR: WSL install failed. Try running this from an elevated terminal, or install WSL manually.
      exit /b 1
    )
    set "INSTALL_OK=1"
  ) else (
    set "INSTALL_OK=1"
  )
  rem Verify Ubuntu shows up as a registered distro (registry is most reliable).
  reg query "%LXSS_KEY%" /s /v DistributionName 2>nul | findstr /i /c:"Ubuntu-24.04" /c:"Ubuntu" >nul 2>nul
  if errorlevel 1 (
    echo Ubuntu did not register correctly; attempting WSL repair...
    call "%~f0" repairlxss
    call "%~f0" fixwsl
    reg query "%LXSS_KEY%" /s /v DistributionName 2>nul | findstr /i /c:"Ubuntu-24.04" /c:"Ubuntu" >nul 2>nul
    if errorlevel 1 (
      echo ERROR: Ubuntu still did not register correctly in WSL.
      echo Try opening Ubuntu once from Start Menu to finish setup, or reinstall Ubuntu/WSL.
      exit /b 1
    )
  )
  echo Done. If Windows asks for a reboot, reboot and then re-run: android\build_apk.bat
  echo Done. >> "%LOG_FILE%"
  exit /b 0
)

if /i "%MODE%"=="fixwsl" (
  echo Attempting WSL repair...
  echo === fixwsl === >> "%LOG_FILE%"
  "%WSL_EXE%" --shutdown >nul 2>nul
  echo Done. Re-run: android\build_apk.bat
  echo Done. >> "%LOG_FILE%"
  exit /b 0
)

if /i "%MODE%"=="updatewsl" (
  echo Updating WSL...
  echo === updatewsl === >> "%LOG_FILE%"
  "%WSL_EXE%" --update
  if errorlevel 1 (
    echo ERROR: wsl --update failed. You may need to run as admin or update WSL from Microsoft Store.
    echo ERROR: wsl --update failed. >> "%LOG_FILE%"
    echo See log: "%LOG_FILE%"
    exit /b 1
  )
  echo Done. Re-run: android\build_apk.bat
  echo Done. >> "%LOG_FILE%"
  exit /b 0
)

if /i "%MODE%"=="repairlxss" (
  call "%~dp0repair_lxss.bat"
  if errorlevel 1 exit /b 1
  echo Done. Re-run: android\build_apk.bat
  exit /b 0
)

rem Make sure at least one distro exists and WSL is healthy enough to run commands.
set "HAS_DISTRO="
set "WSL_LIST_TMP=%TEMP%\wsl_distro_list.txt"
"%WSL_EXE%" -l -q 1>"%WSL_LIST_TMP%" 2>nul
if errorlevel 1 (
  rem Try a couple of automatic repairs then retry once.
  echo WARN: wsl -l -q failed; retrying after shutdown... >> "%LOG_FILE%"
  "%WSL_EXE%" --shutdown >nul 2>nul
  "%WSL_EXE%" -l -q 1>"%WSL_LIST_TMP%" 2>nul
  if errorlevel 1 (
    rem Some WSL installs get stuck with a broken Lxss entry (missing BasePath). Try repairing.
    echo WARN: second wsl -l -q failed; running repairlxss... >> "%LOG_FILE%"
    call "%~f0" repairlxss
    "%WSL_EXE%" -l -q 1>"%WSL_LIST_TMP%" 2>nul
  )
  if errorlevel 1 (
    echo ERROR: WSL failed to list distros.
    echo Try: android\build_apk.bat fixwsl
    echo If that doesn't help, try: android\build_apk.bat updatewsl
    echo If you see BasePath errors, try: android\build_apk.bat repairlxss
    echo If that fails, reinstall WSL / install a distro manually.
    echo ERROR: WSL failed to list distros. >> "%LOG_FILE%"
    echo See log: "%LOG_FILE%"
    del /q "%WSL_LIST_TMP%" >nul 2>nul
    exit /b 1
  )
)
for /f "usebackq delims=" %%D in ("%WSL_LIST_TMP%") do set "HAS_DISTRO=1"
del /q "%WSL_LIST_TMP%" >nul 2>nul
if not defined HAS_DISTRO (
  rem Fallback: check registry for any distro entries (some setups output UTF-16 to files).
  reg query "%LXSS_KEY%" /s /v DistributionName 1>nul 2>nul
  if errorlevel 1 (
    echo No WSL Linux distribution is installed; attempting to install Ubuntu...
    echo No WSL distro found; attempting installwsl... >> "%LOG_FILE%"
    call "%~f0" installwsl
    if errorlevel 1 exit /b 1
    echo Ubuntu installed. Launch it once from Start Menu to finish setup, then re-run: android\build_apk.bat
    echo Ubuntu installed; requires first run. >> "%LOG_FILE%"
    exit /b 1
  )
)

if /i "%RUN_OOBE%"=="0x1" (
  echo Ubuntu is installed but needs first-run setup before it can run build commands.
  if defined WSL_DISTRO_EFFECTIVE (
    echo Launch it once from Start Menu, or run: wsl -d "%WSL_DISTRO_EFFECTIVE%"
  ) else (
    echo Launch it once from Start Menu, or run: wsl
  )
  echo After you create a username/password, re-run: android\build_apk.bat setup
  echo Ubuntu needs first-run setup ^(RunOOBE=0x1^). >> "%LOG_FILE%"
  echo See log: "%LOG_FILE%"
  exit /b 1
)

set "SCRIPT_DIR=%~dp0"
set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"
echo SCRIPT_DIR=%SCRIPT_DIR% >> "%LOG_FILE%"

call :prog_step "Resolving repo path inside WSL"

rem Convert Windows path to WSL path.
set "WSL_ANDROID_DIR="
if /i "%SCRIPT_DIR:~1,2%"==":\" (
  rem Fast-path: convert drive-letter paths without invoking wslpath (avoids encoding issues in for /f).
  set "WIN_DRIVE_LC="
  for /f "delims=" %%L in ('powershell -NoProfile -Command "('%SCRIPT_DIR:~0,1%').ToLowerInvariant()" 2^>nul') do set "WIN_DRIVE_LC=%%L"
  set "WIN_REST=%SCRIPT_DIR:~2%"
  set "WIN_REST=!WIN_REST:\=/!"
  set "WSL_ANDROID_DIR=/mnt/!WIN_DRIVE_LC!!WIN_REST!"
) else (
  rem Fallback: ask the distro to convert the path and decode output via PowerShell.
  set "WSL_WSLPATH_TMP=%TEMP%\wslpath_%RANDOM%%RANDOM%.txt"
  "%WSL_EXE%" %WSL_D% wslpath -a "%SCRIPT_DIR%" 1>"%WSL_WSLPATH_TMP%" 2>nul
  for /f "usebackq delims=" %%P in (`powershell -NoProfile -Command "try { $t = Get-Content -Raw -Encoding Unicode '%WSL_WSLPATH_TMP%'; if(-not $t){ $t = Get-Content -Raw '%WSL_WSLPATH_TMP%' }; $t = $t.Trim(); if($t){ $t } } catch { }" 2^>nul`) do set "WSL_ANDROID_DIR=%%P"
  del /q "%WSL_WSLPATH_TMP%" >nul 2>nul
)
echo WSL_ANDROID_DIR=%WSL_ANDROID_DIR% >> "%LOG_FILE%"
if not defined WSL_ANDROID_DIR (
  echo ERROR: Failed to resolve the android folder path inside WSL.
  echo See log: "%LOG_FILE%"
  exit /b 1
)

call :prog_step "Running Android build (WSL/Buildozer)"

echo Building Android %MODE% (clean=%CLEAN%)...
echo NOTE: First build will download Android SDK/NDK and may take a while.
echo === Build command === >> "%LOG_FILE%"
echo WSL_ANDROID_DIR=%WSL_ANDROID_DIR% >> "%LOG_FILE%"
set "WSL_LINK_ROOT=%KIRO2_WSL_LINK_ROOT%"
echo WSL_LINK_ROOT=%WSL_LINK_ROOT% >> "%LOG_FILE%"
"%WSL_EXE%" %WSL_D% -e bash -lc "set -e; SRC=\"%WSL_ANDROID_DIR%\"; RUN_DIR=\"$SRC\"; if [[ \"$SRC\" == *' '* ]]; then ROOT=\"$(cd \"$SRC/..\" && pwd -P)\"; LINK_ROOT=\"%WSL_LINK_ROOT%\"; if [[ -z \"$LINK_ROOT\" ]]; then LINK_ROOT=\"$(mktemp -d)\"; else rm -f \"$LINK_ROOT\"; fi; ln -s \"$ROOT\" \"$LINK_ROOT\"; RUN_DIR=\"$LINK_ROOT/android\"; fi; cd \"$RUN_DIR\" && chmod +x ./build_apk.sh ./setup_build_env.sh && ./build_apk.sh \"%MODE%\" \"%CLEAN%\"" >> "%LOG_FILE%" 2>&1
if errorlevel 1 (
  call :sanitize_log
  echo ERROR: Build failed. The full log is available at: %LOG_FILE%
  echo ERROR: build command failed. >> "%LOG_FILE%"
  if exist "%LOG_FILE%.txt" echo Clean log copy: "%LOG_FILE%.txt"
  exit /b 1
)

call :prog_step "Done"
call :sanitize_log

echo Done. Check: android\bin\
echo Done. >> "%LOG_FILE%"
echo Log: "%LOG_FILE%"
if exist "%LOG_FILE%.txt" echo Clean log: "%LOG_FILE%.txt"
exit /b 0

:sanitize_log
powershell -NoProfile -Command "$p='%LOG_FILE%'; if(Test-Path $p){ $raw=[System.IO.File]::ReadAllText($p); $raw=$raw -replace \"`0\",''; $raw=[regex]::Replace($raw, \"`e\\[[0-9;?]*[ -/]*[@-~]\", ''); [System.IO.File]::WriteAllText($p+'.txt',$raw,[Text.UTF8Encoding]::new($false)) }" >nul 2>nul
exit /b 0















