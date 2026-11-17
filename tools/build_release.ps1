$ErrorActionPreference = 'Stop'

$workspace = Split-Path -Parent $PSScriptRoot
$releaseRoot = [System.IO.Path]::GetFullPath((Join-Path $workspace 'release'))
$transactionId = [Guid]::NewGuid().ToString('N')
$stageRoot = [System.IO.Path]::GetFullPath((Join-Path $releaseRoot ".release-stage-$transactionId"))
$stagePrefix = $releaseRoot.TrimEnd('\') + '\'
if (-not $stageRoot.StartsWith($stagePrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw 'Release staging path escaped the release directory.'
}

$stageBundle = Join-Path $stageRoot 'Plouto'
$stageFriend = Join-Path $stageRoot 'friend'
$stageRustZip = Join-Path $stageRoot 'Plouto.zip'
$stageFriendZip = Join-Path $stageRoot 'Plouto_for_friend.zip'
$finals = @(
    @{ Stage = $stageBundle; Final = Join-Path $releaseRoot 'Plouto'; IsDirectory = $true },
    @{ Stage = $stageRustZip; Final = Join-Path $releaseRoot 'Plouto.zip'; IsDirectory = $false },
    @{ Stage = $stageFriendZip; Final = Join-Path $releaseRoot 'Plouto_for_friend.zip'; IsDirectory = $false }
)

function Get-Sha256FromStream([System.IO.Stream]$Stream) {
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try {
        return [System.BitConverter]::ToString($sha.ComputeHash($Stream)).Replace('-', '').ToLowerInvariant()
    } finally {
        $sha.Dispose()
    }
}

function Get-RelativeBundlePath([string]$Root, [string]$FullPath) {
    return $FullPath.Substring($Root.TrimEnd('\').Length + 1).Replace('\', '/')
}

function Assert-FullArchive([string]$ArchivePath, [string]$ExecutableHash, [object[]]$ManifestFiles) {
    $archive = [System.IO.Compression.ZipFile]::OpenRead($ArchivePath)
    try {
        $entryMap = @{}
        foreach ($entry in $archive.Entries) {
            $entryMap[$entry.FullName.Replace('\', '/')] = $entry
        }
        foreach ($required in @(
            'Plouto.exe', 'Plouto-Open-Arena.exe', 'README.md', 'docs/plans/GAME_IMPROVEMENT_PLAN.md',
            'docs/reports/GAME_IMPROVEMENT_REPORT.md', 'MANIFEST.json', 'Cargo.toml', 'Cargo.lock',
            'plouto_rs/Cargo.toml', 'plouto_rs/src/main.rs', 'archive/python/ARCHIVE_INFO.md',
            'benchmarks/profile_sim_baseline.json', 'benchmarks/profile_sim_repeat.json'
        )) {
            if (-not $entryMap.ContainsKey($required)) {
                throw "Release archive is missing required entry '$required'."
            }
        }
        if (-not ($entryMap.Keys | Where-Object { $_.StartsWith('assets/', [System.StringComparison]::Ordinal) })) {
            throw 'Release archive does not contain the game assets.'
        }
        if ($entryMap.Keys | Where-Object { $_ -match '(^|/)(progress|user_settings|high_scores)\.json$|\.sav$' }) {
            throw 'Release archive contains local progress or settings data.'
        }
        foreach ($name in @('Plouto.exe', 'Plouto-Open-Arena.exe')) {
            $stream = $entryMap[$name].Open()
            try { $hash = Get-Sha256FromStream $stream } finally { $stream.Dispose() }
            if ($hash -ne $ExecutableHash) {
                throw "Executable hash check failed for '$name'."
            }
        }
        foreach ($file in $ManifestFiles) {
            $entry = $entryMap[$file.path]
            if ($null -eq $entry) {
                throw "Release archive is missing manifest file '$($file.path)'."
            }
            $stream = $entry.Open()
            try { $hash = Get-Sha256FromStream $stream } finally { $stream.Dispose() }
            if ($hash -ne $file.sha256) {
                throw "Release archive content hash check failed for '$($file.path)'."
            }
        }
    } finally {
        $archive.Dispose()
    }
}

function Assert-FriendArchive([string]$ArchivePath, [string]$ExecutableHash, [object[]]$ManifestFiles) {
    $archive = [System.IO.Compression.ZipFile]::OpenRead($ArchivePath)
    try {
        $entryMap = @{}
        foreach ($entry in $archive.Entries) {
            $entryMap[$entry.FullName.Replace('\', '/')] = $entry
        }
        $names = @($entryMap.Keys)
        foreach ($required in @('Plouto.exe', 'laser-gun_38685.ico', 'README.txt', 'MANIFEST.json')) {
            if ($names -notcontains $required) {
                throw "Friend archive is missing required entry '$required'."
            }
        }
        if (-not ($names | Where-Object { $_.StartsWith('assets/', [System.StringComparison]::Ordinal) })) {
            throw 'Friend archive does not contain the game assets.'
        }
        if ($names | Where-Object { $_ -match '(^|/)(GAME_IMPROVEMENT|ENEMY_BEHAVIOR|WEAPON_OUTPUT)|visual_reviews|(^|/)benchmarks/|\.sav$|settings\.json$' }) {
            throw 'Friend archive contains a development report, review image, or local save/settings file.'
        }
        $stream = $entryMap['Plouto.exe'].Open()
        try { $hash = Get-Sha256FromStream $stream } finally { $stream.Dispose() }
        if ($hash -ne $ExecutableHash) {
            throw 'Friend archive executable hash check failed.'
        }
        foreach ($file in $ManifestFiles) {
            $entry = $entryMap[$file.path]
            if ($null -eq $entry) { throw "Friend archive is missing manifest file '$($file.path)'." }
            $stream = $entry.Open()
            try { $hash = Get-Sha256FromStream $stream } finally { $stream.Dispose() }
            if ($hash -ne $file.sha256) { throw "Friend archive content hash check failed for '$($file.path)'." }
        }
    } finally {
        $archive.Dispose()
    }
}

function Promote-ReleaseSet([object[]]$Items, [string]$Root, [string]$Stage) {
    $backups = [System.Collections.Generic.List[object]]::new()
    $installed = [System.Collections.Generic.List[object]]::new()
    try {
        foreach ($item in $Items) {
            $finalPath = [System.IO.Path]::GetFullPath($item.Final)
            if (-not $finalPath.StartsWith($Root.TrimEnd('\') + '\', [System.StringComparison]::OrdinalIgnoreCase)) {
                throw "Release output path escaped the release directory: $finalPath"
            }
            if (Test-Path -LiteralPath $finalPath) {
                $backupPath = Join-Path $Stage ('.backup-' + [System.IO.Path]::GetFileName($finalPath) + '-' + [Guid]::NewGuid().ToString('N'))
                Move-Item -LiteralPath $finalPath -Destination $backupPath
                $backups.Add(@{ Final = $finalPath; Backup = $backupPath; IsDirectory = $item.IsDirectory })
            }
            Move-Item -LiteralPath $item.Stage -Destination $finalPath
            $installed.Add(@{ Final = $finalPath; IsDirectory = $item.IsDirectory })
        }
    } catch {
        for ($index = $installed.Count - 1; $index -ge 0; $index--) {
            $item = $installed[$index]
            if (Test-Path -LiteralPath $item.Final) {
                Remove-Item -LiteralPath $item.Final -Recurse:$item.IsDirectory -Force
            }
        }
        for ($index = $backups.Count - 1; $index -ge 0; $index--) {
            $item = $backups[$index]
            if (Test-Path -LiteralPath $item.Backup) {
                Move-Item -LiteralPath $item.Backup -Destination $item.Final
            }
        }
        throw
    }
    foreach ($item in $backups) {
        if (Test-Path -LiteralPath $item.Backup) {
            Remove-Item -LiteralPath $item.Backup -Recurse:$item.IsDirectory -Force
        }
    }
}

try {
    New-Item -ItemType Directory -Path $stageRoot -Force | Out-Null
    $cargoText = Get-Content -LiteralPath (Join-Path $workspace 'plouto_rs\Cargo.toml') -Raw
    if ($cargoText -notmatch '(?m)^version\s*=\s*"([^"]+)"') {
        throw 'Unable to read the Rust package version from Cargo.toml.'
    }
    $releaseVersion = $Matches[1]
    $replaySource = Get-Content -LiteralPath (Join-Path $workspace 'plouto_rs\src\sim\replay.rs') -Raw
    if ($replaySource -notmatch '(?m)^pub const SIMULATION_RULES_VERSION:\s*u32\s*=\s*(\d+)') {
        throw 'Unable to read SIMULATION_RULES_VERSION for the release manifest.'
    }
    $rulesVersion = [int]$Matches[1]
    $sourceRevision = $null
    $sourceDirty = $null
    $gitCommand = Get-Command git -ErrorAction SilentlyContinue
    if ($gitCommand) {
        $revisionLines = @(& $gitCommand.Source -C $workspace rev-parse --verify HEAD 2>$null)
        if ($LASTEXITCODE -eq 0 -and $revisionLines.Count -gt 0) {
            $sourceRevision = [string]$revisionLines[0]
            $dirtyLines = @(& $gitCommand.Source -C $workspace status --porcelain --untracked-files=normal 2>$null)
            if ($LASTEXITCODE -eq 0) {
                $sourceDirty = $dirtyLines.Count -gt 0
            }
        }
    }
    $manifestPath = Join-Path $workspace 'Cargo.toml'
    $cargoCommand = Get-Command cargo -ErrorAction Stop
    & $cargoCommand.Source build --release --bin plouto --manifest-path $manifestPath
    if ($LASTEXITCODE -ne 0) {
        throw "Rust release build failed with exit code $LASTEXITCODE."
    }

    New-Item -ItemType Directory -Path $stageBundle -Force | Out-Null
    New-Item -ItemType Directory -Path (Join-Path $stageBundle 'visual_reviews') -Force | Out-Null
    $profileBaselinePath = Join-Path $releaseRoot 'profile_sim_baseline.json'
    $profileRepeatPath = Join-Path $releaseRoot 'profile_sim_repeat.json'
    foreach ($profilePath in @($profileBaselinePath, $profileRepeatPath)) {
        if (-not (Test-Path -LiteralPath $profilePath -PathType Leaf)) {
            throw "Required headless performance profile is missing: $profilePath"
        }
    }
    $profileBaseline = Get-Content -LiteralPath $profileBaselinePath -Raw | ConvertFrom-Json
    $profileRepeat = Get-Content -LiteralPath $profileRepeatPath -Raw | ConvertFrom-Json
    foreach ($profile in @($profileBaseline, $profileRepeat)) {
        if ($profile.kind -ne 'headless-rust-simulation-profile' -or [int]$profile.rules_version -ne $rulesVersion) {
            throw 'Headless performance profile kind or simulation-rules version does not match this release.'
        }
    }
    if ($profileBaseline.scenarios.Count -ne $profileRepeat.scenarios.Count) {
        throw 'Headless performance profile runs have different scenario counts.'
    }
    for ($scenarioIndex = 0; $scenarioIndex -lt $profileBaseline.scenarios.Count; $scenarioIndex++) {
        $baselineScenario = $profileBaseline.scenarios[$scenarioIndex]
        $repeatScenario = $profileRepeat.scenarios[$scenarioIndex]
        $baselineHashes = [string]::Join('|', [string[]]@($baselineScenario.checkpoints))
        $repeatHashes = [string]::Join('|', [string[]]@($repeatScenario.checkpoints))
        if ($baselineScenario.name -ne $repeatScenario.name -or $baselineHashes -cne $repeatHashes) {
            throw "Headless performance profile state checkpoints differ for scenario index $scenarioIndex."
        }
    }
    $stageBenchmarks = Join-Path $stageBundle 'benchmarks'
    New-Item -ItemType Directory -Path $stageBenchmarks -Force | Out-Null
    Copy-Item -LiteralPath $profileBaselinePath -Destination (Join-Path $stageBenchmarks 'profile_sim_baseline.json')
    Copy-Item -LiteralPath $profileRepeatPath -Destination (Join-Path $stageBenchmarks 'profile_sim_repeat.json')
    $bossProfileBaselinePath = Join-Path $releaseRoot 'boss_profile_baseline.json'
    $bossProfileAfterPath = Join-Path $releaseRoot 'boss_profile_after.json'
    if ((Test-Path -LiteralPath $bossProfileBaselinePath -PathType Leaf) -and (Test-Path -LiteralPath $bossProfileAfterPath -PathType Leaf)) {
        Copy-Item -LiteralPath $bossProfileBaselinePath -Destination (Join-Path $stageBenchmarks 'boss_profile_baseline.json')
        Copy-Item -LiteralPath $bossProfileAfterPath -Destination (Join-Path $stageBenchmarks 'boss_profile_after.json')
    }
    Copy-Item -LiteralPath (Join-Path $workspace 'target\release\plouto.exe') -Destination (Join-Path $stageBundle 'Plouto.exe')
    Copy-Item -LiteralPath (Join-Path $stageBundle 'Plouto.exe') -Destination (Join-Path $stageBundle 'Plouto-Open-Arena.exe')
    Copy-Item -LiteralPath (Join-Path $workspace 'assets') -Destination (Join-Path $stageBundle 'assets') -Recurse
    Copy-Item -LiteralPath (Join-Path $workspace 'laser-gun_38685.ico') -Destination (Join-Path $stageBundle 'laser-gun_38685.ico')
    foreach ($document in @(
        'README.md', 'docs/README.md', 'docs/plans/GAME_IMPROVEMENT_PLAN.md', 'docs/plans/ENEMY_AI_PLAN.md',
        'docs/reports/GAME_IMPROVEMENT_REPORT.md', 'docs/reports/ENEMY_AND_BOSS_OVERHAUL_REPORT.md',
        'docs/reports/CHARACTER_RENDER_AUDIT.md', 'docs/reports/CHANGELOG.md',
        'docs/design/ENEMY_BEHAVIOR_SHEETS.md', 'docs/design/WEAPON_OUTPUT_LEDGER.md', 'docs/design/SIMULATION_CLOCKS.md',
        'docs/design/LEVEL_DESIGN_AND_DIFFICULTY.md', 'docs/design/CHARACTER_ART_SPECIFICATIONS.md',
        'docs/design/ANIMATION_STATE_MAP.md', 'docs/design/ACHIEVEMENTS.md', 'docs/design/GAMEPAD.md',
        'docs/design/ANDROID_LAYOUT_HYPOTHESIS.md'
    )) {
        # Documents keep their docs/ folder structure inside the bundle.
        $relativeDocument = $document.Replace('/', '\')
        $source = Join-Path $workspace $relativeDocument
        if (-not (Test-Path -LiteralPath $source -PathType Leaf)) {
            throw "Required release document is missing: $document"
        }
        $destination = Join-Path $stageBundle $relativeDocument
        New-Item -ItemType Directory -Path (Split-Path -Parent $destination) -Force | Out-Null
        Copy-Item -LiteralPath $source -Destination $destination
    }

    # The review archive also preserves the active Rust source and the complete Python history.
    foreach ($projectFile in @('Cargo.toml', 'Cargo.lock', '.gitignore', 'build_all.bat', 'run_game.bat', 'run.bat')) {
        $source = Join-Path $workspace $projectFile
        if (Test-Path -LiteralPath $source -PathType Leaf) {
            Copy-Item -LiteralPath $source -Destination (Join-Path $stageBundle $projectFile)
        }
    }
    $stageRustSource = Join-Path $stageBundle 'plouto_rs'
    New-Item -ItemType Directory -Path $stageRustSource -Force | Out-Null
    Copy-Item -LiteralPath (Join-Path $workspace 'plouto_rs\Cargo.toml') -Destination (Join-Path $stageRustSource 'Cargo.toml')
    foreach ($rustDirectory in @('src', 'tests', 'examples')) {
        $source = Join-Path (Join-Path $workspace 'plouto_rs') $rustDirectory
        if (Test-Path -LiteralPath $source -PathType Container) {
            Copy-Item -LiteralPath $source -Destination (Join-Path $stageRustSource $rustDirectory) -Recurse
        }
    }
    $stageArchive = Join-Path $stageBundle 'archive'
    New-Item -ItemType Directory -Path $stageArchive -Force | Out-Null
    Copy-Item -LiteralPath (Join-Path $workspace 'archive\python') -Destination (Join-Path $stageArchive 'python') -Recurse
    $stageTools = Join-Path $stageBundle 'tools'
    New-Item -ItemType Directory -Path $stageTools -Force | Out-Null
    foreach ($toolScript in @('build_release.ps1', 'package_friend.ps1', 'render_model_review.ps1')) {
        $source = Join-Path (Join-Path $workspace 'tools') $toolScript
        if (Test-Path -LiteralPath $source -PathType Leaf) {
            Copy-Item -LiteralPath $source -Destination (Join-Path $stageTools $toolScript)
        }
    }

    $reviewImages = @(
        'boss_gorgon_juggernaut_8_angles.png',
        'boss_swarmqueen_model_8_heading_review.png', 'boss_swarmqueen_volley_model_8_heading_review.png',
        'boss_womb_core_model_8_heading_review.png', 'boss_womb_core_pulse_model_8_heading_review.png',
        'boss_eclipse_archon_model_8_heading_review.png', 'boss_eclipse_archon_charge_model_8_heading_review.png',
        'boss_eclipse_archon_burst_model_8_heading_review.png',
        'live_build_hud_check.png', 'boss_laser_model_8_heading_review.png', 'boss_thunder_model_8_heading_review.png',
        'boss_abyss_gaze_model_8_heading_review.png', 'boss_trapmaster_model_8_heading_review.png',
        'tank_model_8_heading_review.png', 'chaser_model_8_heading_review.png', 'bomber_model_8_heading_review.png',
        'ranged_model_8_heading_review.png', 'sniper_model_8_heading_review.png', 'charger_model_8_heading_review.png',
        'spitter_model_8_heading_review.png', 'flyer_model_8_heading_review.png', 'engineer_model_8_heading_review.png',
        'swarm_model_8_heading_review.png', 'egg_sac_model_8_heading_review.png',
        'current_source_model_audit_1.png', 'current_source_model_audit_2.png', 'current_source_model_audit_3.png',
        'character_render_regular_world_scale_review.png', 'character_render_boss_world_scale_review.png'
    )
    foreach ($imageName in $reviewImages) {
        $source = Join-Path $releaseRoot $imageName
        if (Test-Path -LiteralPath $source -PathType Leaf) {
            Copy-Item -LiteralPath $source -Destination (Join-Path (Join-Path $stageBundle 'visual_reviews') $imageName)
        }
    }

    # The character audit uses release-relative links so its images resolve in the source tree and archive.
    $reportLinkedImages = @(
        'character_render_regular_world_scale_review.png',
        'character_render_boss_world_scale_review.png'
    )
    $stageLinkedEvidence = Join-Path $stageBundle 'release'
    New-Item -ItemType Directory -Path $stageLinkedEvidence -Force | Out-Null
    foreach ($imageName in $reportLinkedImages) {
        $source = Join-Path $releaseRoot $imageName
        if (-not (Test-Path -LiteralPath $source -PathType Leaf)) {
            throw "Required character-audit image is missing: $source"
        }
        Copy-Item -LiteralPath $source -Destination (Join-Path $stageLinkedEvidence $imageName)
    }

    $executableHash = (Get-FileHash -LiteralPath (Join-Path $stageBundle 'Plouto.exe') -Algorithm SHA256).Hash.ToLowerInvariant()
    $bundleRoot = [System.IO.Path]::GetFullPath($stageBundle)
    $files = @(Get-ChildItem -LiteralPath $bundleRoot -File -Recurse | Sort-Object FullName | ForEach-Object {
        [ordered]@{
            path = Get-RelativeBundlePath $bundleRoot $_.FullName
            size = $_.Length
            sha256 = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
        }
    })
    $manifest = [ordered]@{
        formatVersion = 1
        product = 'PLOUTO - Stellar Survival'
        releaseVersion = $releaseVersion
        simulationRulesVersion = $rulesVersion
        sourceRevision = $sourceRevision
        sourceDirty = $sourceDirty
        createdUtc = [DateTime]::UtcNow.ToString('yyyy-MM-ddTHH:mm:ssZ')
        executable = 'Plouto.exe'
        executableSha256 = $executableHash
        buildId = $executableHash.Substring(0, 16)
        files = $files
    }
    $manifestJson = $manifest | ConvertTo-Json -Depth 6
    [System.IO.File]::WriteAllText((Join-Path $stageBundle 'MANIFEST.json'), $manifestJson, [System.Text.UTF8Encoding]::new($false))

    New-Item -ItemType Directory -Path $stageFriend -Force | Out-Null
    Copy-Item -LiteralPath (Join-Path $stageBundle 'Plouto.exe') -Destination (Join-Path $stageFriend 'Plouto.exe')
    Copy-Item -LiteralPath (Join-Path $stageBundle 'laser-gun_38685.ico') -Destination (Join-Path $stageFriend 'laser-gun_38685.ico')
    Copy-Item -LiteralPath (Join-Path $stageBundle 'assets') -Destination (Join-Path $stageFriend 'assets') -Recurse
    $friendReadme = @'
PLOUTO - Stellar Survival
Windows game build

Extract the whole ZIP into a folder, then open Plouto.exe.
Keep the executable, icon, and assets folder together. No Rust installation is needed.

Move: WASD or arrow keys
Aim and fire: mouse and left click
Dash: Space    Boost: Shift    Ultra: Q or right click    Pause: Escape

Gamepad: Left stick move; right stick aim; fire with RT, RB, or pushing the right stick
Dash: A    Boost: LT or LB    Ultra: Y    Pause: Start
Menus: D-pad or left stick; A confirms; B goes back; Start pauses or resumes

Heavy Cannon, Flak, and the late-game Siege Mortar reload between volleys; the weapon chip shows reload progress.
Powerful weapon pickups last for a short burst, then restore your regular weapon.

Progress and settings are stored in %LOCALAPPDATA%\Plouto; they are not included in this ZIP.
'@
    [System.IO.File]::WriteAllText((Join-Path $stageFriend 'README.txt'), $friendReadme, [System.Text.UTF8Encoding]::new($false))
    $friendRoot = [System.IO.Path]::GetFullPath($stageFriend)
    $friendFiles = @(Get-ChildItem -LiteralPath $friendRoot -File -Recurse | Sort-Object FullName | ForEach-Object {
        [ordered]@{
            path = Get-RelativeBundlePath $friendRoot $_.FullName
            size = $_.Length
            sha256 = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
        }
    })
    $friendManifest = [ordered]@{
        formatVersion = 1
        product = 'PLOUTO - Stellar Survival'
        releaseVersion = $releaseVersion
        simulationRulesVersion = $rulesVersion
        sourceRevision = $sourceRevision
        sourceDirty = $sourceDirty
        createdUtc = $manifest.createdUtc
        executable = 'Plouto.exe'
        executableSha256 = $executableHash
        buildId = $executableHash.Substring(0, 16)
        files = $friendFiles
    }
    [System.IO.File]::WriteAllText((Join-Path $stageFriend 'MANIFEST.json'), ($friendManifest | ConvertTo-Json -Depth 6), [System.Text.UTF8Encoding]::new($false))
    $friendFiles = @(Get-ChildItem -LiteralPath $friendRoot -File -Recurse | Where-Object { $_.Name -ne 'MANIFEST.json' } | Sort-Object FullName | ForEach-Object {
        [ordered]@{
            path = Get-RelativeBundlePath $friendRoot $_.FullName
            size = $_.Length
            sha256 = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
        }
    })
    # The manifest intentionally does not hash itself, avoiding a recursive digest.

    Add-Type -AssemblyName System.IO.Compression.FileSystem
    [System.IO.Compression.ZipFile]::CreateFromDirectory($stageBundle, $stageRustZip, [System.IO.Compression.CompressionLevel]::Optimal, $false)
    [System.IO.Compression.ZipFile]::CreateFromDirectory($stageFriend, $stageFriendZip, [System.IO.Compression.CompressionLevel]::Optimal, $false)
    Assert-FullArchive $stageRustZip $executableHash $files
    Assert-FriendArchive $stageFriendZip $executableHash $friendFiles

    Promote-ReleaseSet $finals $releaseRoot $stageRoot
    Write-Output "Release bundle ready: $(Join-Path $releaseRoot 'Plouto')"
    Write-Output "Rust archive ready: $(Join-Path $releaseRoot 'Plouto.zip')"
    Write-Output "Friend archive ready: $(Join-Path $releaseRoot 'Plouto_for_friend.zip')"
} finally {
    if (Test-Path -LiteralPath $stageRoot) {
        Remove-Item -LiteralPath $stageRoot -Recurse -Force
    }
}
