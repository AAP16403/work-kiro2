param(
  [switch]$Force
)

$ErrorActionPreference = "Stop"

function Write-Info($msg) { Write-Host $msg }
function Write-Warn($msg) { Write-Host $msg -ForegroundColor Yellow }
function Write-Err($msg) { Write-Host $msg -ForegroundColor Red }

$lxssRoot = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Lxss"
if (-not (Test-Path $lxssRoot)) {
  Write-Info "No Lxss registry key found; nothing to repair."
  exit 0
}

$subKeys = Get-ChildItem $lxssRoot -ErrorAction Stop | Where-Object { $_.PSChildName -match '^\{[0-9a-fA-F-]+\}$' }
if (-not $subKeys) {
  Write-Info "No WSL distro registry entries found; nothing to repair."
  exit 0
}

$broken = @()
foreach ($k in $subKeys) {
  $props = Get-ItemProperty -LiteralPath $k.PSPath -ErrorAction Stop
  $hasBasePath = $props.PSObject.Properties.Name -contains "BasePath"
  if (-not $hasBasePath) {
    $broken += [pscustomobject]@{
      KeyPath = $k.PSPath
      Guid = $k.PSChildName
      DistributionName = ($props.DistributionName | ForEach-Object { "$_" })
      OsVersion = ($props.OsVersion | ForEach-Object { "$_" })
      Modern = ($props.Modern | ForEach-Object { "$_" })
    }
  }
}

if (-not $broken) {
  Write-Info "No broken WSL registry entries found (all have BasePath)."
  exit 0
}

Write-Warn "Found broken WSL distro registry entries (missing BasePath):"
$broken | Format-Table Guid, DistributionName, OsVersion, Modern | Out-String | Write-Host

if (-not $Force) {
  Write-Warn "This script will BACK UP your Lxss registry key and then delete only the broken entries."
  Write-Warn "Re-run with -Force to apply:  powershell -ExecutionPolicy Bypass -File android\\fix_wsl.ps1 -Force"
  exit 2
}

$backupDir = Join-Path $PSScriptRoot "_wsl_backups"
New-Item -ItemType Directory -Force -Path $backupDir | Out-Null
$ts = Get-Date -Format "yyyyMMdd_HHmmss"
$backupPath = Join-Path $backupDir "Lxss_$ts.reg"

Write-Info "Backing up registry key to: $backupPath"
& reg.exe export "HKCU\Software\Microsoft\Windows\CurrentVersion\Lxss" "$backupPath" /y | Out-Null

foreach ($b in $broken) {
  Write-Info "Deleting broken distro key: $($b.Guid) ($($b.DistributionName))"
  Remove-Item -LiteralPath $b.KeyPath -Recurse -Force -ErrorAction Stop
}

# Fix DefaultDistribution if it points at a deleted key.
$defaultGuid = (Get-ItemProperty -LiteralPath $lxssRoot -ErrorAction Stop).DefaultDistribution
if ($defaultGuid) {
  $exists = Test-Path (Join-Path $lxssRoot $defaultGuid)
  if (-not $exists) {
    Write-Info "DefaultDistribution referenced deleted key; clearing DefaultDistribution."
    Remove-ItemProperty -LiteralPath $lxssRoot -Name "DefaultDistribution" -ErrorAction SilentlyContinue
  }
}

Write-Info "Shutting down WSL..."
& wsl.exe --shutdown | Out-Null

Write-Info "Repair complete."
Write-Info "Next: run android\\build_apk.bat again. If Ubuntu isn't installed, run android\\build_apk.bat installwsl."
