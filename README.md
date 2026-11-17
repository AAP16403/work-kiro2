# PLOUTO: Stellar Survival

PLOUTO is a fast arcade survival game set in a neon-lit arena. The active desktop game is written in Rust and uses `wgpu` for rendering, with a deterministic simulation for combat, runs, and replays.

## Run the game

Install the stable Rust toolchain, then run from the repository root:

```powershell
cargo run --bin plouto
```

On Windows, `run.bat` and `run_game.bat` launch the same game. `build_all.bat` creates the release folder at `release\Plouto`, the full Rust review archive at `release\Plouto.zip`, and the friend-ready player archive at `release\Plouto_for_friend.zip`. The review archive includes the Rust source, assets, design/report documents, and the complete archived Python base. The friend ZIP includes only the ready-to-run game, assets, icon, and player instructions. Both archives are staged and checked before the existing release set is replaced.

`run_game.bat` launches the packaged Rust game when a release build exists. Before the first package build, it falls back to `cargo run --bin plouto`. Each build refreshes both `Plouto.exe` and the compatibility name `Plouto-Open-Arena.exe` in the release folder. The archives include a SHA-256 manifest; the friend ZIP contains the game, assets, icon, player instructions, and a package-only manifest, but no progress or development reports.

## Controls

| Action | Keyboard / mouse | Gamepad (Xbox layout) |
| --- | --- | --- |
| Move | WASD or arrow keys | Left stick |
| Aim and fire | Mouse and left click | Right stick aims (keeps its last aim when released); fire with right trigger, right bumper, or by pushing the right stick past halfway |
| Dash | Space | A |
| Boost | Shift | Left trigger or left bumper |
| Ultra ability | Q or right click | Y |
| Pause / resume | Escape | Start |
| Navigate menus | Arrow keys and Enter | D-pad or left stick (held direction repeats); A confirms, B goes back, Start acts as Escape. B and Start do nothing on the main menu, so they cannot quit the game there. |

- Controllers that `gilrs` recognises (Xbox-style, PlayStation, and generic pads) are read through `gilrs`, with hot-plug detection and automatic switching between mouse/keyboard and gamepad. No specific model has been tested.
- Settings include Gamepad on/off, Vibration on/off, and Stick Deadzone (0.05 to 0.5, default 0.18). Rumble plays on player damage, death, boss phase changes and defeat, and large blasts. It is rate-limited and only runs while the gamepad is the active device.
- Some pads expose the triggers only as a stick-style axis; on those there is no analog trigger, so use the bumpers for fire and boost.
- No automated test covers gamepad mapping, and gamepad support has not been tested on real hardware.

## What’s in the game

- Four open arena shapes—Circle, Donut, Cross, and Diamond—with clear interior lanes and no cover obstacles blocking player or enemy fire. Every five-wave sector shifts the arena circuit colors and pulses the rim on entry.
- Enemy classes with distinct movement and ranged attacks, introduced through staged wave combinations. Several enemies predict incoming player-shot paths and dodge likely hits; later waves pair close-range pressure with ranged threats and a rotating specialist. Elite modifiers split, reflect shots, add shields, explode on death, repair allies, or protect nearby enemies.
- Arena events create tactical openings: telegraphed meteors and solar flares hit enemy ships too, ranged enemies dodge imminent meteor strikes, and nebula clouds shield enemies that remain inside.
- Eight named bosses—Storm Sovereign, Prisma Overlord, Forge Warden, Brood Matriarch, Gorgon Juggernaut, Ocular Abyss, Origin Nexus, and Eclipse Archon—with distinct phase shifts, escalating visuals, and readable attack patterns. The in-game Field Guide explains each boss's counterplay.
- Weapon upgrades, power-ups, boss-earned run relics, skins, mutators, daily runs, 35 achievements, replays, and persistent scores. Relics can pull salvage farther away, repair hull after a wave, or turn dash endings into a damaging phase pulse.
- The Hangar has an Achievements tab that lists every achievement with its category, your completion percentage, progress bars, and secret entries shown as "???". Game-over screens show new unlocks and up to two "almost there" progress lines.
- Animated menus and effects, keyboard-focused settings navigation, buff countdown rings, boss phase feedback, screen shake controls, reduced-motion options, color-aware enemy palettes, and configurable display settings.

## Project layout

- `Cargo.toml` and `Cargo.lock` define the Rust workspace.
- `plouto_rs\src` contains the simulation (`sim`), rendering (`render`), audio, saves, interface (`ui`), and input (`input`: gamepad, button mapping, rumble, and button glyphs).
- `plouto_rs\tests` holds the headless integration tests; `plouto_rs\examples` holds the profiling and enemy-review tools.
- `assets` holds the fonts and sound files shared with the game.
- `docs` holds the plans, reports, and design notes for the Rust game. See [docs/README.md](docs/README.md).
- `archive\python` preserves the earlier Python desktop game, browser version, tests, tools, and design notes.
- Development runs keep `progress.json`, `user_settings.json`, and `high_scores.json` beside the Rust workspace. Installed Windows builds use `%LOCALAPPDATA%\Plouto`; the first run copies any matching legacy portable files into that folder without deleting the originals. Set `PLOUTO_PORTABLE=1` to keep data beside the executable, or set `PLOUTO_DATA_DIR` to choose another writable folder.

The Python game is kept as a historical archive; Rust is the launch and release target.

## Record and replay

```powershell
cargo run --bin plouto -- --record run.json
cargo run --bin plouto -- --replay run.json
```

Use `--help` to see command options. Replays verify the deterministic simulation result recorded in the file.

- The replay file records `SIMULATION_RULES_VERSION` (currently 12, defined in `plouto_rs\src\sim\replay.rs`). Replays recorded under older rules versions are rejected and must be recorded again.
- A recorded run (`--record`) does not write progress. A replay (`--replay`) never grants achievements.

## Development

Run the headless test suite from the repository root:

```powershell
cargo test -p plouto_rs
```

The suite covers simulation, saves, achievements, bosses, enemies, rendering geometry, and UI behavior. These tests do not open the game window. To additionally run the graphics check for every boss phase and personality on a real graphics adapter, use `cargo test -p plouto_rs --test boss_gpu -- --ignored --nocapture`.

Unexpected Rust panics and fatal application errors append details to `crash.log` in the same data folder as your progress (normally `%LOCALAPPDATA%\Plouto` for installed builds).

Human play-testing has not been done for the recent gamepad, achievement, and enemy work. The achievement and simulation behavior is covered by the headless tests above. The gamepad code has source review only, because no automated test covers it.

Simulation changes must bump `SIMULATION_RULES_VERSION` (see the record and replay section above).

## Documentation

- [docs/README.md](docs/README.md) indexes every document in `docs/`, with one sentence on each and a suggested reading order for a new contributor.
- [docs/plans/ENEMY_AI_PLAN.md](docs/plans/ENEMY_AI_PLAN.md) is the work order for the enemy AI changes. Its section 0 lists the rules every change follows.
- [docs/design/GAMEPAD.md](docs/design/GAMEPAD.md) and [docs/design/ACHIEVEMENTS.md](docs/design/ACHIEVEMENTS.md) describe the gamepad and achievement behavior in detail.
- [docs/reports/CHANGELOG.md](docs/reports/CHANGELOG.md) is the change history for the Rust crate.
