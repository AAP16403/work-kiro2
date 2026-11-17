$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.IO.Compression.FileSystem

function Get-Sha256FromStream([System.IO.Stream]$Stream) {
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try { return [System.BitConverter]::ToString($sha.ComputeHash($Stream)).Replace('-', '').ToLowerInvariant() }
    finally { $sha.Dispose() }
}

$workspace = Split-Path -Parent $PSScriptRoot
$releaseRoot = [System.IO.Path]::GetFullPath((Join-Path $workspace 'release'))
$bundle = Join-Path $releaseRoot 'Plouto'
$output = Join-Path $releaseRoot 'Plouto_for_friend.zip'
$stage = Join-Path $releaseRoot ('.friend-stage-' + [Guid]::NewGuid().ToString('N'))
$stageZip = Join-Path $stage 'Plouto_for_friend.zip'
$stageDir = Join-Path $stage 'package'
$backup = Join-Path $stage 'previous.zip'

try {
    foreach ($required in @('Plouto.exe', 'laser-gun_38685.ico', 'assets')) {
        if (-not (Test-Path -LiteralPath (Join-Path $bundle $required))) {
            throw "Rust release bundle is incomplete; missing $required. Run build_all.bat first."
        }
    }
    New-Item -ItemType Directory -Path $stageDir -Force | Out-Null
    Copy-Item -LiteralPath (Join-Path $bundle 'Plouto.exe') -Destination (Join-Path $stageDir 'Plouto.exe')
    Copy-Item -LiteralPath (Join-Path $bundle 'laser-gun_38685.ico') -Destination (Join-Path $stageDir 'laser-gun_38685.ico')
    Copy-Item -LiteralPath (Join-Path $bundle 'assets') -Destination (Join-Path $stageDir 'assets') -Recurse
    $readme = @(
        'PLOUTO - Stellar Survival', 'Windows game build', '',
        'Extract this ZIP into a folder, then open Plouto.exe.',
        'Keep the executable, icon, and assets folder together. No Rust installation is needed.', '',
        'Move: WASD or arrow keys', 'Aim and fire: mouse and left click',
        'Dash: Space    Boost: Shift    Ultra: Q or right click    Pause: Escape', '',
        'Gamepad (Xbox layout): Left stick move, Right stick aim, fire with RT, RB, or pushing the right stick',
        'Dash: A    Boost: LT or LB    Ultra: Y    Pause: Start', 'Menus: D-pad or left stick, A confirm, B back, Start for Escape',
        'Controllers are detected when plugged in, including mid-game. Vibration and stick deadzone are in Settings.', '',
        'Heavy Cannon, Flak, and the late-game Siege Mortar reload between volleys; the weapon chip shows reload progress.',
        'Powerful weapon pickups last for a short burst, then restore your regular weapon.', '',
        'Progress and settings are stored in %LOCALAPPDATA%\Plouto and are not included in this ZIP.'
    ) -join [Environment]::NewLine
    [System.IO.File]::WriteAllText((Join-Path $stageDir 'README.txt'), $readme, [System.Text.UTF8Encoding]::new($false))
    $releaseManifest = Get-Content -LiteralPath (Join-Path $bundle 'MANIFEST.json') -Raw | ConvertFrom-Json
    $manifestFiles = @(Get-ChildItem -LiteralPath $stageDir -File -Recurse | Sort-Object FullName | ForEach-Object {
        [ordered]@{
            path = $_.FullName.Substring($stageDir.Length).TrimStart('\').Replace('\', '/')
            size = $_.Length
            sha256 = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
        }
    })
    $friendManifest = [ordered]@{
        formatVersion = $releaseManifest.formatVersion
        product = $releaseManifest.product
        releaseVersion = $releaseManifest.releaseVersion
        simulationRulesVersion = $releaseManifest.simulationRulesVersion
        sourceRevision = $releaseManifest.sourceRevision
        sourceDirty = $releaseManifest.sourceDirty
        createdUtc = $releaseManifest.createdUtc
        executable = 'Plouto.exe'
        executableSha256 = $releaseManifest.executableSha256
        buildId = $releaseManifest.buildId
        files = $manifestFiles
    }
    [System.IO.File]::WriteAllText((Join-Path $stageDir 'MANIFEST.json'), ($friendManifest | ConvertTo-Json -Depth 6), [System.Text.UTF8Encoding]::new($false))
    [System.IO.Compression.ZipFile]::CreateFromDirectory($stageDir, $stageZip, [System.IO.Compression.CompressionLevel]::Optimal, $false)

    $archive = [System.IO.Compression.ZipFile]::OpenRead($stageZip)
    try {
        $names = @($archive.Entries | ForEach-Object { $_.FullName })
        foreach ($required in @('Plouto.exe', 'laser-gun_38685.ico', 'README.txt', 'MANIFEST.json')) {
            if ($names -notcontains $required) { throw "Friend archive is missing $required." }
        }
        if (-not ($names | Where-Object { $_.StartsWith('assets/', [System.StringComparison]::Ordinal) })) {
            throw 'Friend archive contains no game assets.'
        }
        if ($names | Where-Object { $_ -match '(^|/)(GAME_IMPROVEMENT|ENEMY_BEHAVIOR|WEAPON_OUTPUT)|visual_reviews|\.sav$|settings\.json$' }) {
            throw 'Friend archive contains private progress or development-only files.'
        }
        foreach ($file in $manifestFiles) {
            $entry = $archive.GetEntry($file.path)
            if ($null -eq $entry) { throw "Friend archive is missing manifest file '$($file.path)'." }
            $stream = $entry.Open()
            try { $zipHash = Get-Sha256FromStream $stream } finally { $stream.Dispose() }
            if ($zipHash -ne $file.sha256) { throw "Friend archive content hash check failed for '$($file.path)'." }
        }
        $entry = $archive.GetEntry('Plouto.exe')
        $stream = $entry.Open()
        try { $zipHash = Get-Sha256FromStream $stream } finally { $stream.Dispose() }
        $sourceHash = (Get-FileHash -LiteralPath (Join-Path $bundle 'Plouto.exe') -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($zipHash -ne $sourceHash) { throw 'Friend archive executable hash does not match the release bundle.' }
    } finally { $archive.Dispose() }

    $hadPrevious = Test-Path -LiteralPath $output
    if ($hadPrevious) { Move-Item -LiteralPath $output -Destination $backup }
    try {
        Move-Item -LiteralPath $stageZip -Destination $output
    } catch {
        if ($hadPrevious -and (Test-Path -LiteralPath $backup)) { Move-Item -LiteralPath $backup -Destination $output }
        throw
    }
    if (Test-Path -LiteralPath $backup) { Remove-Item -LiteralPath $backup -Force }
    Write-Output "Friend package ready: $output"
} finally {
    if (Test-Path -LiteralPath $stage) { Remove-Item -LiteralPath $stage -Recurse -Force }
}
