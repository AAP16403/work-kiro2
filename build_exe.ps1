Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

Push-Location $PSScriptRoot
try {
  if (-not (Test-Path ".\\.venv\\Scripts\\python.exe")) {
    throw "Missing .venv. Create it first: py -m venv .venv ; .\\.venv\\Scripts\\python.exe -m pip install -r requirements.txt (or pyglet + pyinstaller)."
  }

  $py = ".\\.venv\\Scripts\\python.exe"

  & $py -m pip show pyinstaller *> $null
  if ($LASTEXITCODE -ne 0) {
    Write-Host "Installing PyInstaller into .venv..."
    & $py -m pip install --upgrade pip
    & $py -m pip install pyinstaller
  }

  Write-Host "Building Kiro2Game..."
  & $py -m PyInstaller --noconfirm --clean .\\kiro2_game.spec

  Write-Host ""
  Write-Host "Done."
  Write-Host "Your distributable folder is: .\\dist\\Kiro2Game\\"
  Write-Host "Executable: .\\dist\\Kiro2Game\\Kiro2Game.exe"
}
finally {
  Pop-Location
}

