# Rust Game Improvement Report

Last updated: 2026-11-17

## Current status

As of 2026-11-17. This section describes the current state. The dated entries below are history: each one describes the state and checks of its own pass.

- The game is PLOUTO, built from the Rust crate `plouto_rs` (wgpu and winit). The Rust build is the primary game and the release target.
- The Python game is archived in `archive/python` (224 files). It is not the launch path.
- `SIMULATION_RULES_VERSION` is 13. Replays recorded under older rules versions are rejected with an explicit rules-version message.
- The latest full `cargo test -p plouto_rs` run passed 159 tests with one adapter-dependent GPU test intentionally ignored; that run predates the daily-record metadata and menu-label changes below. The current Rust source passes `cargo check -p plouto_rs`. No game window was opened.
- The latest release package is rebuilt at rules version 13. See the dated entry below for its manifest and archive results.
- The earlier broken test build (a stale `now` field in `tests/sim_and_save.rs`) is fixed.
- Older test counts and release manifests in dated entries describe only their own pass. The daily metadata changes have only been compile-checked so far.
- Headless tests are allowed. Agents do not launch the game window. Human play-testing has not been done for any of the new work, including the gamepad and achievements changes.
- Gamepad support (gilrs 0.11) is implemented in `plouto_rs/src/input/`. No test in `plouto_rs/tests/` or the `input` module covers gamepad mapping, and it has not been tested on real hardware. Known limit: a pad that exposes its triggers only as an axis has no analog trigger, so use RB and LB.
- Achievements: 35 in total, the 20 original ids plus 15 new ones. All 23 achievement tests pass within the current 155-test suite. Unlock toasts, the game-over screen, the Hangar layout, and unlock feel in the live game are not verified.
- Open policy questions, not yet decided: abandoned or quit runs inflate achievements based on `runs_played`, and daily retries count as runs.
- Current rules-13 headless CPU profiles on one Windows machine match all 30/30 checkpoints across repeated runs. At 112 synthetic actors, p95 is 0.776–0.908 ms, below both the 16.67 ms step budget and the plan's 1 ms target. Rendering, GPU cost, and whole-frame time were not measured.
- Rust formatting: the 2026-11-16 pass could not run `cargo fmt --check` because rustfmt is not installed. This status did not re-check it.
- The core typed-role AI, perception, attack director, unified locomotion, and formation-v2 systems are implemented. Follow-ups remain for per-role validation, boss prediction migration, reusable telemetry, and a stronger moving-player fairness sample; see `docs/plans/ENEMY_AI_PLAN.md`.
- The character renderer is split into player, regular-enemy, and boss 3D models. Current scale and offline-sheet evidence are in `docs/reports/CHARACTER_RENDER_AUDIT.md`; final GPU framing and human-play review remain open.
- An Android touch-control layout hypothesis is documented, but touch input and Android device validation are not implemented.
- No new sectors or sound work were added. Current arenas remain open; existing sector signatures are visual only.

## Contents

- [Direction](#direction)
- [Latest changes](#latest-changes)
  - [Comprehensive gameplay and visual audit — 2026-11-17](#comprehensive-gameplay-and-visual-audit--2026-11-17)
  - [Daily challenge, modifier, and RPG reward audit — 2026-11-17](#daily-challenge-modifier-and-rpg-reward-audit--2026-11-17)
  - [Gamepad support — 2026-11-17](#gamepad-support--2026-11-17)
  - [Achievements overhaul — 2026-11-17](#achievements-overhaul--2026-11-17)
- [Work completed](#work-completed)
  - [Rust release and Python archive](#rust-release-and-python-archive)
  - [Open arenas and gameplay](#open-arenas-and-gameplay)
  - [HUD and visual feedback](#hud-and-visual-feedback)
  - [Swarmqueen encounter — this pass](#swarmqueen-encounter--this-pass)
  - [Boss attack readability — this pass](#boss-attack-readability--this-pass)
  - [Wave progression and entry spacing — this pass](#wave-progression-and-entry-spacing--this-pass)
  - [Wave spawn regression audit — this pass](#wave-spawn-regression-audit--this-pass)
  - [Animated in-game comms — this pass](#animated-in-game-comms--this-pass)
  - [Enemy attack readability — this pass](#enemy-attack-readability--this-pass)
  - [Engineer mine readability — this pass](#engineer-mine-readability--this-pass)
  - [Combat scale and bomber blast — this pass](#combat-scale-and-bomber-blast--this-pass)
  - [Storm Sovereign boss cycle — this pass](#storm-sovereign-boss-cycle--this-pass)
  - [Combat silhouettes and bomber impact — this pass](#combat-silhouettes-and-bomber-impact--this-pass)
  - [Main menu input focus — this pass](#main-menu-input-focus--this-pass)
  - [Forge Warden arena-aware spike placement — this pass](#forge-warden-arena-aware-spike-placement--this-pass)
  - [Tactical animated comms — this pass](#tactical-animated-comms--this-pass)
  - [Sound scope — this pass](#sound-scope--this-pass)
  - [Artwork-based 3D characters and engine effects — this pass](#artwork-based-3d-characters-and-engine-effects--this-pass)
  - [Player pod 3D readability and rotation — this pass](#player-pod-3d-readability-and-rotation--this-pass)
  - [Player model world rotation and hangar preview — this pass](#player-model-world-rotation-and-hangar-preview--this-pass)
  - [Origin Nexus and Eclipse Archon articulation — this pass](#origin-nexus-and-eclipse-archon-articulation--this-pass)
  - [Player pod proportions and screen-direction turn — this pass](#player-pod-proportions-and-screen-direction-turn--this-pass)
  - [Boss art fidelity and all-angle visual review — this pass](#boss-art-fidelity-and-all-angle-visual-review--this-pass)
  - [Render coverage and replay consistency — this pass](#render-coverage-and-replay-consistency--this-pass)
  - [Player pod vertical proportions and natural facing — this pass](#player-pod-vertical-proportions-and-natural-facing--this-pass)
  - [Siege tank 3D model and firing animation — this pass](#siege-tank-3d-model-and-firing-animation--this-pass)
  - [Chaser interceptor art and lunge animation — this pass](#chaser-interceptor-art-and-lunge-animation--this-pass)
  - [Bomber mine-layer art and reactor pulse — this pass](#bomber-mine-layer-art-and-reactor-pulse--this-pass)
  - [Ranged gunship art and cannon windup — this pass](#ranged-gunship-art-and-cannon-windup--this-pass)
  - [Sniper railgun art and charge animation — this pass](#sniper-railgun-art-and-charge-animation--this-pass)
  - [Charger forked silhouette and dash pose — this pass](#charger-forked-silhouette-and-dash-pose--this-pass)
  - [Spitter acid gunship art and volley animation — this pass](#spitter-acid-gunship-art-and-volley-animation--this-pass)
  - [Flyer crescent interceptor and wing animation — this pass](#flyer-crescent-interceptor-and-wing-animation--this-pass)
  - [Engineer repair drone art and claw animation — this pass](#engineer-repair-drone-art-and-claw-animation--this-pass)
  - [Swarm delta fighter proportions and flight pose — this pass](#swarm-delta-fighter-proportions-and-flight-pose--this-pass)
  - [Egg sac shell split and hatch telegraph — this pass](#egg-sac-shell-split-and-hatch-telegraph--this-pass)
  - [Prisma Overlord crystal art and laser-lock pose — this pass](#prisma-overlord-crystal-art-and-laser-lock-pose--this-pass)
  - [Storm Sovereign 3D cross and crystal volley pose — this pass](#storm-sovereign-3d-cross-and-crystal-volley-pose--this-pass)
  - [Ocular Abyss eye mask and tendril pose — this pass](#ocular-abyss-eye-mask-and-tendril-pose--this-pass)
  - [Forge Warden upright armor and cannon pose — this pass](#forge-warden-upright-armor-and-cannon-pose--this-pass)
  - [Brood Matriarch 3D proportions and attack poses — this pass](#brood-matriarch-3d-proportions-and-attack-poses--this-pass)
  - [Origin Nexus heart, gyroscope, and pulse pose — this pass](#origin-nexus-heart-gyroscope-and-pulse-pose--this-pass)
  - [Fresh packaged HUD cursor review — this pass](#fresh-packaged-hud-cursor-review--this-pass)
  - [Eclipse Archon crown, event horizon, and ring attacks — this pass](#eclipse-archon-crown-event-horizon-and-ring-attacks--this-pass)
  - [Ultra HUD label spacing — this pass](#ultra-hud-label-spacing--this-pass)
  - [Animated comms cursor — this pass](#animated-comms-cursor--this-pass)
  - [Combat logic, flock spacing, and boss phase cues — this pass](#combat-logic-flock-spacing-and-boss-phase-cues--this-pass)
  - [Full combat and squad-logic recheck — this pass](#full-combat-and-squad-logic-recheck--this-pass)
- [Build and verification](#build-and-verification)
  - [Friend-ready package — this pass](#friend-ready-package--this-pass)
  - [Explosive reloads, pickup balance, and enemy recovery — 2026-11-16](#explosive-reloads-pickup-balance-and-enemy-recovery--2026-11-16)
- [Ongoing scope](#ongoing-scope)
  - [Detailed improvement roadmap — 2026-11-16](#detailed-improvement-roadmap--2026-11-16)
  - [Damage resolution and projectile impact order — 2026-11-16](#damage-resolution-and-projectile-impact-order--2026-11-16)
  - [Enemy clocks and interrupted attacks — 2026-11-16](#enemy-clocks-and-interrupted-attacks--2026-11-16)
  - [Pickup rules, reload debt, and bounded interactions — 2026-11-16](#pickup-rules-reload-debt-and-bounded-interactions--2026-11-16)
  - [Weapon output ledger and enemy commitment pass — 2026-11-16](#weapon-output-ledger-and-enemy-commitment-pass--2026-11-16)
  - [Enemy attack pressure, crowd spacing, and swarm/hatch control — 2026-11-16](#enemy-attack-pressure-crowd-spacing-and-swarmhatch-control--2026-11-16)
  - [Boss transitions and eight-encounter sequence pass — 2026-11-16](#boss-transitions-and-eight-encounter-sequence-pass--2026-11-16)
  - [Versioned replay fingerprints and early divergence reporting — 2026-11-16](#versioned-replay-fingerprints-and-early-divergence-reporting--2026-11-16)
  - [Complete Rust source archive and release package — 2026-11-16](#complete-rust-source-archive-and-release-package--2026-11-16)
  - [Time Slow aware enemy attack scheduling — 2026-11-16](#time-slow-aware-enemy-attack-scheduling--2026-11-16)
  - [Siege Mortar, target feedback, and explosive cadence — 2026-11-16](#siege-mortar-target-feedback-and-explosive-cadence--2026-11-16)
  - [Roadmap evidence reconciliation and source provenance — 2026-11-16](#roadmap-evidence-reconciliation-and-source-provenance--2026-11-16)
  - [Power-up rarity and explosive cooldown audit — 2026-11-16](#power-up-rarity-and-explosive-cooldown-audit--2026-11-16)
  - [Rank-safe temporary weapon pickups — 2026-11-16](#rank-safe-temporary-weapon-pickups--2026-11-16)
  - [Swarm surge communication and scheduler reservation audit — 2026-11-17](#swarm-surge-communication-and-scheduler-reservation-audit--2026-11-17)
  - [Current-source 3D model heading and proportion review — 2026-11-17](#current-source-3d-model-heading-and-proportion-review--2026-11-17)
  - [Critical comms reveal timing — 2026-11-17](#critical-comms-reveal-timing--2026-11-17)
  - [Headless simulation performance baseline — 2026-11-17](#headless-simulation-performance-baseline--2026-11-17)


## Direction

The Rust build is the primary game and release. The Python project is preserved as a full source archive under `archive/python` for reference; it is no longer the default launch path.

## Latest changes

The current audit below summarizes the completed systems checks and their limits. Older dated entries retain the evidence recorded at the time of each pass.

### Comprehensive gameplay and visual audit — 2026-11-17

- Raised the player pod's uniform 3D art scale from `1.27` to `1.34`, ordinary enemies from `1.30` to `1.43`, and most bosses by 8%; Storm Sovereign stays at its fitted scale. Brood Matriarch's wing span increased by 20%. Simulation hit radii were not changed. A static review also corrected dash-ghost dimensions so the player scale is applied once. See `docs/reports/CHARACTER_RENDER_AUDIT.md` for source and offline-sheet evidence.
- Improved the main menu with a rotating spotlight over all 11 regular enemy hulls. Updated the guide's enemy/boss mechanics, symbol badges, and 3D preview framing. Reduced-motion behavior remains available. Headless guide and fit tests cover the roster.
- Rechecked all 17 pickup dispatches and their expiry paths. No broken effect or cooldown defect was found. Added repeat-pickup, temporary-weapon restoration, Repulsor queue, and Ultra-cap contracts. Mortar coverage confirms its 1.30-second minimum reload, 168-unit splash, and 0.24-second visual blast lifetime.
- Rechecked wave composition, role unlocks, boss cadence, arena-event gating and damage scaling, Nebula cleanup, and obstacle suppression across the four arena shapes. Boss waves spawn one boss without adds; arena events roll on eligible non-boss waves only. Added four focused headless regression tests.
- Rechecked all eight boss phase-transition paths and warning/damage geometry. No production defect was reproduced. Added an all-eight phase-transition contract test for cancellation, beam cleanup, and the committed Origin Nexus warning/pulse pair.
- Wave 5 and Wave 10 boss HP are doubled, and the three Ultra variants have broader coverage and higher damage (`90 + 8 × effective player damage`, 220-unit pulse radius, plus three forward fan lanes). In guaranteed-charge profiles, Ultra's mean share rose from 10.0/10.0/7.7% to 17.8/17.1/15.4% on Easy/Normal/Hard. Existing matched profiles compare rules versions 11 and 12, so they are whole-profile observations rather than an isolated HP experiment. All 18 runs (three seeds × three difficulties × natural/guaranteed Ultra) reached wave 41 without timeout or game over.

  | Boss | Easy mean TTK | Normal mean TTK | Hard mean TTK |
  | --- | ---: | ---: | ---: |
  | Wave 5 | 5.29 → 9.20s (+74%) | 5.84 → 11.01s (+89%) | 9.91 → 15.84s (+60%) |
  | Wave 10 | 5.30 → 14.45s (+172%) | 9.02 → 15.00s (+66%) | 8.46 → 19.46s (+130%) |

  Later-boss TTK and damage changes are mixed. Several runs changed weapon loadout, Wave 30/35 boss identity differed in some pairs, and the compared files use different rules versions; do not attribute those later shifts solely to the Wave 5/10 HP adjustment.
- The headless AI fairness sample found that moving-orbit projectile hits are too sparse for a stable accuracy conclusion (4/1,198 Easy; 8/1,100 Hard over five 180-second seeds). A stationary-target diagnostic measured 37.58% Easy and 45.51% Hard collision rates, but does not represent a moving player's exposure and is not a fairness verdict. The plan records sample sizes, warning-time gaps, and remaining telemetry work.
- Updated the Android layout hypothesis to preserve current HUD priorities and distinguish proposed touch controls from implemented controls. No touch runtime was added.
- Removed superseded visual-review records and release-list entries from the current documentation. No visual behavior change was made for that cleanup.
- Full headless suite: **155 passed, 1 ignored** (`boss_gpu` requires a graphics adapter). No game window or sound work was used.
- Current rules-12 P01 profiles match all 30/30 state checkpoints. p95 step times were 0.233/0.230 ms for 24 actors, 0.621/0.669 ms for 64, 1.206/0.890 ms for 112, 0.031/0.028 ms for authored wave 14, and 0.013/0.010 ms for boss wave 15. The 112-actor pair straddles the plan's 1 ms target but remains well below the 16.67 ms simulation-step budget; rendering and full-frame timing remain unmeasured.
- The transactional release build validated both archives, executable identity, source/profile rules-version match, deterministic profile checkpoints, manifest hashes, required report/evidence paths, and friend-package exclusions. The full archive includes the Android hypothesis, character audit, both current-scale character sheets, current rules-12 profiles, and the paired boss profiles. The current source revision is `538f746c73f84e194ea9ab9092b059ee86ed240b`, with `sourceDirty: true`.

### Daily challenge, modifier, and RPG reward audit — 2026-11-17

- Daily challenges are keyed to UTC and use a stable date-derived seed with the authored Normal difficulty, Circle arena, and one daily modifier. Personal accessibility and visual settings remain active. The menu refreshes the challenge when UTC midnight passes while it remains open.
- Daily records now persist the challenge seed, normalized modifier set, and simulation-rules version alongside date, score, and wave. Existing save entries without metadata load as legacy records. A changed ruleset or challenge setup starts a fresh comparison and preserves up to eight previous records; old scores are labeled as prior rules/setup in the menu instead of being presented as today's comparable best.
- The daily summary shows the date, fixed difficulty and arena, modifier score multiplier, modifier effect, and either the current-rule best or a clear prior-record label. The guide explains the fixed global challenge rules.
- RPG reward choices now avoid no-op permanent rewards, favor three distinct categories when the pool permits, and still fill all three slots when fewer categories are available. Repeatable permanent rewards display their actual stack count; unique relics remain unique. Temporary effects validate their keys and authored duration caps, and selection cards show active duration/refresh and stack behavior. Reward descriptions now match Ultra cooldown/charge and hull-repair effects.
- A rejected permanent reward leaves the reward selection open. An invalid temporary reward has no side effects. The simulation-rules version remains 13; the record metadata and menu wording do not alter replayed simulation behavior.
- Verification for this follow-up: `cargo check -p plouto_rs` passed. No game window or gameplay tests were run after these changes. The full test-suite count above is from the preceding source state.
- The release bundle and friend ZIP were rebuilt after this report update. Package counts and manifest hashes are recorded in the final release entry after the build completes.

### Gamepad support — 2026-11-17

- Added controller input through gilrs 0.11, in `plouto_rs/src/input/`: `gamepad.rs`, `mapping.rs`, `rumble.rs`, and `glyphs.rs`.
- In a run: left stick moves; right stick aims and keeps its last aim when released; fire is RT, RB, or the right stick pushed past 0.5; A dashes; LT or LB boosts; Y fires Ultra; Start pauses.
- Menus: D-pad or left stick moves the selection (first repeat after 0.35 s, then every 0.12 s); A confirms; B goes back. B and Start are ignored on the main menu, so they cannot quit the game.
- Settings: Gamepad on/off, Vibration on/off, and Stick Deadzone (0.05 to 0.5, default 0.18).
- Rumble plays on player damage, death, boss phase changes and defeat, and large blasts. It is rate-limited and runs only while the gamepad is the active device.
- The active input device switches automatically between mouse/keyboard and gamepad.
- Known limit: a pad that exposes its triggers only as an axis has no analog trigger; use RB and LB instead.
- Verification: the current `cargo test -p plouto_rs` run passes 155 tests, with one adapter-dependent GPU test ignored. A search found no gamepad test in `plouto_rs/tests/` or in the `input` module, so the controller mapping is not covered by an automated test.
- Not verified: real controller hardware, and human play-testing of pad controls, rumble strength, and deadzone feel.

### Achievements overhaul — 2026-11-17

- The set is now 35 achievements: the 20 original ids are kept, and 15 are new: `dash_master`, `overdrive`, `overkill`, `scavenger`, `shield_wall`, `triple_threat`, `every_boss`, `world_tour`, `daily_driver`, `mutant`, `purist`, `endurance`, `five_thousand`, `old_hand`, `clean_sweep`.
- Names, descriptions, categories, secret flags, and conditions are defined in `plouto_rs/src/sim/achievements.rs`.
- Fixes:
  - A hit that the shield absorbs with no health loss counts as a shield block and does not break the Untouchable streak. A hit that removes health does break it.
  - Enemy contact self-destructs no longer count as player kills.
  - A wave clear on the death step no longer counts.
  - Runs ended from the pause menu or by closing the window now settle and count.
  - `--replay` playback never grants achievements, and `--record` runs skip progress writes.
- Mid-run unlock toasts appear only for achievements that cannot regress. Purist waits until the run settles.
- The game-over screen shows new unlocks and up to two "almost there" progress lines.
- The Hangar tab shows categories, completion percentage, progress bars, and secret "???" rows.
- Open policy questions, not decided: abandoned or quit runs inflate `runs_played`-based achievements, and daily retries count as runs.
- Verification: `tests/achievements.rs` has 23 tests, all passing within the current 155-test suite.
- Not verified: toast timing, game-over and Hangar layout, and unlock feel in the live game. No human play-testing has been done.

## Work completed

> Historical note: the passes in this section are undated. Each entry describes the checks it ran at the time. For current state, see Current status.

### Rust release and Python archive

- Moved the Python desktop and browser source base into `archive/python` (224 archived files).
- Made the packaged Rust executable the first choice in `run_game.bat`, with a source-build fallback.
- Updated `build_all.bat` to produce the Rust release folder, a compatibility executable name, and `release/Plouto.zip`.
- Removed local save data from the distributable archive.

### Open arenas and gameplay

- Removed interior obstacles from Rust runs. Defaults and run initialization keep obstacles disabled, and new runs start with an empty obstacle list.
- Audited the power-up catalog and effect dispatch. Every catalog pickup has a working effect and feedback; capped pickups convert into a useful benefit, expired pickups are removed, and Repulsor overflow preserves queued charges.
- Kept arenas open while improving edge clamping and resize behavior.
- Improved enemy steering: committed attacks keep their direction, formation corrections move the actual enemy, and projectile dodging prioritizes dangerous shots without allocating per enemy each frame.
- Added sector-based visual signatures to arena maps and increased menu scaling for large screens.

### HUD and visual feedback

- Replaced the Ultra cooldown number with a circular gauge that fills as the cooldown elapses, with a moving highlight and a clear ready state.
- Added active-power-up and relic badges with remaining-time rings and short animations.
- Added the Aegis Relay run relic: Ultra strikes restore up to 14 shield. Its reward entry, duplicate filtering, shield effect, animated HUD badge, acquisition chatter, and guide entry are connected.
- Added clearer boss action labels and tells across the boss roster.

### Swarmqueen encounter — this pass

- Added a 0.78-second committed windup before brood pods, swarm adds, or a plasma fan.
- Added distinct HUD labels and arena warnings: brood and swarm attacks show their spawn band; the plasma fan shows its locked firing lanes.
- Expanded the Matriarch's wings and brightened its core while it charges an attack.
- Limited egg sacs and summoned adds to remaining arena capacity. If a summon no longer fits when the warning ends, the boss fires its plasma fan instead.

### Boss attack readability — this pass

- The Forge Warden now slows its movement and commits to a 0.72-second lock-on before its spike array and spread volley. Floor markers show the exact future trap positions, and the firing rails show the volley direction.
- The Ocular Abyss now locks its aim and signals for 0.68 seconds before its main salvo. The fan rails and later-phase radial pulse are visible during the windup; the later laser lanes keep their own beam warning.
- Both attacks use the same stored direction and target position for the warning and the release, so the telegraph describes the attack that actually follows.
- The Warden's claws open and core brightens during its lock-on. The Abyss's tendrils coil inward and its pupil grows while aiming.

### Wave progression and entry spacing — this pass

- Aligned enemy-class unlocks with the wave that guarantees their first introduction: ranged fire (2), bombers (3), swarmers (4), engineers (6), tanks (7), snipers (8), and flankers (9). This prevents a role from appearing randomly before its “NEW THREAT” banner.
- Later waves layer the established frontline and ranged roles around the scheduled new role, then add a rotating wildcard as the roster grows.
- Wave enemies now enter from a ring just inside the arena edge. Spawn placement checks separation against enemies already placed and tries multiple candidates before choosing the clearest available position, reducing unfair overlaps while keeping all arenas open.
- Regular waves and boss encounters now also score edge spawn candidates against the player's position, targeting at least 34% of the room radius of breathing room when the arena shape allows. If crowding or a narrow arena shape prevents both player and enemy spacing, the candidate with the best combined clearance is used.

### Wave spawn regression audit — this pass

- Added a deterministic spawn-clearance regression check covering waves 1–20, eight seeds per wave, and all four arena shapes, with the player at the arena start and four cardinal rim positions (3,200 generated wave plans).
- Every checked spawn stayed on walkable floor, preserved the configured player safety gap even with the player at the rim, and remained separated from other enemies by their collision radii plus ten units.
- The audit required no spawn-logic changes. It specifically checks the constrained Cross and Donut arenas as well as Circle and Diamond.
- Reconciled the migration against the prior Python source list: all 202 removed Python files are present in `archive/python`, including the archived tests and tools, with zero missing files. No Python modules remain at the repository root; Rust remains the launch and release target.

### Animated in-game comms — this pass

- Added short, contextual Flight Link messages for wave changes, boss arrivals and phase changes, critical hull, newly active power-ups, Ultra readiness, and arena events.
- Added a signal emblem, radio bars, type-on text, and a brief slide and fade animation.
- Chatter stays below the boss health strip and above the lower-center HUD, and reduced-motion mode removes the animation while keeping the message readable.
- Urgent boss and danger cues move ahead of routine messages in the short queue.

### Enemy attack readability — this pass

- Ranged enemies now pause briefly and show a bright, committed firing lane before the first shot of each burst. Their follow-up shots retain the quick burst rhythm, followed by the existing repositioning move.
- Spitters now mark the center of their aim before releasing either alternating spread fan, giving players time to move across the lane as the fan opens.
- Both enemies hold the marked direction through the windup, and their bodies brighten and swell as the shot approaches. The enemy guide explains how to respond to each tell.
- Removed the ranged enemy's obstacle-cover positioning branch because the Rust game now runs with open, obstacle-free arenas.

### Engineer mine readability — this pass

- Engineers now lock and hold a predicted mine position for 0.54 seconds before deploying. The warning marker uses the exact point where the mine will appear, and formation steering stays paused during the tell.
- Added an expanding floor ring with a lock-progress arc and crosshair. After deployment, mines have a distinct four-stud design that changes from orange while arming to pulsing red when armed.
- Updated the enemy guide with the new mine warning and dodge response.

### Combat scale and bomber blast — this pass

- Increased the player pod, regular enemy hitboxes, boss radius, and projectile hit radii modestly so combat silhouettes and collisions read at a glance. The player pod art grew about 8%; most standard enemy and projectile collision radii grew about 8–12%.
- Made both player and enemy projectile heads and trails thicker and brighter, while keeping each attack's color and shape signature.
- Bomber bombs now display a low-opacity danger zone with a filling timer arc during the last 0.52 seconds of flight. The marked ellipse is projected from the actual 72-unit blast radius.
- Redesigned bomber detonation with a broad expanding edge ring, a delayed inner ring, a hotter core, and a distinct spark burst. Its outer ring now matches the blast's gameplay radius, and this visual is separated from ordinary bomber deaths and volatile-elite blasts.
- Visual reference check: the [official Hades update notes](https://www.supergiantgames.com/blog/hades-the-nighty-night-update-patch-notes/) call out attacks whose visuals better match their hitboxes and clearer floor traps; I applied that readability principle to Plouto's projectile size, mine/bomb warning areas, and blast edge. Official pages for [Brotato](https://store.steampowered.com/app/1942280/Brotato/) and [Vampire Survivors](https://store.steampowered.com/app/1794680/Vampire_Survivors/) were also reviewed as high-density arena-survival references.

### Storm Sovereign boss cycle — this pass

- Added a 0.62-second ring-charge state after each teleport. Floor spokes show the exact stored direction and count of the radial volley; the center and four pylons brighten as the charge completes.
- The release uses that same stored ring angle and projectile count. At phase three, a slower half-density ring fills alternating gaps, and both rings are previewed before either fires.
- Added a distinct “RING CHARGE” boss cue and updated the boss guide with the new dodge pattern.

### Combat silhouettes and bomber impact — this pass

- Enlarged the player pod art by another 5% and increased its gameplay radius from 4.5 to 4.8. Standard enemy silhouettes and collision radii now gain about 5%; the boss radius increased from 32 to 33.6.
- Increased projectile collision radii by 5% and thickened player shots about 6% over their prior rendering. Enemy shot heads, bomber bombs, and boss shots received a small matching visual increase so their danger reads more clearly.
- Rebuilt bomber detonation around a quick orange shock ring that reaches the 72-unit damage radius, followed by two smaller delayed heat rings, a brief hot-center flash, and short radial sparks. Reduced-motion mode lowers the spark count.
- Reference check: the [official Hades update notes](https://www.supergiantgames.com/blog/hades-updates/) include a more distinct Minotaur attack tell and an adjusted nova hitbox. I applied the same readable-warning and hit-area alignment principles to Plouto's bomb. [Brotato](https://store.steampowered.com/app/1942280/Brotato/) describes a top-down arena fight against hordes, and [Vampire Survivors](https://store.steampowered.com/app/1794680/Vampire_Survivors/) centers on surviving large enemy crowds; those references informed the modest silhouette and projectile increases without making the blast itself fill the screen.

### Main menu input focus — this pass

- The pointer now owns the menu focus cue while the mouse is active, so its hover highlight no longer competes with the keyboard outline.
- Arrow or WASD navigation and Enter hand control back to the keyboard immediately, clearing stale pointer hover and restoring the selected control outline.

### Forge Warden arena-aware spike placement — this pass

- Warden spike traps previously used a ring around the predicted player point without constraining each spike to the walkable arena. Near an edge, cross arm, or donut pit, part of the attack could fall outside the floor.
- Spike placement now projects each trap inside the active arena with clearance for its 26-unit radius. The render telegraph calls the same placement function, so every warning marker matches the trap's actual position across arena shapes.

### Tactical animated comms — this pass

- Replaced generic boss arrival and phase-change lines with short, actionable guidance for all eight bosses, based on each fight's actual attack pattern.
- Rewrote power-up chatter to tell the player how to use each active effect, including Repulsor and Chain Surge.
- Kept the type-on animation, alert priority, timing, and reduced-motion behavior intact. The dialogue remains visual-only.

### Sound scope — this pass

- Kept this pass focused on gameplay and visual feedback. No sound cues or sound assets were added or changed.

### Artwork-based 3D characters and engine effects — this pass

- Built shaded, rotating 3D polygon models from the supplied character artwork. The player pod, all 11 regular enemy types, and all eight bosses now use 3D meshes in the isometric arena. Hull depth, faceplates, engine details, wing silhouettes, and boss-specific parts remain visible as models turn.
- The player pod now turns through a damped heading spring, banks with sideways movement, and pitches during dash or boost. Its pupils track aim, and its blink and worried expressions follow the model as it moves.
- Enemy facing eases toward its movement direction. Flyer and swarm wings flap; the engineer's six legs and claws animate; bosses articulate limbs, tentacles, pylons, blades, and rotating rings. Small engine effects add movement cues without changing combat behavior.
- Reduced-motion mode removes model banking and pulse animation and uses fewer, slower engine motes. The changes are visual only; no sound was added or changed.
- Refined the player pod against `assets/artwork/characters/player-classic-pod.png`: a distinct forward cowl, broad curved dark visor, swept cyan eyes built into the mesh, side thrusters, and a rear amber beacon. The raised visor and eye parts are still 3D geometry; only small eye glints and expression marks are screen-facing. Kept the real hull and enlarged the model for gameplay readability.
- Live visual review caught a second visibility problem: the muzzle sat inside the model and the projectile trail extended backward across its face. Moved the standard-fire muzzle to 40 world units and the Ultra muzzle to 28, grew each trail from the projectile's actual travel distance, clipped player trails outside a 32-unit hull clearance, and reduced bloom while keeping a solid colored bullet head. This keeps firing readable without replacing or hiding the 3D model.
- The pod's boost effect remains three short rear-facing flame tongues. Four-heading model sheets and fresh in-game menu/gameplay captures were rendered for review: `release/player_model_four_heading_final.png`, `release/regular_models_4_angles_v4.png`, `release/boss_models_4_angles_v4.png`, `release/live_menu_final.png`, and `release/live_run_final.png`.

### Player pod 3D readability and rotation — this pass

- Reworked the player material values so the non-emissive cyan hull and gold trim stay below the global bloom threshold. The eyes, antenna tip, and engine accents remain small, controlled highlights.
- Increased the model scale from 1.17 to 1.27 and deepened the hull vertically to better match the rounded proportions in `assets/artwork/characters/player-classic-pod.png`.
- Replaced the finely triangulated face patch with a curved, forward-facing 3D visor cap, raised rim, and 3D eye domes. The visor and hull now share one depth-sorted mesh, with back-face culling on the pod, so the face turns out of view naturally instead of showing through the back of the body.
- Added a small screen-space overlap to rendered mesh triangles to close antialias seams at normal gameplay size. This is a rasterization adjustment; the character remains a rotating 3D model.
- Rendered an eight-heading model sheet at the in-game model scale for visual inspection: `release/player_pod_game_scale_rotation_check.png`. This is a screen-space model review sheet; it does not include the final GPU bloom pass.
- No sound code or assets were changed.

### Player model world rotation and hangar preview — this pass

- The pod previously used a normalized screen basis derived from its heading. That made the camera turn with the model, so the visor stayed viewer-facing and the body's up/down proportions changed incorrectly.
- The mesh, face details, thrusters, and boost flames now rotate around the model's world-space up axis and project through the fixed isometric camera. Depth sorting and back-face culling use that same camera, so the visor narrows naturally from the side and turns out of view from behind.
- Eye glints and expressions follow the same 3D transform. The hangar skin cards now preview the real 3D pod rather than a separate flat drawing, with a restrained glow and small idle turn.
- Rendered and reviewed the eight-heading gameplay-scale batch sheet at `release/player_pod_game_scale_rotation_check.png` and its close view at `release/player_pod_rotation_detail.png`. The sheet uses the game's actual mesh batches and excludes the final GPU bloom pass.
- No sound code or assets were changed.

### Origin Nexus and Eclipse Archon articulation — this pass

- Added a `WombPulseTelegraph` state that matches the existing 0.52-second floor warning. The boss cue reads “PULSE WARNING,” and the mesh windup ramps through that same interval.
- Eclipse Archon now has eight articulated arms and four rotating pylons. They orbit at rest, hold a tighter charge pose, extend through the nova burst, and draw back during the phase shift. Rage increases orbit speed; reduced-motion mode pauses ambient movement while preserving each attack pose.
- Render checks compare the actual projected mesh between each boss phase. A simulation check confirms the Origin Nexus model cue and trap warning start and end together.
- No sound code or assets were changed.

### Player pod proportions and screen-direction turn — this pass

- Increased the pod shell's vertical volume and carried that proportion through the forward cowl and visor, so the 3D hull reads as the rounded flight pod in the character artwork instead of flattening into a puck on up/down turns.
- Corrected the rotation review to convert screen-space aim through the game's isometric camera mapping before rotating the actual 3D mesh. The eight-heading review now matches real mouse directions: the visor faces the camera on approach, narrows on side turns, and turns fully out of view when facing away.
- Rendered the eight screen headings from the game's real 3D draw batches for visual inspection. This geometry review excludes the final GPU post-processing pass.
- Tightened the rotation check to cover real screen headings, verify front/side/rear face visibility, and reject collapsed proportions. No sound code or assets were changed.

### Boss art fidelity and all-angle visual review — this pass

- Rendered the regular-enemy and boss sheets from Rust draw batches across eight screen headings, covering all 11 regular enemies and all eight bosses: `release/regular_models_8_screen_angles_current.png` and `release/boss_models_8_screen_angles_current.png`. The regular sheet is an earlier snapshot from before the tank and chaser refinements below; those current models have separate review sheets. These geometry reviews exclude final GPU post-processing.
- The review showed the Gorgon Juggernaut did not match its supplied horned quadruped artwork. Rebuilt its forward head, amber eyes, curled ivory horns, and four heavy legs while keeping its armor and boss-specific palette.
- Added a head-lowering brace during the visible charge warning and a forward lean during the charge. Reduced-motion mode keeps those attack poses while removing ambient gait; existing attack timing and collision behavior remain intact.
- Rendered a close eight-angle view of the updated Gorgon: `release/boss_gorgon_juggernaut_8_angles.png`.
- Extended the boss render check to compare the Juggernaut's telegraph and charge poses and confirm the animated parts stay in the 3D model. No sound code or assets were changed.

### Render coverage and replay consistency — this pass

- The render test roster was stale: it omitted the sniper and Eclipse Archon even though both have 3D models. Expanded it to cover all 11 regular enemies and all eight bosses, dispatch each to its 3D model, and render each in four cardinal headings while checking for finite geometry and visible effects.
- Rechecked all 17 power-up dispatches and emblems, capped-pickup conversions, pickup expiry, Repulsor overflow, and the Ultra cooldown gauge. The full Rust test suite now passes: 25 tests passed, including fixed-camera pod rotation and the Origin Nexus/Eclipse Archon phase checks.
- The replay round-trip check exposed a state-hash mismatch because new open-arena runs defaulted destructible crates on while replay verification forced them off. Destructible crates now default off with obstacles, and replay verification preserves the serialized flag for deterministic hashes; obstacles remain disabled and the arena stays open.
- No sound cues or sound assets were added or changed.

### Player pod vertical proportions and natural facing — this pass

- The pod hull was almost spherical. Rebalanced its world-space width and height into a broader, softly upright ellipsoid, then shaped the chin and visor to match the supplied flight-pod artwork.
- Broadened the curved 3D visor and enlarged the cyan side thruster rings so the pod's artwork details read at gameplay size; these parts remain attached to the rotating mesh.
- Removed the constant idle tilt toward the camera. The model still yaws around the world vertical axis through the fixed isometric camera; its face parts stay on the forward 3D surface and disappear as the pod turns away. Movement pitch remains tied to boost and dash.
- Tightened the face visibility threshold so the visor and eye details turn out of view earlier at side and rear headings.
- The eight-heading review image uses the game's flipped cursor Y convention, so its labels match physical mouse directions. The focused fixed-isometric pod rotation check passes across all headings.
- No sound code or assets were changed.

### Siege tank 3D model and firing animation — this pass

- Rebuilt the tank from `assets/artwork/characters/enemy-tank.png` as a pointed, layered graphite hull with chamfered armor plates, visible side treads, cyan edge trim, paired raised amber gun wells, and a larger faceted cyan reactor. The mesh rotates in world space with the existing isometric camera.
- Road wheels and spokes move with the tank's existing velocity; suspension follows its ram windup. The twin cannons recoil as their existing firing cooldown approaches. The cyan reactor, amber muzzle cues, and charge warning remain separate effects around the real 3D mesh.
- Rendered and visually reviewed all eight screen headings from the current Rust mesh batches at close review scale: `release/tank_model_8_heading_review.png`. The review maps the renderer's bottom-up coordinates into the image correctly and leaves the charge ring out of the model sheet. It excludes final GPU bloom.
- The focused tank render check passes: it verifies cyan and amber model details, finite geometry across eight headings, visible tread and cannon changes during movement/fire, and stable geometry with reduced motion.
- No sound code or assets were changed.

### Chaser interceptor art and lunge animation — this pass

- Recolored and refined the 3D chaser to match `assets/artwork/characters/enemy-chaser.png`: graphite swept-wing armor, a recessed dark cockpit, narrow amber nose and wing marks, cyan leading-edge trim, and one centered rear engine.
- Added small articulated wing fins and a 3D exhaust plume that lengthens with movement and the existing lunge warning. Reduced-motion mode removes idle fin flex while keeping the lunge pose and thrust cue.
- Rendered and reviewed the real Rust mesh at eight screen headings: `release/chaser_model_8_heading_review.png`. The renderer maps the game's bottom-up coordinates into the review image and excludes screen-space warning/glow effects.
- The focused chaser render check passes for the graphite/cyan/amber palette, eight finite headings, lunge cue and 3D exhaust changes, and reduced-motion consistency.
- No sound code or assets were changed.

### Bomber mine-layer art and reactor pulse — this pass

- Reworked `assets/artwork/characters/enemy-bomber.png` into a dark graphite mine-layer with four armored bomb arms, cyan outer-edge markings, amber hazard pods, and a larger layered furnace core. Replaced the former all-orange material treatment with the reference art's controlled graphite, cyan, and amber palette.
- Kept the bomber's existing heading spin and fuse timing. Enlarged the core's visual presence and tied its restrained glow pulse to the current attack countdown; reduced-motion mode holds a steady reactor and stops the idle spin.
- Rendered and reviewed the actual mesh in eight screen headings: `release/bomber_model_8_heading_review.png`. The sheet contains the 3D geometry without screen-space glows and preserves the labeled heading.
- The focused bomber check passes for graphite/cyan/amber materials, eight finite headings, a peak fuse pulse, and stable reduced-motion geometry and reactor brightness.
- No sound code or assets were changed.

### Ranged gunship art and cannon windup — this pass

- Refined the ranged enemy against `assets/artwork/characters/enemy-ranged.png` as a broad, pointed graphite gunship with cyan edge rails and reactor, amber hazard marks, a centered rear engine, and two raised shoulder cannon mounts.
- Added paired 3D barrels that lift into the firing lane and draw back during the existing 0.34-second windup. The small amber muzzle tell follows each barrel through the ship's normal world-space rotation; firing timing and projectile behavior are unchanged.
- Rendered and inspected all eight screen headings from the Rust mesh batches: `release/ranged_model_8_heading_review.png`. The review shows the actual 3D geometry and excludes screen-space glows and final GPU bloom.
- The focused ranged check passes for the artwork palette, windup-driven cannon movement and muzzle tell, finite geometry at eight headings, and stable reduced-motion geometry.
- No sound code or assets were changed.

### Sniper railgun art and charge animation — this pass

- Refined the sniper against `assets/artwork/characters/enemy-sniper.png` into a long, needle-point railgun craft with broad swept rear wings, small mid-body fins, cyan edge rails, graphite armor, and a recessed violet optic and engine.
- The existing 0.92-second lock-on now extends and brightens a narrow 3D energy channel along the twin rail housing. The moving rail tip carries a restrained magenta muzzle tell; the locked aim and shot timing are unchanged.
- Rendered and inspected all eight screen headings from the Rust mesh batches: `release/sniper_model_8_heading_review.png`. The sheet shows the actual 3D model without screen-space glows or final GPU bloom.
- The focused sniper check passes for graphite/cyan/violet materials, charge-driven rail movement and muzzle feedback, finite geometry at eight headings, and stable reduced-motion geometry.
- No sound code or assets were changed.

### Charger forked silhouette and dash pose — this pass

- Rebuilt the charger against `assets/artwork/characters/enemy-charger.png` as a broad delta-wing hull with cyan outer rails, amber vents, a recessed orange core, and paired rear turbines.
- Added two segmented 3D horns with hot inner edges. They curl toward the launch lane during the existing windup, extend during the committed dash, and carry twin rear flames in that same dash pose. The attack direction and collision timing are unchanged.
- Rendered and inspected all eight screen headings from the Rust model batches: `release/charger_model_8_heading_review.png`. The review contains the rotating 3D mesh without screen-space effects or final GPU bloom.
- The focused charger check passes for the artwork palette, windup and dash geometry, dash effects, finite geometry at eight headings, and stable reduced-motion geometry.
- No sound code or assets were changed.

### Spitter acid gunship art and volley animation — this pass

- Replaced the spitter's six-legged bug silhouette with the armored spacecraft in `assets/artwork/characters/enemy-spitter.png`: pointed graphite hull, swept cyan-edged wings, twin raised spray ports, broad lime acid reservoirs, and a centered rear engine.
- Added small suspended 3D bubbles inside both reservoirs. They drift during play, rise and grow with the existing 0.38-second spread warning, and hold still in reduced-motion mode. The alternating three-shot and five-shot fans are unchanged.
- Rendered and visually checked all eight screen headings from Rust mesh batches: `release/spitter_model_8_heading_review.png`. The current review uses gunmetal reservoir rims and lime liquid to match the art; the sheet excludes screen-space glow and final GPU bloom.
- The focused spitter check passes for the graphite/cyan/lime palette, windup response, rising bubbles, eight finite headings, and stable reduced-motion geometry.
- No sound code or assets were changed.

### Flyer crescent interceptor and wing animation — this pass

- Rebuilt the flyer against `assets/artwork/characters/enemy-flyer.png` with a pointed graphite fuselage, broad crescent delta wings, cyan leading edges, amber wing vents and canopy details, and two rear engines.
- The real 3D wings flap through the existing flight animation and sweep into the existing attack warning pose. Twin mesh exhausts lengthen with movement; the small firing tell follows the nose. Steering and attack timing are unchanged.
- Rendered and inspected all eight screen headings from the game's Rust mesh batches: `release/flyer_model_8_heading_review.png`. The sheet shows the rotating 3D mesh without screen-space effects or final GPU bloom.
- The focused flyer check passes for the reference palette, wing flap and windup poses, finite geometry at eight headings, and stable reduced-motion geometry.
- No sound code or assets were changed.

### Engineer repair drone art and claw animation — this pass

- Refined the engineer against `assets/artwork/characters/enemy-engineer.png` while keeping the spherical 3D repair-drone body, antenna beacon, forward visor, and two articulated tool claws.
- Built up the layered graphite armor and raised brow, made the two amber optics and top beacon read clearly, and gave the chest reactor and hover ring a restrained cyan treatment.
- Kept the face on the forward surface of the model so it naturally turns out of view as the drone rotates away. The claw mine-placement pose remains visible in reduced-motion mode; reduced motion only removes ambient sway.
- Rendered and visually reviewed the actual Rust mesh at all eight screen headings: `release/engineer_model_8_heading_review.png`. The heading labels follow the game's cursor convention; the sheet excludes screen-space effects and final GPU bloom.
- The focused engineer render check passes for the artwork palette, articulated claws, windup reactor effect, finite geometry at eight headings, and stable attack pose in reduced-motion mode.
- No sound code or assets were changed.

### Swarm delta fighter proportions and flight pose — this pass

- Rebuilt the 3D swarm fighter against `assets/artwork/characters/enemy-swarm.png`: a broad layered graphite delta hull with swept shoulder armor, cyan leading rails, paired warm wing marks, and a forward orange-red optic.
- Increased its in-game model scale by about 25% so the distinctive wing span reads at gameplay distance. The optic sits on the forward surface and turns away naturally with the hull instead of staying visible at every heading.
- Added small articulated wing panels that flutter in flight and a restrained optic pulse. Reduced-motion mode keeps a steady 3D pose.
- Rendered and visually reviewed the real Rust mesh at all eight screen headings: `release/swarm_model_8_heading_review.png`. The face is only visible when its surface faces the camera; the sheet excludes screen-space effects and final GPU bloom.
- The focused swarm render check passes for the graphite/cyan/orange-red palette, wing animation, true 3D rotation, eight finite headings, and reduced-motion consistency.
- No sound code or assets were changed.

### Egg sac shell split and hatch telegraph — this pass

- Refined the existing grounded cocoon concept; there is no separate egg-sac character artwork in the project. The enlarged 3D form now has a tapered plum-charcoal shell, six swept ribs, a single seam, a low anchor collar, and four feet that keep it planted.
- Moved the warm hatch core into a recessed forward slit. Its face follows the cocoon's 3D rotation and turns out of view naturally.
- The two front shell plates slide apart as the four-second hatch timer runs down, exposing a brighter, larger core. The gameplay timer and spawned swarm count are unchanged; the urgency pose stays active with reduced motion.
- Rendered and reviewed the actual mesh at all eight screen headings: `release/egg_sac_model_8_heading_review.png`. The review shows the near-hatch pose and excludes screen-space glow and final GPU bloom.
- The focused egg-sac check passes for shell and core colors, hatch-driven plate movement and glow, eight finite headings, natural face rotation, and reduced-motion consistency.
- No sound code or assets were changed.

### Prisma Overlord crystal art and laser-lock pose — this pass

- Rebuilt the Prisma Overlord as a tall, faceted violet monolith with a vertical halo, a recessed magenta slit eye, and twin forward crystal wings, following `assets/artwork/characters/boss-prisma-overlord.png`.
- The wings fold toward the eye during the existing laser lock. The phase-two halo carries four smaller moving collimator crystals; reduce-motion mode holds them steady.
- Rendered and inspected the actual model in all eight headings: `release/boss_laser_model_8_heading_review.png`. The eye follows the 3D face and naturally leaves view at side and rear angles.
- Added focused checks for its tall silhouette, varied crystal materials, wing-fold animation, and reduced-motion stability.
- No sound code or assets were changed.

### Storm Sovereign 3D cross and crystal volley pose — this pass

- Replaced the floor-oriented rotor with an upright, beveled cross built from a thick 3D hull. The model follows `assets/artwork/characters/boss-storm-sovereign.png` with slate armor, gold trim, a recessed cyan vortex, and four faceted crystals.
- Mirrored the armor and core details on both faces so the cross turns naturally with its heading. The face turns out of view from the side and rear; the four crystal sockets extend slightly during the existing radial-volley windup. Attack timing and damage remain unchanged.
- Rendered the Rust mesh at all eight headings and added a regression check comparing its face-on width with its side profile: `release/boss_thunder_model_8_heading_review.png`.
- No sound code or assets were changed.

### Ocular Abyss eye mask and tendril pose — this pass

- Rebuilt the boss around an upright purple eye mask with an ice-cyan iris, a sharply defined vertical pupil, magenta crown and jaw gems, and six thicker curling tentacles based on `assets/artwork/characters/boss-ocular-abyss.png`.
- The tentacles flex and pull inward during the existing fan attack warning. The eye glow and pupil follow the real 3D face and disappear when it turns edge-on; the attack timing and damage are unchanged.
- Rendered and visually reviewed all eight headings: `release/boss_abyss_gaze_model_8_heading_review.png`. Added a regression check for the eye glow turning off at the side heading.
- No sound code or assets were changed.

### Forge Warden upright armor and cannon pose — this pass

- Rebuilt the Forge Warden as an upright bronze golem with a toothed back gear, helmet and visor, recessed furnace chest, reinforced waist, and articulated legs, following `assets/artwork/characters/boss-forge-warden.png`.
- Rotated the forward face toward its target and moved both cannon gauntlets into the same 3D pose as the artwork. The four short muzzles and three-prong claws stay housed in the hands; the arms drive outward during its existing spike-array warning.
- Added a dedicated bronze and furnace palette plus an articulation regression check. Attack timing, traps, and damage are unchanged.
- Rendered and visually reviewed all eight headings: `release/boss_trapmaster_model_8_heading_review.png`.
- No sound code or assets were changed.

### Brood Matriarch 3D proportions and attack poses — this pass

- Rebuilt the queen from `assets/artwork/characters/boss-brood-matriarch.png` as an upright 3D insectoid with a raised jeweled crown, forward-facing eyes, heart-shaped chest armor, four segmented abdomen plates, four crystal nodes, two plated claws, six articulated legs, and broad tapered wings.
- The wings now attach to the shoulder joints and keep their purple membrane on both sides. Their pose changes for brood, swarm, and plasma-fan warnings; the claws also rise or spread with the matching attack. Reduced-motion mode holds each attack pose and removes only idle movement.
- Removed the old screen-flat wing and body overlay. The 3D model now owns the full silhouette, avoiding the broad billboard panels that flattened the queen during turns.
- Rendered and reviewed both idle and plasma-fan poses across eight screen headings from Rust draw batches: `release/boss_swarmqueen_model_8_heading_review.png` and `release/boss_swarmqueen_volley_model_8_heading_review.png`. These model reviews exclude the final GPU bloom pass.
- Extended the existing boss articulation regression check to verify the queen's upright proportions, stable connected geometry, and distinct brood, swarm, and volley poses. No attack timing or damage changed.
- No sound code or assets were changed.

### Origin Nexus heart, gyroscope, and pulse pose — this pass

- Rebuilt the Origin Nexus around a suspended, multi-lobed heart with a raised heart-shaped breastplate, open support cage, and a dedicated purple, graphite, cyan, and magenta palette, following `assets/artwork/characters/boss-origin-nexus.png`.
- Replaced the three static rings with thick, independently precessing 3D gyroscopes. Added ring-mounted crystal clusters and metallic filigree that stay attached while the rings rotate.
- The cage ribs flex during idle motion and close with the existing 0.52-second floor-pulse warning. Reduced-motion mode stops ambient precession while retaining the contracted attack pose.
- Rendered and inspected idle and pulse-warning sheets at eight headings from Rust draw batches: `release/boss_womb_core_model_8_heading_review.png` and `release/boss_womb_core_pulse_model_8_heading_review.png`. The sheets exclude final GPU bloom.
- Extended the existing boss articulation check for ring motion, reduced-motion stability, pulse contraction, and retained model geometry. Attack timing and damage are unchanged.
- No sound code or assets were changed.

### Fresh packaged HUD cursor review — this pass

- Launched the current packaged Rust build with an isolated, muted profile and captured its live WGPU output at 1280×720: `release/live_build_hud_check.png`.
- The typewriter message now renders a thin animated line at the end of the text. The unsupported block cursor glyph is absent in the actual packaged build.
- The temporary profile kept test settings and progress separate from the user's game data. No sound code or assets were changed.

### Eclipse Archon crown, event horizon, and ring attacks — this pass

- Rebuilt Eclipse Archon against `assets/artwork/characters/boss-eclipse-archon.png`: a visible black event horizon and cyan-green corona now sit inside eight separate beveled violet armor blades. The open gaps keep the core exposed at front and side headings; the former filled plate and detached screen-space glow are gone.
- Added three independently precessing 3D orbit rings with attached satellites. The crown and rings extend during the existing charge and nova burst states, while reduced-motion mode holds the idle pose steady and keeps the attack pose readable.
- Added a dedicated graphite, violet, cyan-green, and magenta palette. Attack timing, damage, and collision remain unchanged.
- Rendered and visually inspected idle, charge, and burst poses at eight headings from real Rust draw batches: `release/boss_eclipse_archon_model_8_heading_review.png`, `release/boss_eclipse_archon_charge_model_8_heading_review.png`, and `release/boss_eclipse_archon_burst_model_8_heading_review.png`. The sheets omit final GPU bloom.
- Extended the existing boss articulation regression check for ring precession, reduced-motion stability, charge extension, and burst extension. No sound code or assets were changed.

### Ultra HUD label spacing — this pass

- A live 1920×1080 gameplay review showed the `ULTRA` label crossing the supernova emblem inside the radial cooldown gauge.
- Moved the emblem lower in the circle and the label above it, keeping the animated cooldown arc and charge pips in place so each cue has its own space.
- No sound code or assets were changed.

### Animated comms cursor — this pass

- The typewriter message cursor used a block glyph that the active font did not contain, so it rendered as a missing-character placeholder after in-game callouts.
- Replaced the text glyph with a small animated SDF line at the measured end of the visible message. Reduced-motion mode removes the blink.
- Added a regression check for the missing glyph and the cursor geometry.
- No sound code or assets were changed.

### Combat logic, flock spacing, and boss phase cues — this pass

- Added a short 0.08-second damage grace window after a landed hit. Several pellets or hazards resolving in one frame can no longer multiply one impact into a sudden damage burst; shield hits still count in run statistics.
- Restricted formation cohesion to the same enemy type so frontline, flank, and ranged roles stop pulling toward one shared center. Swarm fighters now remain under their dedicated encircle/surge/regroup controller instead of being redirected by the general formation pass.
- Spaced live swarm fighters into evenly distributed orbit lanes, reduced their inward crowding during surges, and added deterministic body-overlap resolution after movement. The shared flock mode clock now follows enemy time and slows correctly during Time Slow.
- Fixed a boss warning gap: when one hit crossed both the 35% rage and 33% phase-three thresholds, the rage banner suppressed the phase-three pattern cue. The combined banner now reports both.
- Added simulation checks for same-frame projectile damage, a 20-fighter swarm through its mode cycle, slow-time flock pacing, the complete regular-enemy roster, and all eight bosses through phase changes and active movesets.
- No sound code or assets were changed.

### Full combat and squad-logic recheck — this pass

- Kept swarmers and stationary egg sacs out of the regular formation anchor and slot groups. Their locations no longer pull chaser, ranged, or engineer squads away from their own roles.
- Confirmed the 11-role live roster remains in bounds and collision-clear after six simulated seconds. The initial circle/Normal sweep kept 2.95 world units of body clearance; this pass expanded the check to all four arena shapes and all three difficulties (12 combinations), including egg-sac hatching.
- Extended the boss regression so each of the eight bosses must emit an attack during phase II and phase III after lingering hazards from the prior phase are cleared.
- Added direct damage checks across Easy, Normal, and Hard to verify difficulty scaling occurs before shields absorb the hit. Multiple same-frame projectiles still resolve as one landed hit.
- Fixed the long-run bot so it chooses both rewards after boss clears and approaches targets beyond its weapon range. With one shared seed and a simple orbit-and-approach policy, it reached wave 23 on Easy, wave 27 on Normal, and wave 8 on Hard. The Hard run ended at about 133 seconds; the other runs reached the 400-second simulation limit or ended near it. This is a deterministic regression sample, not a substitute for human balance playtests.
- No sound code or assets were changed.

## Build and verification

> Historical note: the counts and check results in this section (for example, "54 tests") were correct for the passes they describe. The current count is 88; see Current status.

- `cargo check --workspace --all-targets` passed after the combat and squad-logic recheck.
- `cargo test -p plouto_rs` passed with 54 tests: 11 library tests, 28 render/UI tests, and 15 simulation/save tests. This run includes the expanded mixed-roster check across all four arena shapes and all three difficulties.
- Existing checks still cover all 17 power-up effects, Ultra cooldown behavior, wave spawn safety, all 11 enemy and eight boss render coverage, non-degenerate triangles at every heading, player and boss rotation, boss animation timing, replay verification, and enemy health indicators.
- Focused render checks pass for tank, chaser, bomber, ranged, sniper, charger, spitter, flyer, engineer, swarm, egg sac, Prisma, Storm Sovereign, Ocular Abyss, Forge Warden, Brood Matriarch, Origin Nexus, and Eclipse Archon. Their model sheets are rendered from Rust 3D draw batches and visually reviewed; they exclude the GPU bloom pass. The live WGPU capture covers first-wave chasers and chargers with bloom enabled.
- Earlier power-up, spawn-clearance, UI, boss, player rotation, and projectile-visibility checks remain recorded above. Rust formatting could not be run because the installed toolchain does not include `rustfmt`.
- The focused chaser render check verifies lunge-driven fins and engine plume, the artwork palette, and stable geometry in reduced-motion mode. Its eight-heading review image is generated from the actual 3D batches without the final GPU bloom pass.
- The optimized Rust release build and `release/Plouto.zip` are refreshed after this combat and HUD pass. The bundle includes this report and twenty-six visual-review images, contains no local save files, and ships matching main and compatibility executable hashes. The outdated regular-enemy snapshot and pre-rework combined boss overview stay out of the archive; current player, regular enemy, boss, Origin Nexus, Eclipse Archon idle/charge/burst, and live GPU review sheets are included.
- Rust formatting could not be run because the installed toolchain does not include `rustfmt`.

### Friend-ready package — this pass

- Added `release/Plouto_for_friend.zip` as a ready-to-extract Windows game package with the Rust launcher, required assets, window icon, and a short `README.txt` with launch steps and controls.
- The friend package excludes Python files, local progress/settings, development reports, and review screenshots.
- Verified that the launcher hash matches the current packaged Rust executable and that the archive contains the assets and run instructions.

### Explosive reloads, pickup balance, and enemy recovery — 2026-11-16

- Reviewed the reported bomb/mortar behavior against the current arsenal: its explosive primaries are Heavy Cannon missiles and Flak Battery clusters. Both now enforce minimum reload windows even with stacked fire-rate rewards and cadence jitter. Heavy Cannon fires about every 0.95s with a 0.70s floor; Flak fires about every 1.10s with a 0.85s floor.
- Added real radial damage: Heavy Cannon blasts reach 112 world units and Flak blasts reach 76, with damage falling toward the edge. Direct targets receive the direct hit once; splash excludes that target. Missiles detonate on impact, expiry, and spent boundary travel. Flak keeps its shrapnel and adds the radial blast. Blast rings use the same radius as damage.
- Reduced Flak detonation shake from a 5-unit impulse per shell to a 1.2-unit impulse capped at 3.0. The three-shell volley no longer repeatedly drives the camera to the full shake cap.
- Weapon pickup durations: Heavy Cannon 8s, Flak 6s, Railgun/Plasma 12s, lighter weapon pods 20s. Expiry restores the regular primary. Permanent wave-earned weapons remain permanent.
- Ion Beam lasts 5s, fires on its own 0.32s cooldown, and uses a 20-unit-wide piercing lane. It no longer inherits a rapid primary's firing interval. Singularity lasts 6s with a radius increased from 70 to 110. Drone lasts 8s, Ricochet 6s, Homing 5s, and Chain 5s. Time Slow, defensive pickups, and utility pickups retain their existing windows.
- HUD buff rings use the actual new durations, and the weapon chip now has a reload bar based on the scheduled shot interval. Updated the guide descriptions for pickups, bomber, and tank.
- Bomber now locks its target during a 0.60s windup, then lobs a bomb whose speed agrees with its 1.25s fuse. Its recovery is 2.8–3.3s before attack-speed scaling. Previously fixed slow velocity caused distant bombs to fall short of their intended target.
- Tank now marks its cannon lane during a 0.48s windup and reloads for 1.9–2.2s before attack-speed scaling. Formation steering preserves both new windup states.
- Charger charges time out after 1.15s and enter recovery when a target cannot be reached at the arena boundary. Capped chaser prediction at 0.35s to avoid steering toward a distant projected player position.
- Plasma now has a center projectile: three 9-damage base pellets replace two 12-damage base pellets that could straddle a small target at the crosshair. Headless progression exposed this aiming gap.
- Cadence jitter is sampled when firing rather than consuming random values every simulation frame. Updated the headless bot to lead moving targets and approach within Flak range. The hatch check tracks newly hatched fighters rather than requiring the original fighter to survive; the progression check still requires the target wave and boss reward completion, with a 90s minimum instead of requiring Easy/Normal survival to an arbitrary 300s cutoff.
- Verification: `cargo test -p plouto_rs` passed all 59 tests (11 library, 28 render/UI, 20 simulation/save). Five new regressions cover explosive reload/splash, firing intervals, pickup expiry/restoration, bomber/tank windup/recovery, and stuck charger recovery. No interactive game was launched for this pass.
- Updated the build script to refresh `Plouto_for_friend.zip` automatically from the newest executable and assets, keeping local settings/progress out of that archive. No sound changes.

## Ongoing scope

> Historical note: the 2026-11-16 and 2026-11-17 entries record the state at the time. Statements such as "no test suite was run" or "cargo check passed" apply only to that pass. For current state, see Current status.

### Detailed improvement roadmap — 2026-11-16

- Created `docs/plans/GAME_IMPROVEMENT_PLAN.md`, a roughly 19,500-word plan with 30 numbered sections, a linked table of contents, phased delivery, an ordered implementation backlog, dependencies, risks, and completion criteria.
- Grounded the current baseline in Rust source and the latest report. Future designs and candidate tuning ranges are explicitly distinguished from implemented behavior and verified results.
- Included every regular enemy, all eight bosses, damage/collision, cooldowns, weapon and pickup interactions, squad/swarm movement, open arena encounters, progression, artwork/proportions, animation, effects, menus/HUD, accessibility, performance, replay/save integrity, and distribution.
- Preserved the user's requirements: no sound work, no new blocking obstacles, proper rotating 3D models faithful to artwork, and no interactive game testing unless requested.
- Checked the Markdown structure, all 30 contents links, numbered section coverage, and code-fence pairing. This was a documentation pass; no game source changes, runtime launch, game tests, or release rebuild were performed.

The requested source changes and headless checks are complete for this pass. Existing live captures predate this balance pass; they do not verify the new reload bar or balance changes visually. Per the latest direction, additional in-game playthroughs and captures will only be done if requested. Sound remains out of scope.

### Damage resolution and projectile impact order — 2026-11-16

- Began the 37-task implementation ledger in `docs/plans/GAME_IMPROVEMENT_PLAN.md`. C01–C04 now record implemented source changes with focused scenario verification still pending; the remaining 33 tasks stay explicitly open.
- Added a structured `DamageResult` containing source, target, raw and adjusted damage, shield and health damage, rejection reason, and kill result. Enemy damage now returns this record and emits it through the simulation event stream. Player damage candidates are also source-tagged and resolve to the same record; statistics and player damage feedback use its resolved amounts.
- Replaced vector-order player damage selection with a deterministic same-step rule: resolve the strongest eligible hit, use the longer contact grace as the first tie-break, then source name. Other same-step candidates receive a `SupersededByStrongerSameStepHit` result with no false popup. Existing invulnerability still rejects later-step hits. The 0.25s stunned-contact and 0.6s boss-contact grace windows remain explicit.
- Kept earlier hits ahead of same-step healing pickups, while late beam hits resolve after the pickup pass. This preserves the existing damage/healing order while grouping collisions that previously depended on which enemy/projectile happened to be visited first.
- Added a first-contact segment/circle calculation and sort player projectile hits by path segment, contact time, and stable enemy ID. Piercing shots now resolve every target crossed during the same fixed step up to their pierce budget. Ricochet shots preserve incoming and reflected legs for collision checks.
- Unified player missile/Flak retirement through one detonation handler. Direct enemy impact, reflection, boundary exhaustion, obstacle contact, and expiry remove the projectile before triggering one effect. Explosions and fragments start at the actual contact point; splash still excludes a direct-hit target. Splash kills now retain the configured powerup-edge kill order and trigger Tank death blasts consistently with direct kills.
- Projectile travel now stops at the exact remaining TTL instead of advancing a full frame beyond expiry. Enemy projectiles test their final swept segment before an expired bomb detonates.
- Checks: `cargo check -p plouto_rs --all-targets` passed after the final edits with no warnings. No test suite was run, no game was launched, and no visual or human-play review is claimed.
- No sound code or assets were changed. No release package was rebuilt in this implementation pass.
- Remaining evidence for C01–C04: focused headless cases for reversed hit storage order, shield-only outcomes, earliest targets, multiple pierce contacts, bounce path order, exact TTL, boundary/obstacle retirement, and one-time splash/chain cleanup. Next implementation dependencies are C05/C06, followed by shared pickup/reload rules and enemy/boss work.

### Enemy clocks and interrupted attacks — 2026-11-16

- Continued C05's source inventory. The fixed simulation clock advances only in active `step()` calls; hitstop returns early, and pause/reward screens do not advance combat. Player timers and player projectiles use world/player time. Enemy behavior, enemy shots, traps, thunder lines, hostile beam warnings, and their lifetimes use Time Slow-scaled `enemy_dt`. Arena event schedules remain on world time, and Repulsor stun duration remains a player-applied world-time status.
- Corrected two confirmed enemy-clock mismatches: elite Mender recovery/heal interval now advances on `enemy_dt`, and Reflector's cooldown is now a remaining-time counter decremented on `enemy_dt` instead of a global absolute deadline. The Mender pulse animation remains on unscaled visual time, and stunned Menders cannot heal.
- Added one cancellation path for interrupted enemy actions. Repulsor stun removes stale windup telegraphs, clears committed sub-states and charge/volley remnants, stops the committed movement, and establishes at least 0.65s recovery. Boss phase changes use the same cleanup with a 0.35s recovery; already launched projectiles and deployed floor hazards continue under their own truthful cues.
- Checks: `cargo check -p plouto_rs --all-targets` passed after the clock and interruption edits. No test suite or game launch was performed. No visual or human-play evidence is claimed.
- No sound code or assets were changed. Focused clock, stun-during-windup, and threshold-crossing scenarios remain pending. C05's full timer inventory and C06's scenario verification remain open.

### Pickup rules, reload debt, and bounded interactions — 2026-11-16

- Added a Rust simulation definition for all 17 pickup categories. Rarity feedback, timed-effect durations, HUD ring denominators, and guide timing copy now read from the shared definitions. Weapon durations remain weapon-class specific and the guide derives its list from the weapon table. Existing gameplay values and sound classification were retained.
- Weapon pods now temporarily equip a valid weapon regardless of rank. A second pod replaces the current temporary weapon while retaining the original base weapon; expiry restores that base. Invalid saved or authored weapon keys roll through the normal wave weapon selection instead of silently becoming the basic gun.
- Weapon changes preserve the outstanding shot deadline and impose the new weapon's minimum cadence from the last shot when needed. Restoring the base weapon applies the same rule, including when a pending shot was scheduled under a faster temporary weapon or Ion Beam interval.
- Capped chain lightning to eight successful links per fixed simulation step. Existing critical shards remain bounded by their 24-shard pool. Flak produces four short-lived fragments per shell, with three shells per configured volley (at most twelve fragments per volley); fragments cannot recursively split into critical shards.
- Added a 0.45-second per-enemy boost-ram interval so overlap cannot apply full ram damage every simulation frame. Boss contact retains boss damage/grace, stunned normal enemies do not hurt through passive contact, and shove effects occur on the actual ram interval. Dash aiming now falls back to movement or a stable heading when the aim point coincides with the player.
- Checks: `cargo check -p plouto_rs --all-targets` passed after these edits. No test suite, game launch, visual review, or release build was run. No sound assets or audio behavior were edited.
- Remaining evidence: focused pickup swap/expiry timing, chain-limit, multi-shell fragment count, boost overlap, stun contact, and all-arena dash boundary scenarios. W01/W03/W04/W05 are source-implemented; scenario verification remains open.

### Weapon output ledger and enemy commitment pass — 2026-11-16

- Added `docs/design/WEAPON_OUTPUT_LEDGER.md`, deriving base damage, trigger payload, nominal cadence, pierce ceiling, splash falloff, fragment count, and pickup reload slots from the Rust weapon and projectile definitions. It explicitly calls these source formulas and hit-potential ceilings, not observed DPS or playtest results.
- Added `docs/design/ENEMY_BEHAVIOR_SHEETS.md` with movement/attack cycles, warning and recovery timing, target-lock rules, caps, and source-level limitations for all 11 regular enemy roles. Added missing Swarmer and Egg Sac entries to the in-game field guide and updated Bomber, Tank, and Charger timing guidance.
- Put projectile avoidance on a short 0.16s response and role-specific cooldowns from 0.52s to 1.15s, all advanced on enemy time. Chaser lunge and the committed Sniper/Charger/Flyer sequences suppress evasion.
- Fixed two confirmed commitment leaks: the Flyer now exits a dash on arrival or a 1.35s timeout, and Chaser/Charger/Flyer warnings are removed when they launch instead of lingering after commitment.
- Bomber warnings now mark the locked destination with an isometric ring using the exact gameplay blast radius. During flight, the marker follows the projectile's predicted fuse endpoint. Bomber warning intensity is normalized to its 0.60s timer; Tank cannon charge now reads the 0.48s Tank windup state directly.
- Reworked role formation assignment to persist each enemy's slot. New or removed members no longer renumber all other members in that role lane; a newly opened slot is reused, with additional members placed on outer rings.
- Checks: `cargo check -p plouto_rs --all-targets` passed. No tests, interactive launch, final GPU visual review, or release build were run. No audio or sound assets were changed.
- Evidence still pending: target-area and tank-art review in a final GPU capture, evasion response timings, Flyer boundary timeout scenarios, local slot churn scenarios, and real hit-rate measurements. This pass advances E01–E04 but does not claim encounter balance or visual approval.

### Enemy attack pressure, crowd spacing, and swarm/hatch control — 2026-11-16

- Added a regular-enemy attack scheduler. It counts existing windups and committed charges by attack weight, limits new commitments according to live crowd size, spaces same-role starts, and grants at most one overdue regular attack per simulation step after prolonged denial. The forced grant has a separate minimum gap so a sustained crowd cannot bypass the budget every frame. Boss attacks retain their existing authored cadence; the presence of a boss reduces regular-enemy commitment capacity.
- Replaced the swarm's shared synchronized mode with three independently timed subgroups. Their encircle, surge, and regroup transitions start staggered and continue on enemy time. Stable subgroup and lane keys come from each fighter's run spawn key, so a death does not renumber the survivors. Alignment and cohesion now operate within each subgroup; the mixed body-spacing pass handles contact with all enemy roles.
- Added deterministic body-clearance resolution for mixed enemy crowds. Bosses, egg sacs, stunned enemies, and enemies with committed attacks remain anchored; free enemies separate from them and one another. Clearance has a per-enemy movement ceiling and clamps to the open arena geometry.
- Egg sacs now hatch only into the remaining non-boss spawn budget. Each child searches several ring positions, projects them onto valid arena floor, and avoids current and queued bodies. A final queue-commit guard applies the same cap to pending boss adds and other summoned enemies while preserving the configured boss-wave add allowance.
- Checks: `cargo check -p plouto_rs --all-targets` passed with no warnings. This was a compile check only; no test suite, game launch, visual review, or human-play balance check was performed. No sound code or assets were changed.
- Evidence still pending: scheduler cadence and forced-grant scenarios; mixed anchor/crowd cases across arena shapes; subgroup stability after casualties; hatch behavior at capacity and arena boundaries; and visual/human-play confirmation that attack pressure and crowd displacement feel fair. E05–E08 are source-implemented, not encounter-validated.

### Boss transitions and eight-encounter sequence pass — 2026-11-16

- Consolidated boss phase and rage changes into one `BossTransition` result consumed by the banner flow. Crossing more than one health threshold reports the final phase once. A phase change cancels its unlaunched state/telegraph, pauses the boss for a minimum 0.35 enemy-clock seconds, then lets it start the new phase. Already released projectiles and hazards retain their own warning and finish. Each boss projectile, laser, trap, and thunder line now records its boss source; defeating that boss clears only those owned threats while leaving living support enemies intact.
- Storm Sovereign lightning lanes are now generated as a locked parallel set around the predicted target. The lane count is one in phase I, two from phase II, and three only for an aggressive final-phase persona, with deliberate spacing and a full warning second. The regular radial projectile ring remains a distinct simultaneous pressure layer.
- Prisma Overlord no longer rolls an extra untelegraphed projectile ring every active frame. The final phase instead ends its sweep with a 0.46s wing-release warning; the three visible fan rails match the released five-shot fan, and the 3D wings open for that state.
- Forge Warden's existing target markers were source-checked against the same position helper used to place spike traps. Brood Matriarch now commits exact, arena-legal, body-separated egg or swarmer positions when its warning begins. The floor markers show those positions, and the same stored coordinates are used when the adds are queued. Capacity changes can reduce the number at release but cannot create unmarked points.
- Gorgon Juggernaut's charge line now stops at the first boundary for the selected arena shape, including the Donut inner edge. Phase II gains one marked close pulse after a wall impact. Phase III can perform a bounded two-charge sequence: a shortened first rush, a short recovery, a separately aimed 0.62s warning, and a shorter follow-up charge before its final cross-lane warning. The Ocular Abyss's drawn radial ring was not backed by damage; it has been removed, leaving its fan rails to match the actual locked fan and beam lanes.
- Origin Nexus's warning and damage traps are now added as an atomic pair, so the global trap cap cannot admit a visible warning without its damage volume (or a damage volume without the warning). Eclipse Archon's radial safe gap now remains fixed through its full burst; during charge, the actual 3D model turns to the locked lane and its visible sector rails use the exact +/-0.42-radian gap boundaries.
- Checks: `cargo check -p plouto_rs --all-targets` passed. No test suite or game was launched; no boss fight, rendered frame, or human fairness result is claimed. No sound code or assets were changed.
- Remaining evidence: phase-threshold skips, stun/death during each telegraph, trap-cap behavior, boss-owned cleanup after death, all eight bosses' phase timing and recovery, warning/model alignment, and human escape-route review. B01–B05 are source-implemented with encounter verification pending.

### Versioned replay fingerprints and early divergence reporting — 2026-11-16

- Replay format version 4 now stores a simulation-rules version, a comprehensive state fingerprint, checkpoints every 300 fixed steps, and a final checkpoint. The fingerprint includes player state, ordered enemy/shot/hazard/pickup state, AI timers and commitments, run progression, ability systems, score and stats, arena events, and pending damage. The one simulation `HashMap` is sorted by enemy ID before hashing; entity vectors retain simulation order.
- The recorder captures checkpoints from the live simulation after each fixed update. Reward decisions update a checkpoint at the same frame after both reward choices have applied, and the verifier applies choices before comparing that frame checkpoint.
- Replay verification stops at the first failed checkpoint and reports its frame. Format versions 1–3 retain their historical hash algorithms. Unknown future formats and unsupported version-4 rules versions fail with an explicit message rather than producing a misleading mismatch.
- Checks: `cargo check -p plouto_rs --all-targets` passed. No replay was executed and no test suite was run, so determinism, legacy-file compatibility, and early mismatch behavior remain unverified at runtime. No sound code or assets were changed.

### Complete Rust source archive and release package — 2026-11-16

- Purpose: deliver a usable Windows build to a friend while keeping a complete review archive of the Rust project and the preserved Python base.
- Corrected the review ZIP scope. `release/Plouto.zip` now contains the playable Rust bundle, assets, Rust workspace manifest and source, Rust tests/examples as source material, release/build helpers, the full `archive/python` tree, improvement plan/report, behavior and balance references, and any explicitly selected review images available at build time. Rust `target` output and local save/settings files are excluded.
- Kept `release/Plouto_for_friend.zip` focused on the Windows game, required assets and icon, launch/control instructions, and a package-only manifest. It excludes the source archive, development documents, review captures, and local player data.
- Normalized ZIP entry separators during validation so source paths are checked consistently on Windows. The build pipeline stages both archives and the runnable folder, checks required source/runtime entries, verifies every manifest file's SHA-256, confirms the two full-bundle executable names match, confirms the friend's executable matches, rejects local save files, and only then replaces the prior release set with rollback backups available during promotion.
- The README now explains the separate roles of the review archive and friend ZIP. Each archive manifest records product/release version, simulation-rules version, build identity, and per-file size and hash; the manifest does not recursively hash itself.
- Checks: PowerShell parser accepted both packaging scripts. The optimized `cargo build --release --bin plouto` completed successfully. The packaging script validated the full bundle and both ZIPs, including required Rust source and `archive/python/ARCHIVE_INFO.md`, all manifest hashes, executable identity, required assets, and friend-package exclusions. The final bundle manifest records release 0.1.0, simulation-rules version 2, and 411 content files; its source tree retains all 224 archived Python files. The release script was rerun after this report and plan update, so both delivered archives contain the final documents.
- No test suite, game launch, or audio/sound work was performed in this pass. The prior compile-only checks remain the source evidence for code changes; no gameplay or visual result is newly claimed here.
- Remaining work after packaging: perform the deferred in-game visual and human-play review only when requested; run the focused timing/damage/boss/squad scenarios and replay checks only when requested; collect measured performance evidence before optimizing P01; and decide separately whether the Rust arsenal should gain a true ground-targeted Mortar, since no weapon with that name exists in the current source. No claims of final balance approval or full roadmap completion are made.

### Time Slow aware enemy attack scheduling — 2026-11-16

- Static timer review found one gap in the clock inventory: enemy attack denial accumulated on `enemy_dt`, but same-role staggering and the forced-attack gap compared timestamps against unscaled `state.time`. Under Time Slow, this could compress spacing between enemy attacks even while each attack sequence slowed.
- Added `SimState.enemy_time`, advanced only by the accepted `enemy_dt`. Regular attack start and forced-start timestamps now use that clock, as do swarm subgroup clock comparisons. This makes attack permission spacing follow the same Time Slow scale as enemy movement and attack cooldowns. Player cooldowns and arena events remain on world time by design.
- Expanded `docs/design/SIMULATION_CLOCKS.md` with explicit ownership for scheduler timestamps, enemy state timers, player deadlines, hostile/player projectile and hazard clocks, events, score, and presentation.
- Bumped `SIMULATION_RULES_VERSION` to 3 and added `enemy_time` to the version-4 replay state fingerprint. Existing version-4 recordings that declare rules version 2 are rejected with the existing explicit rules mismatch; historical version 1–3 hash algorithms remain unchanged.
- Checks: `cargo check --workspace --bin plouto` passed after moving the new clock into the fingerprint's canonical tuple. No tests or replay runs were performed, and the game was not launched. The prior release artifacts are stale until the next release build; no visual or balance result is claimed.
- Remaining evidence: focused scheduler/Time Slow overlap, forced-grant spacing under slow time, hit-stop boundary, and replay mismatch/round-trip scenarios. C05's source inventory is now complete; scenario verification remains pending.

### Siege Mortar, target feedback, and explosive cadence — 2026-11-16

- Resolved the prior report's open decision about a dedicated Mortar. The Rust arsenal now has a late-game rank-8 Siege Mortar in the post-wave-15 weapon pool. It fires one 32-base-damage shell (37 raw at default player damage), has a 1.45s nominal interval with a 1.30s minimum cooldown, and lasts 5s as a temporary pickup. This gives approximately 3.4 nominal cadence slots; this is not an observed hit-rate or a guarantee that every distant shell lands before pickup expiry.
- The shell locks a valid arena-floor point on fire, clamped to a 200–520-unit requested range and arena boundary, then travels at 260 units/s. Homing and Ricochet do not bend its trajectory. Direct impact damage is applied once; the 168-unit blast gives secondary targets 80% damage with 100%–50% distance falloff. The blast's visual lifetime is 0.24s, and its camera kick is capped at 4.5 to pair broad area with brief, bounded shake.
- Added `mortar_landing_target` as the shared source calculation for combat and the renderer. While aiming, its exact landing point and blast boundary are previewed on the floor. During flight the same marker follows the locked target, displays elapsed flight, and is paired with an elevated shell silhouette and separate ground shadow. The shell arc is visual only; gameplay collision remains on its deterministic floor trajectory.
- Design comparison: Hades combat references describe circular floor attacks as area cues players move out of, while Deep Rock Galactic's Proximity Mine reference describes a floor-projected circle for its trigger/explosion radius ([Hades combat](https://hades.wiki.gg/wiki/Hades:Combat), [Deep Rock Galactic Proximity Mine](https://deeprockgalactic.wiki.gg/wiki/Proximity_Mine)). Applying that pattern here is a design inference: the Mortar preview uses a floor-projected ellipse for the actual blast boundary, and the flight marker stays on the committed landing point rather than relying on a bright shell glow to communicate range.
- Fixed the weapon reticle color lookup to use the projectile type rather than the display name, so Siege Mortar receives its intended orange reticle instead of the generic white fallback. Updated the source-derived eight-weapon ledger, improvement plan, and friend-build instructions. Bumped simulation-rules version from 3 to 4 because the available arsenal and projectile state changed.
- Checks: `cargo check --workspace --bin plouto` passed. `cargo fmt --all -- --check` could not run because rustfmt is not installed in this toolchain. No test suite, game launch, audio work, GPU frame capture, or balance measurement was performed.
- The optimized Rust release build and transactional package validation passed. Both manifests record release 0.1.0 and simulation-rules version 4; the Rust review archive contains 411 content files and all 224 archived Python files. The script verified source/document entries, every manifest SHA-256, identical review executable copies, friend executable identity, and friend-package exclusions. The final ZIPs were rebuilt once more after this report update so the report and plan are included.
- Remaining evidence: rendered aiming and in-flight marker legibility across arena shapes; range clamping at boundaries; exactly-once direct-plus-area retirement; Homing/Ricochet interactions; cadence under stacked fire-rate rewards; and live Mortar balance. No test suite, game launch, audio work, GPU frame capture, or human-play result is claimed.

### Roadmap evidence reconciliation and source provenance — 2026-11-16

- Re-audited the current plan against the source and packaging scripts. Corrected stale statements that described the save-location policy as undecided, packaging as non-transactional, and release manifests as future work. Recorded the implemented contact and temporary-weapon policies while keeping their scenario evidence visibly pending.
- The static obstacle system remains behind a disabled-by-default runtime flag; new runs initialize with an empty obstacle list, preserving legacy replay compatibility without placing obstacles in current arenas.
- Added `sourceRevision` and `sourceDirty` to both package manifests. When Git metadata is available, the build records the current commit and whether local changes were included; the friend packaging helper carries the same fields forward. This workspace is dirty, so the release is explicitly identified as such.
- No gameplay source changed in this pass. No tests or game launch were performed. The release script completed successfully after these document changes. Both manifests record source revision `538f746c73f84e194ea9ab9092b059ee86ed240b`, `sourceDirty: true`, release version 0.1.0 and simulation-rules version 4. The review archive still contains 411 manifest files and all 224 archived Python files; the friend ZIP carries the same provenance and omits the source archive and local saves.

### Power-up rarity and explosive cooldown audit — 2026-11-16

- Compared the Rust power-up definitions with the preserved legacy policy in `archive/python/powerup.py`. Rust had `drone`, `laser`, and `vortex` marked non-rare, while `magnet`, `ricochet`, and `repulsor` were marked rare. Restored the archived set: Ultra, Weapon, Vortex, Laser, Drone, Homing, Time Slow, and Chain are rare; the other pickups are not.
- This classification feeds the existing pickup ring, popup emphasis, off-screen pickup pointer, and pickup-tier event. Correcting it makes rare rewards visible and consistent again, while avoiding rare emphasis on Magnet, Ricochet, and Repulsor. The guide's Core/Tactical/Rare emblem frame remains a separate art category. No sound system or assets were added; the existing rare pickup event follows the corrected legacy classification.
- Cross-checked the 17 gameplay keys against effect dispatch, visual catalog, and color mapping: all 17 are represented in each place, with no missing keys. This is a source consistency review, not a runtime effect test.
- Traced explosive weapon cooldowns: the Rust player arsenal has no weapon with projectile type `bomb`; bomber bombs are enemy projectiles. Player explosive classes use the shared firing scheduler and minimum cooldowns of 0.70s for Heavy Cannon missiles, 0.85s for Flak, and 1.30s for Siege Mortar. The Bomber has a 0.60s windup, a 1.25s fuse, then a 2.8–3.3s reload. These values are source-derived; hit rates and perceived cadence have not been verified in-game.
- Checks: the static parity audit found an exact 8-of-8 match with the archived rare-pickup set; `cargo check --workspace --bin plouto` passed; the optimized release build and transactional package validator passed. The release manifest matches the corrected Rust source and this report, the packaged executable matches the release target, the source archive preserves all 224 Python files, and the friend ZIP carries assets with matching source provenance while excluding development sources.
- No tests or game launch were performed. Current-build pickup appearance, effect behavior in play, and full gameplay scenario review remain pending under the user's no-game-test instruction. No new sound effects or sound systems were added.

### Rank-safe temporary weapon pickups — 2026-11-16

- Source comparison with archived `archive/python/powerup.py` and `weapons.py` found that Rust detected equal/lower-rank weapon drops but still replaced the player's current weapon. This could downgrade the run and discard an already-active temporary weapon; the rank check only changed the existing pickup emphasis.
- Equal/lower-rank Weapon Pods now leave the current weapon and its expiry untouched, then convert into +20 shield. If shield is capped, the pickup restores up to 10 hull; if both are capped, it grants +1 permanent damage. Strictly higher-rank drops retain temporary replacement, base-weapon restoration, and reload-debt preservation.
- Bumped `SIMULATION_RULES_VERSION` from 4 to 5 because pickup outcomes changed. Previous versioned replays therefore receive the existing explicit rules-version rejection rather than silently replaying with altered pickup behavior.
- Updated W03's acceptance and execution ledger. The archived Python tree remains unchanged.
- No tests or game launch were performed. Compile and package results are recorded after rebuilding; focused weapon-pickup scenarios remain unverified under the current instruction.

### Swarm surge communication and scheduler reservation audit — 2026-11-17

- Reconciled the enemy behavior sheets with the current source. E07's three spawn-keyed subgroups and E08's pending-spawn caps were already implemented, but the sheets incorrectly labeled subgroup splitting and hatch accounting as still open. Documented the actual subgroup/lane policy, 16-position hatch search plus bounded fallback, and owner policy: death before an egg's hatch deadline cancels the hatch; once egg or boss children are queued and admitted, they continue independently.
- E07's desired subgroup surge telegraph was missing from the implementation. Added a 0.30s `SurgeTelegraph` state on the enemy clock between Encircle and Surge. During the tell, that subgroup maintains its lane at reduced speed while the other subgroups continue on their staggered cycles. The world renderer reads the same subgroup state and remaining timer to animate the model tint and draw an isometric floor ring with a filling arc. The surge transition therefore uses one simulation clock and one presentation source.
- Rechecked E05 reservations against attack start requests. Charger, Spitter, and Sniper each request weight 2, but the active-weight reconstruction had counted Sniper as weight 1 on following frames. Active Sniper windups now retain weight 2, preventing the scheduler from freeing one commitment slot early.
- Reconciled plan sections 11–12 and the enemy behavior sheets with these implementations and remaining evidence needs. Bumped `SIMULATION_RULES_VERSION` from 5 to 6 for the swarm timing/movement change; replay compatibility rejects older rules versions explicitly.
- Checks: the optimized Rust release build compiled successfully after the pickup, swarm, and scheduler changes. The transactional packaging validator passed for release 0.1.0 / simulation-rules version 6. The full review ZIP contains 416 entries, including all 224 archived Python files and three current-source model sheets; its 414-file manifest hashes the packaged source, documents, and review images. The friend ZIP contains 85 entries, carries the same executable and source provenance, and excludes the Python archive, development reports, review images, and local saves/settings. The current source revision is `538f746c73f84e194ea9ab9092b059ee86ed240b`; `sourceDirty` is true because this workspace contains the ongoing Rust migration and improvements.
- No tests or game launch were performed. Current-build GPU visibility, swarm crowd spacing, squad overlap, and owner-death scenarios remain unverified under the user's no-game-test instruction. These are the remaining evidence gaps for this pass; no sound work was added.

### Current-source 3D model heading and proportion review — 2026-11-17

- Rendered the Rust player model and all 11 regular enemy models directly from the current model functions, at eight headings per model. These CPU geometry renders do not launch the game.
- Reviewed the three generated sheets: the player front opening rotates with the hull and leaves view on rear headings. The sheets also expose the current model proportions and silhouettes across headings.
- Preserved the sheets as `current_source_model_audit_1.png` through `_3.png` in the full Rust review archive. They are evidence about model geometry only; they do not render the game's GPU SDF shader, post-processing, final screen scale, or gameplay animation.
- No tests or game launch were performed. The current-build GPU and in-game visual review remains open under the user's instruction not to test in game.

### Critical comms reveal timing — 2026-11-17

- Source review found that urgent callouts already preempted lower-priority lines but still used the routine type-on animation. This delayed boss, critical-hull, arena-event, and relic information by up to the full character reveal time.
- Urgent comms now draw their complete, wrapped message on the first visible frame in an expanded panel, without the entrance slide or blinking type cursor. Routine wave and pickup guidance retains the type-on animation; reduced-motion mode also shows the complete wrapped text immediately.
- Updated U03's execution ledger. This is a presentation-only change; the deterministic simulation and replay rules version are unchanged.
- No tests or game launch were performed. The optimized Rust rebuild and archive validation are recorded after rebuilding; final GPU layout and visibility review remains pending.

### Headless simulation performance baseline — 2026-11-17

- Added a small release-profile CLI profiler that steps the deterministic simulation without opening the game window. Each scenario runs 240 warm-up steps and 1,800 measured steps at a fixed 1/60-second delta, recording p50/p95/p99/max step duration, peak enemies/projectiles/events, and six state-hash checkpoints.
- Captured authored wave 14 (15 initial enemies) and boss wave 15 (one boss, two peak enemies) plus synthetic mixed-role crowds of 24, 64, and 112 enemies. The stress cases retain high player health and exercise movement, firing, boost, dash, Ultra, and active timed effects.
- Repeated the same profile on Windows 11 Home Single Language, a 12th Gen Intel Core i5-12450H (8 cores/12 logical processors), x86_64, using the optimized release profile. All six checkpoint hashes matched between runs for all five scenarios (30/30), supporting repeatable state progression for these exact scenarios.
- The 112-actor stress case measured 0.7258–0.7332 ms p95, 0.8894–0.9674 ms p99, and 2.7472/2.8290 ms maximum samples. The 64-actor case had the largest one-off sample at 5.790 ms in the first run and 2.159 ms in the repeat. Authored wave and boss p95 results were 0.0184–0.0208 ms and 0.0038–0.0050 ms respectively. At 60 Hz, the simulation-step budget is 16.67 ms; these results do not show a simulation bottleneck worth optimizing, so no spatial index or parallel path was added.
- Raw JSON is preserved in the Rust review archive as `benchmarks/profile_sim_baseline.json` and `benchmarks/profile_sim_repeat.json`; the friend ZIP does not include benchmark data.
- Release packaging rebuilt successfully. The Rust review ZIP has 419 entries and a 417-file manifest, preserves all 224 Python archive files, and includes both raw profile JSONs. The friend ZIP has 85 entries and contains no benchmark or review material. The packaging validator checked the rules-version match, identical per-scenario checkpoint sequences, all archive hashes, executable identity, and friend exclusions.
- Scope limit: this measures CPU simulation-step time only. It does not measure rendering, GPU cost, window scheduling, whole-frame time, target hardware outside this machine, or gameplay correctness/balance. One-step max values may include OS scheduling pauses. No test suite or game launch was performed.
