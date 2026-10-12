<#
.SYNOPSIS
  Smoke test for the Windows build: Plouto.exe must start, stay running, and find its assets.

.DESCRIPTION
  1. dist\Plouto\Plouto.exe must exist. Run build_all.bat first.
  2. asset_manifest.py --list names every asset the code opens. Each one must exist under
     dist\Plouto\_internal, and dist\Plouto\_internal\assets\audio must hold every WAV it names.
  3. Plouto.exe is started, the script waits -WaitSeconds, and the process must still be
     running. The process is then stopped.

  Exit code 0: every check passed. Exit code 1: a check failed or there is no build.

.PARAMETER WaitSeconds
  Seconds to wait after launch before checking that the process is alive (1 to 600, default 8).

.PARAMETER DistDir
  Folder that holds Plouto.exe (default: <repo>\dist\Plouto).

.PARAMETER Python
  Python that runs asset_manifest.py. Default: <repo>\.venv\Scripts\python.exe, then py -3, then python.

.EXAMPLE
  powershell -NoProfile -ExecutionPolicy Bypass -File tools\smoke_exe.ps1 -WaitSeconds 10
#>
[CmdletBinding()]
param(
  [ValidateRange(1, 600)]
  [int]$WaitSeconds = 8,
  [string]$DistDir = "",
  [string]$Python = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
if (-not $DistDir) { $DistDir = Join-Path $RepoRoot "dist\Plouto" }
$ExePath = Join-Path $DistDir "Plouto.exe"
$Internal = Join-Path $DistDir "_internal"
$AudioDir = Join-Path $Internal "assets\audio"

function Stop-Smoke([string]$Message) {
  Write-Host "SMOKE FAIL: $Message"
  exit 1
}

if (-not (Test-Path -LiteralPath $ExePath -PathType Leaf)) {
  Stop-Smoke "no build at $ExePath (run build_all.bat first)"
}
if (-not (Test-Path -LiteralPath $Internal -PathType Container)) {
  Stop-Smoke "missing folder $Internal"
}
if (-not (Test-Path -LiteralPath $AudioDir -PathType Container)) {
  Stop-Smoke "missing audio folder $AudioDir"
}

# Find the Python that lists the referenced assets.
$PyExe = $null
$PyPrefix = @()
$VenvPy = Join-Path $RepoRoot ".venv\Scripts\python.exe"
if ($Python) { $PyExe = $Python }
elseif (Test-Path -LiteralPath $VenvPy -PathType Leaf) { $PyExe = $VenvPy }
elseif (Get-Command py -ErrorAction SilentlyContinue) { $PyExe = "py"; $PyPrefix = @("-3") }
elseif (Get-Command python -ErrorAction SilentlyContinue) { $PyExe = "python" }
if (-not $PyExe) { Stop-Smoke "no Python found to run asset_manifest.py" }

$Manifest = Join-Path $RepoRoot "asset_manifest.py"
$Listing = & $PyExe @PyPrefix $Manifest --list --root $RepoRoot
if ($LASTEXITCODE -ne 0) { Stop-Smoke "asset_manifest.py reports a problem with the source tree (see above)" }
$Referenced = @($Listing | ForEach-Object { "$_".Trim() } | Where-Object { $_ })
if ($Referenced.Count -eq 0) { Stop-Smoke "asset_manifest.py listed no assets" }

# Every asset the code opens must be in the build.
$Missing = @()
foreach ($Rel in $Referenced) {
  $Path = Join-Path $Internal $Rel.Replace("/", "\")
  if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { $Missing += $Rel }
}
foreach ($Rel in $Missing) { Write-Host ("  missing from build: _internal\" + $Rel.Replace("/", "\")) }
if ($Missing.Count -gt 0) { Stop-Smoke ("{0} asset(s) the code opens are not in the build" -f $Missing.Count) }

$WavReferenced = @($Referenced | Where-Object { $_ -like "assets/audio/*.wav" })
$WavBuilt = @(Get-ChildItem -LiteralPath $AudioDir -Filter "*.wav" -File)
Write-Host ("ASSETS OK: {0} referenced files present in _internal; {1} WAV referenced, {2} WAV in assets\audio" -f $Referenced.Count, $WavReferenced.Count, $WavBuilt.Count)

# Start the game, wait, and check that it is still running.
$Proc = $null
$Failure = $null
try {
  Write-Host "Starting $ExePath (wait $WaitSeconds s)"
  # Start the exe directly, not through Start-Process, so HasExited and ExitCode describe the game itself.
  $Info = New-Object System.Diagnostics.ProcessStartInfo
  $Info.FileName = $ExePath
  $Info.WorkingDirectory = $DistDir
  $Info.UseShellExecute = $false
  $Proc = [System.Diagnostics.Process]::Start($Info)
  if (-not $Proc) { throw "the process did not start" }
  Start-Sleep -Seconds $WaitSeconds
  $Proc.Refresh()
  if ($Proc.HasExited) {
    $Failure = "Plouto.exe exited within $WaitSeconds s with exit code $($Proc.ExitCode)"
  }
  else {
    Write-Host "Process $($Proc.Id) is still running after $WaitSeconds s."
  }
}
catch {
  $Failure = "could not start Plouto.exe: $($_.Exception.Message)"
}
finally {
  if ($Proc -and -not $Proc.HasExited) {
    Stop-Process -Id $Proc.Id -Force -ErrorAction SilentlyContinue
    [void]$Proc.WaitForExit(5000)
    Write-Host "Stopped Plouto.exe."
  }
}

if ($Failure) { Stop-Smoke $Failure }
Write-Host "SMOKE PASS: Plouto.exe started, stayed running for $WaitSeconds s, and every referenced asset is in the build."
exit 0
