# PLOUTO documentation

This folder holds the plans, reports, and design notes for the Rust game. The game code lives in `plouto_rs\`; the earlier Python game lives in `archive\python`. Each document states its own evidence level. Most design notes are source audits and have not been checked in live play.

## Where to start

Read these in order when you join the project or pick up a new task:

1. `plans\ENEMY_AI_PLAN.md`, section 0 ("Rules every agent follows"). These rules apply to all work: determinism, the clock rules, bumping `SIMULATION_RULES_VERSION` for any change to simulation output, no panics in sim code, and owning only your files.
2. `reports\CHANGELOG.md`, the record of changes to the Rust crate, starting with the Unreleased section.
3. The design note for the system you are changing. The table below shows which one.

Working rule from the current plans: do not launch the game window. Headless `cargo test -p plouto_rs` and the profiling example are allowed.

| If you are working on | Read |
| --- | --- |
| Enemy movement, attacks, or formation | `design\ENEMY_BEHAVIOR_SHEETS.md`, then `plans\ENEMY_AI_PLAN.md` |
| Timers, cooldowns, or Time Slow | `design\SIMULATION_CLOCKS.md` |
| Weapon damage or fire rate | `design\WEAPON_OUTPUT_LEDGER.md` |
| Wave composition, arena events, or difficulty | `design\LEVEL_DESIGN_AND_DIFFICULTY.md` |
| Character models or art | `design\CHARACTER_ART_SPECIFICATIONS.md` |
| Animation poses and timing | `design\ANIMATION_STATE_MAP.md` |
| Gamepad input, rumble, or glyphs | `design\GAMEPAD.md` |
| Achievements, progress, or unlocks | `design\ACHIEVEMENTS.md` |
| What has been done so far | `reports\GAME_IMPROVEMENT_REPORT.md`, then `plans\GAME_IMPROVEMENT_PLAN.md` |

## Plans

- `plans\GAME_IMPROVEMENT_PLAN.md`: The detailed roadmap for making the Rust game more readable, varied, and deliberate. Its status section records that source changes are in place for all 37 ledger tasks, and that sound is out of scope.
- `design\android_ui\android_ui_mockups.html`: HTML mockups of every Android screen (landscape touch). Open it in a browser. It has device presets, left-handed mode, and overlays for safe area, touch targets and stick zones. Design only; not implemented.
- `design\desktop_ui\desktop_ui_mockups.html`: HTML mockups of a redesigned desktop UI for every screen. It has window-size presets and a keyboard/gamepad glyph toggle. Design only; not implemented.
- `plans\ANDROID_PLAN.md`: Android version plan. It covers the DPI and safe-area layout system, the touch combat HUD, compact menu layouts, the touch input design, the Android port (GameActivity, assets, lifecycle, GPU fallback), parallel workstreams, and validation. Plan only; nothing is implemented.
- `plans\ENEMY_AI_PLAN.md`: The enemy AI implementation work order with a current-source status table. Typed roles, perception, the regular attack director, formation v2, and unified locomotion are present; role-state splitting and parts of per-role validation remain open. WP-G currently has headless diagnostics, but its stationary-target accuracy sample does not establish live-play fairness.

## Reports

- `reports\GAME_IMPROVEMENT_REPORT.md`: A record of the completed Rust game improvement work, including the switch to Rust as the release target and the Python archive. Last updated 2026-11-17.
- `reports\CHANGELOG.md`: The changelog for the `plouto_rs` crate, following Keep a Changelog. The Unreleased section covers the current replay rules, boss/Ultra pass, character scaling, menu/guide updates, and focused gameplay contracts.

## Design

- `design\ENEMY_BEHAVIOR_SHEETS.md`: The current regular enemy behavior and attack timing, taken from the source after the enemy commitment pass.
- `design\WEAPON_OUTPUT_LEDGER.md`: Nominal damage output for each weapon at default settings, calculated from the formulas, before hit chance, armor, and upgrades.
- `design\SIMULATION_CLOCKS.md`: Which clock (`state.time`, `dt`, `enemy_dt`) each system uses, and when each one advances.
- `design\LEVEL_DESIGN_AND_DIFFICULTY.md`: The open-arena encounter direction, the authored wave templates for waves 1 to 20, arena events, and difficulty calibration.
- `design\CHARACTER_ART_SPECIFICATIONS.md`: The rules that keep the 3D characters faithful to the reference art, and the 3D presentation constraints.
- `design\ANIMATION_STATE_MAP.md`: How gameplay and enemy states map to animation poses and timing, including reduced-motion behavior.
- `design\GAMEPAD.md`: Gamepad support as implemented on 2026-11-17: supported controllers, bindings, menu navigation, settings, and rumble. Not tested on real hardware.
- `design\ANDROID_LAYOUT_HYPOTHESIS.md`: Proposed landscape Android twin-stick and HUD layout based on the supplied schematic; touch input and Android release support are not implemented or device-verified.
- `design\ACHIEVEMENTS.md`: The 35 achievements as of 2026-11-17, with their definitions, settlement rules, and the skins they unlock.
