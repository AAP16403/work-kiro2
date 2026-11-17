# Changelog

All notable changes to PLOUTO (Rust crate `plouto_rs`) are recorded here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased] — 2026-11-17

### Boss crash investigation

- Fixed an integer overflow when rendering chain lightning. The regression test reproduced a debug-build panic while Prisma Overlord was attacking.
- Prisma Overlord now removes its sustained laser beams when a sweep finishes, preventing residual beam damage during its wing warning or recovery. Covered at normal speed and under Time Slow.
- Added an explicit GPU integration check covering all eight bosses, their three phases, and three personalities, including real beam rendering, bloom, and text submission.
- Rust panics and fatal startup errors now save a timestamped crash report and backtrace to the player data folder. The originally reported packaged-build crash has not been reproduced.
- At the time of this crash-fix pass, simulation rules advanced to version 11. Later gameplay work advanced the current source to version 13; older replays must be recorded again.

### Added

- Gamepad support through gilrs 0.11, in `plouto_rs/src/input/` (`gamepad.rs`, `mapping.rs`, `rumble.rs`, `glyphs.rs`).
- Gameplay bindings: left stick moves, right stick aims (keeps the last aim when released), fire on RT, RB, or right stick pushed past 0.5, A dashes, LT/LB boost, Y uses Ultra, Start pauses.
- Menu bindings: D-pad or left stick navigates (repeats after 0.35s, then every 0.12s), A confirms, B goes back. B and Start do nothing on the main menu so a stray press cannot quit the game.
- Gamepad settings: Gamepad on/off, Vibration on/off, Stick Deadzone (0.05–0.5, default 0.18).
- Controller rumble on player damage, death, boss phase change and defeat, and large blasts. Rumble is rate-limited and only runs while the gamepad is the active device.
- Automatic switching between mouse/keyboard and gamepad based on the last input used.
- 15 new achievements, bringing the total to 35: dash_master, overdrive, overkill, scavenger, shield_wall, triple_threat, every_boss, world_tour, daily_driver, mutant, purist, endurance, five_thousand, old_hand, clean_sweep.
- Mid-run unlock toasts for achievements that only go up. Purist waits until the run settles.
- Game-over screen shows new unlocks and up to 2 "almost there" progress lines.
- Hangar achievements tab shows categories, completion percentage, progress bars, and secret entries shown as "???".
- Main menu now rotates through an animated spotlight for all 11 regular enemy hulls; the guide uses accurate role descriptions, semantic symbols, and fitted 3D previews.
- A documented landscape Android twin-stick/HUD hypothesis based on the supplied schematic. This is a layout proposal; touch controls are not implemented.
- Headless contracts for repeat power-ups, temporary weapon restoration, Ultra/Repulsor caps, wave/event rules, and all-eight boss phase transitions.
- Daily records now save their date-associated seed, normalized modifier set, and rules version. A new rules/setup comparison preserves the prior record as history and the menu labels it as such.
- Boss reward offers now favor distinct categories, omit permanent upgrades that cannot change the build, keep repeatable upgrade stacks visible, and show duration/stack context on reward cards.

### Changed

- The current simulation-rules version is 13 (`SIMULATION_RULES_VERSION` in `plouto_rs/src/sim/replay.rs`). Replays recorded under earlier rules versions are rejected with an explicit rules-version message. Re-record any replay you want to keep.
- Doubled wave-5 and wave-10 boss health. Ultra now uses 90 base damage plus an 8× effective-damage term, a 220-unit pulse, and an additional three-lane fan; focused coverage includes all three Ultra variants.
- Increased player, ordinary-enemy, and most boss render scales while keeping simulation hit radii independent. Brood Matriarch's wings are 20% wider. The player dash ghost now uses relative scale factors so its global art scale is applied once.
- Documentation reorganized under `docs/`: reports in `docs/reports/`, plans in `docs/plans/`, design references in `docs/design/`, with an index at `docs/README.md`.

### Fixed

- The stale `now` field that broke an earlier test build is fixed. The latest full test run before the daily metadata follow-up passed 159 tests; one adapter-dependent GPU integration test is ignored. The follow-up changes compile with `cargo check -p plouto_rs`; no game window was opened.
- Achievement shield-blocked hits are handled under the new shield rule.
- Enemy contact self-destruct no longer counts as a player kill.
- A wave clear that happens on the same step as the player's death no longer counts.
- Runs ended from the pause menu or by closing the window now settle and count toward achievements.
- `--replay` playback never grants achievements.
- `--record` runs skip progress writes.

### Known issues

- Gamepad support has not been tested on real hardware. Human play-testing of the new work has not been done; the game was not launched during this pass.
- Pads that expose the triggers only as a single axis have no analog trigger. Use RB and LB on those pads.
- Open policy question: abandoned or quit runs inflate achievements based on `runs_played`.
- Open policy question: daily retries count as runs.
- The core typed-role AI, perception, attack director, formation v2, and unified locomotion are implemented. Per-role acceptance, boss prediction migration, persistent telemetry, and stronger moving-player fairness samples remain open in `docs/plans/ENEMY_AI_PLAN.md`.
- Moving-orbit projectile-hit samples remain too sparse for a stable Easy/Hard accuracy conclusion; stationary-target rates are diagnostics only.
- Final GPU appearance, live combat animation, human-play balance, real gamepad hardware, and Android touch/device validation remain unverified.

## [0.1.0] — 2026-11-16

First Rust release. Source of detail: `docs/reports/GAME_IMPROVEMENT_REPORT.md`.

### Added

- Rust is the primary game. The Python project was moved to `archive/python` (224 files) and is no longer the default launch path.
- `run_game.bat` launches the packaged Rust executable first, with a source-build fallback.
- Aegis Relay run relic: Ultra strikes restore up to 14 shield.
- Animated in-game "Flight Link" comms for wave changes, boss arrivals and phases, critical hull, power-ups, and arena events.
- Shaded 3D models for the player pod, all 11 regular enemy types, and all eight bosses, built from the artwork in `assets/artwork/characters/`.
- Eight-screen-heading model review sheets and a deterministic spawn-clearance check across waves 1–20, all four arena shapes, and eight seeds per wave.
- Friend-ready Windows package (`release/Plouto_for_friend.zip`) and a review archive (`release/Plouto.zip`) with manifests and SHA-256 hashes.

### Changed

- Rust arenas are open: interior obstacles are disabled by default and new runs start with an empty obstacle list.
- Regular enemies gained committed windups with visible telegraphs (ranged fire, spitter spread, engineer mines, bomber blasts, tank cannon, Storm Sovereign ring, boss attacks).
- Explosive weapons (Heavy Cannon, Flak, Siege Mortar) have minimum reload windows and radial splash damage.
- Replay format version 4 stores a rules version and periodic state fingerprints, and reports the first failed checkpoint.
- Pickup durations and rarity follow the archived Python classification. Equal or lower rank weapon pods convert to shield or hull instead of replacing the current weapon.

### Fixed

- Wave enemies spawn at the arena rim with separation checks. Regular waves and bosses favor spawn points away from the player.
- Forge Warden spike traps are placed inside the walkable arena.
- When one hit crosses both the 35% rage and 33% phase-three thresholds, the combined boss banner reports both instead of hiding the phase-three cue.
- Enemy and boss clocks respect Time Slow. Interrupted attacks are cancelled cleanly on stun and phase change.
- Projectile hit order is deterministic, and piercing shots resolve every target crossed in one step.
- Ultra label, Ultra gauge, and comms cursor glyph render correctly in the packaged build.
