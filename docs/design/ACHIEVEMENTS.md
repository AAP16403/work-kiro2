# Achievements

Status as of 2026-11-17. Every number and name here comes from the code at:

- `plouto_rs/src/sim/achievements.rs` (definitions, `RunStats`, `AchTotals`, condition checks)
- `plouto_rs/src/save/progress.rs` (settlement, `progress.json`, skin unlocks)
- `plouto_rs/src/app.rs` (when runs settle, live toasts, game-over near-misses)
- `plouto_rs/src/sim/skins.rs` (skins that unlock from achievements)
- `plouto_rs/src/sim/replay.rs` (`SIMULATION_RULES_VERSION`, replay fingerprint)
- `plouto_rs/tests/achievements.rs` (tests)

Human play-testing of the achievement flow has not been done. The test suite is the only check so far.

## Summary

- 35 achievements: 20 original (ids and names are frozen) and 15 added in the wave-9 expansion.
- 5 categories: Combat (7), Survival (10), Bosses (5), Mastery (7), Career (6).
- 1 secret achievement: `clean_sweep`.
- Each achievement is either a **run** condition (judged on one run's stats) or a **lifetime** condition (judged on totals across all saved runs).
- Earned achievements are stored as ids in `progress.json`. They are never removed.

## Achievement table

Thresholds are in the units the condition uses. `survived_s` and `best_combo` are stored internally in thousandths (for example 300000 means 300 seconds, and 6000 means a 6.0x combo). `COMBO_MAX` is 8.0.

"Scope" is `run` (this run's `RunStats`) or `lifetime` (the saved totals, which include the run being judged).

| id | Name | Category | Secret | Condition (exact) | Scope |
|---|---|---|---|---|---|
| first_blood | First Blood | Combat | no | `kills` >= 1 | run |
| massacre | Massacre | Combat | no | `kills` >= 50 | run |
| giant_slayer | Giant Slayer | Bosses | no | `boss_kills` >= 1 | run |
| boss_hunter | Boss Hunter | Bosses | no | `bosses_defeated` >= 3 | lifetime |
| bossbreaker | Bossbreaker | Bosses | no | `bosses_defeated` >= 15 | lifetime |
| no_damage_wave | Untouchable | Survival | no | `perfect_waves` >= 1 | run |
| flawless_five | Flawless Five | Survival | no | `perfect_waves` >= 5 | run |
| elite_slayer | Elite Slayer | Combat | no | `elite_kills` >= 5 | run |
| combo_6x | Combo x6 | Combat | no | `best_combo` >= 6.0 (stored 6000) | run |
| combo_max | Maxed Out | Combat | no | `best_combo` >= 8.0 (stored 8000, from `COMBO_MAX`) | run |
| survive_ten_waves | Survivor | Survival | no | `waves_cleared` >= 10 | run |
| into_the_deep | Into the Deep | Survival | no | `wave` >= 10 | run |
| deep_space | Deep Space | Survival | no | `wave` >= 20 | run |
| edge_of_stars | Edge of the Stars | Survival | no | `wave` >= 30 | run |
| marathon | Marathon | Survival | no | `survived_s` >= 300 s (stored 300000) | run |
| five_digits | Five Digits | Mastery | no | `score` >= 10000 | run |
| stellar_score | Stellar Score | Mastery | no | `score` >= 50000 | run |
| centurion | Centurion | Career | no | `total_kills` >= 100 | lifetime |
| exterminator | Exterminator | Career | no | `total_kills` >= 1000 | lifetime |
| veteran | Veteran | Career | no | `runs_played` >= 10 | lifetime |
| dash_master | Dash Master | Mastery | no | `dashes` >= 100 | run |
| overdrive | Overdrive | Combat | no | `ultra_uses` >= 5 | run |
| overkill | Overkill | Combat | no | `ultra_kills` >= 25 | run |
| scavenger | Scavenger | Mastery | no | `pickups` >= 25 | run |
| shield_wall | Shield Wall | Survival | no | `shield_blocks` >= 10 | run |
| triple_threat | Triple Threat | Bosses | no | `boss_kills` >= 3 | run |
| every_boss | Boss Collector | Bosses | no | number of distinct boss kinds killed, across all runs, >= 8 (length of `BOSS_KINDS`) | lifetime |
| world_tour | World Tour | Mastery | no | number of distinct arena shapes with a cleared wave, across all runs, >= 4 (length of `ARENA_SHAPES`) | lifetime |
| daily_driver | Daily Driver | Career | no | `daily_runs` >= 1 | lifetime |
| mutant | Mutant | Mastery | no | wave reached >= 10 **and** at least one mutator active (`wave_mutated`) | run |
| purist | Purist | Mastery | no | wave reached >= 15 **and** zero ultras fired this run (`wave_no_ultra`) | run, can regress |
| endurance | Endurance | Survival | no | `survived_s` >= 600 s (stored 600000) | run |
| five_thousand | Five Thousand | Career | no | `total_kills` >= 5000 | lifetime |
| old_hand | Old Hand | Career | no | `runs_played` >= 50 | lifetime |
| clean_sweep | Clean Sweep | Survival | **yes** | `perfect_waves` >= 10 | run |

Notes on specific rows:

- `wave_mutated` is the run's `wave` when `mutator_count > 0`, otherwise 0. `wave_no_ultra` is the run's `wave` when `ultra_uses == 0`, otherwise 0.
- `world_tour` and `every_boss` count distinct entries. Unknown names are ignored when recorded and dropped on load.
- `daily_driver` counts any settled daily run, whatever its score.
- `Untouchable` and `Flawless Five` use `perfect_waves`. A wave is perfect when no health-damage hit happened since the previous wave clear. The first wave counts when the run has had no health hit at all. Shield-only blocks do not break the streak.

### Secret rows

`clean_sweep` is the only secret row. Until it is earned, the UI shows the name "???" and the text "Secret achievement. Keep playing to find out how." (`shown_name` and `shown_description`). The game-over near-miss lines never show secret achievements.

## Stat sources (where each counter is incremented)

`RunStats` is updated only through its `on_*` methods. The call sites listed here are from the code at the time of writing. Line numbers may drift.

| Stat | Set by | Call site |
|---|---|---|
| `kills`, `elite_kills`, `boss_kills`, `best_combo` | `on_kill` | `sim/step.rs` `kill_enemy_inner` when `credit` is true |
| `boss_kinds` | `on_boss_kind` | same site, for behaviors starting with `boss_` |
| `ultra_kills` | `on_ultra_kill` | `sim/step.rs` (ultra kill path), alongside `on_kill` |
| `ultra_uses` | `on_ultra_use` | `sim/step.rs` ultra activation |
| `dashes` | `on_dash` | `sim/step.rs` `trigger_dash` |
| `hits_taken`, `damage_taken` | `on_player_hit` | `sim/step.rs` where `health_damage > 0` |
| `shield_blocks` | `on_shield_block` | `sim/step.rs` where `shield_damage > 0` and `health_damage == 0` |
| `pickups` | `on_pickup` | `sim/step.rs` pickup apply |
| `waves_cleared`, `perfect_waves`, `arenas_cleared` | `on_wave_clear`, `on_arena_clear` | `sim/step.rs` wave-clear block, only if `hp > 0` on that step |
| `mutator_count`, `daily` | `set_run_context` | `app.rs` at settlement (from `RunContext`, see below) |
| `wave`, `score`, `survived_s` | `finish` | `app.rs` `settle_run` |

Rules built into the hooks:

- A contact suicide (an enemy that destroys itself on the player) scores normally but is **not** credited (`kill_enemy_uncredited`). It does not count as a kill.
- A wave cleared on the same step the player dies is **not** credited. The wave-clear credit runs only when `hp > 0`.
- `on_player_hit` ignores zero or negative amounts.

## When achievements are evaluated

There are two paths.

### 1. Mid-run live checks (toasts only, nothing saved)

- `check_live_unlocks` in `app.rs` runs while the game is in the Playing screen. It runs every 0.5 s (`LIVE_CHECK_S`) and also whenever the wave number changes.
- It builds a copy of the live `RunStats` with `wave`, `score`, `survived_s` and `best_combo` filled from the sim, then calls `evaluate_live`.
- `evaluate_live` skips achievements already in `progress.json`, and skips any condition where `can_regress` is true. Today that is only `wave_no_ultra` (Purist). So Purist is never toasted mid-run.
- Each id is toasted once per run (`live_toasted`). Live checks are read-only and write nothing.
- A live toast is shown as "Achievement Unlocked". Live checks never grant skins.
- Live checks are off when the run is recorded with `--record`.

### 2. Settlement (the real grant)

`settle_run` in `app.rs` runs once per run. It does, in order:

1. Calls `RunStats::finish` with the final score, wave, survival time and best combo.
2. Submits the score to the high-score table.
3. Calls `end_run` (see below) unless the run is a `--record` run.
4. If saved, queues a toast for each new achievement. Ids already toasted live are not toasted again. Queues a "Skin Unlocked" toast for each new skin.
5. Builds the game-over data: unlocked names and up to two near-miss lines.

`end_run` in `progress.rs`:

1. If `progress.json` exists but cannot be opened, it writes nothing, returns `saved = false`, and the UI shows "Progress Not Saved". This prevents overwriting a file that could not be read.
2. Copies the run and applies the context from `RunContext` (see below).
3. Loads `progress.json`, calls `apply_run` (merges the run into lifetime totals with `AchTotals::absorb`), then `evaluate_achievements`, then `refresh_skin_unlocks`.
4. For a valid daily date, records the daily result (kept only if it is the first result for that date or the score is strictly higher).
5. Saves the file atomically.

`evaluate_achievements` checks every definition not yet in `data.achievements`. It appends new ids in `ACHIEVEMENTS` order, so two achievements unlocked by the same run are stored in definition order.

### Non-regressing rule

- An id, once in `progress.json`, is never removed. The loop skips earned ids.
- A condition that can become false again later in the same run (`can_regress`) is only checked at settlement. Purist is the only one. Its settlement check uses the full run: wave reached >= 15 and no ultra fired in the whole run.
- Lifetime totals only grow, because `absorb` only adds or takes a max.

## What counts as a run

A run starts in `start_run`. A run settles exactly once (`game_over_settled`). It settles in one of three ways:

| Ending | Code path | Settles? | Game-over screen? |
|---|---|---|---|
| Death | sim sets `game_over`, `settle_game_over` | yes | yes |
| Pause menu, quit to menu | `quit_run_to_menu` calls `abandon_run` | yes | no |
| Window close | `WindowEvent::CloseRequested` calls `abandon_run` | yes | no |

`abandon_run` calls `settle_run`, which has no minimum run length. A run quit a moment after it starts still counts: it adds 1 to `runs_played`, can add to `total_kills`, and is evaluated for achievements.

Other rules:

- **Replay (`--replay <file>`)**: never grants achievements. `main.rs` calls `replay_and_verify`, which does not read or write `progress.json`.
- **Record (`--record <file>`)**: the run is written as a recording, and the progress write is skipped (`skip_progress`). Live toasts are off and settlement grants nothing and shows no unlocks.
- **Daily run**: `daily_date` is set from the run. A valid date sets `daily = true` on the run copy, so it counts toward `daily_runs`. An invalid date is treated as a normal run. Every settled daily run counts as a run in `runs_played` as well. Retries count.
- **Mutators**: the number of mutators active (from `RunContext.mutators`) becomes `mutator_count` on the run copy. This is set at settlement, not by the sim. Achievements read it only through `wave_mutated`.

`RunContext` is passed to both `end_run` and `evaluate_live`. Its fields are `daily_date` and `mutators`. `prepared_run` applies them to a copy of `RunStats`. The caller's `RunStats` is not changed, as `progress.rs` states, so the replay fingerprint is not affected by settlement.

## Skins unlocked by achievements

Three skins in `sim/skins.rs` use `UnlockRule::Achievement`. They unlock when `end_run` runs `refresh_skin_unlocks` after an achievement is earned at settlement. They do not unlock from a live toast.

| Skin id | Name | Unlocked by |
|---|---|---|
| void | Void Pod | `combo_6x` (Combo x6) |
| neon | Neon Pod | `elite_slayer` (Elite Slayer) |
| ghost | Ghost Pod | `no_damage_wave` (Untouchable) |

Other skins unlock from score, wave, boss count or kill count. For those, see `SKINS` in `sim/skins.rs`. Skin unlocks are stored in `unlocked_skins`.

## progress.json

The file is `progress.json`, located with `resolve_data_file`. The `PLOUTO_DATA_DIR` environment variable overrides the folder. The version key is `version`, currently `PROGRESS_VERSION = 1`.

Fields used by achievements and skins:

| Key | Type | Meaning |
|---|---|---|
| `version` | integer | File format version (1). |
| `best_wave` | integer | Highest `wave` over all settled runs. |
| `best_score` | integer | Highest `score` over all settled runs. |
| `total_kills` | integer | Sum of `kills` over all settled runs. |
| `bosses_defeated` | integer | Sum of `boss_kills` over all settled runs. |
| `runs_played` | integer | Number of settled runs. |
| `daily_runs` | integer | Number of settled daily runs. |
| `bosses_seen` | array of strings | Distinct boss kinds killed (subset of `BOSS_KINDS`). Unknown names dropped on load. |
| `arenas_cleared` | array of strings | Distinct arena shapes with a cleared wave (subset of `ARENA_SHAPES`). Unknown names dropped on load. |
| `achievements` | array of strings | Earned achievement ids, in unlock order. No timestamps are stored. |
| `unlocked_skins` | array of strings | Unlocked skin ids. |
| `selected_skin` | string | Currently selected skin id. |
| `daily` | object | Per-date best result: `"YYYY-MM-DD": { "score": n, "wave": n }`. |

Other behaviour:

- Keys this version does not know are kept in `extra` and written back, so newer files are not stripped.
- Corrupt JSON is moved aside (quarantined) by the shared save code before defaults are used.
- Non-negative integers are enforced on load (negative values fall back to 0).
- Duplicate ids in `achievements` are removed on load. Non-string entries are ignored.
- Achievement progress bars are not stored. They are computed from `RunStats` and the totals.

## Open policy questions

These are not decided. The code does what is described, and the owner should decide whether to change it.

1. **Quit and abandon runs count.** A run quit from the pause menu, or ended by closing the window, counts as a settled run. That adds to `runs_played`, `total_kills`, and the lifetime totals. Veteran (10 runs) and Old Hand (50 runs) can be reached by starting and quitting runs. There is no minimum run length.
2. **Daily retries count as runs.** Every settled daily run adds to `runs_played` and `daily_runs`. Daily Driver is satisfied by any one settled daily run, whatever its score.
3. **Live toast versus settlement.** A toast can appear mid-run for an achievement the run would not keep if it changed later. Only Purist is excluded from live toasts, but other conditions cannot regress today, so this is safe for them.
4. **Game-over list.** The near-miss lines list only two locked, non-secret achievements, ranked by progress ratio. Ties are not defined beyond the sort order.

## How to add an achievement safely

1. **Do not change existing ids or names.** Saved `progress.json` files store ids. `LEGACY_ACHIEVEMENT_IDS` must stay at 20 entries and must not be edited. Tests `ids_are_unique_complete_and_named` and `legacy_ids_and_names_are_unchanged` check this.
2. **Use an existing stat key if one fits.** Keys are listed in `run_value`, `run_float` and `total_value` in `achievements.rs`. An unknown key never unlocks (no panic), and `every_key_is_known` in the module tests fails if one is used.
3. **New per-run stat:**
   - Add the field to `RunStats` and its initializer in `RunStats::new`.
   - Add the hook method and call it from the sim at the right point.
   - Add the key to `run_value` or `run_float`.
   - **Bump `SIMULATION_RULES_VERSION`** in `sim/replay.rs` (now 7). The module says any `RunStats` field change requires this. `RunStats` is part of the replay fingerprint. Recordings with a different rules version are rejected.
   - If the stat can drop during a run, add the condition to `can_regress`, so it is only checked at settlement.
4. **New lifetime stat:**
   - Add it to `AchTotals`, `ProgressData`, `default_progress`, `from_json_map`, `to_json_map`, `totals_of`, and `AchTotals::absorb`.
   - Add the key to `KNOWN_KEYS` in `progress.rs`, so it is not also kept in `extra`.
   - Add the key to `total_value`.
5. **Add the definition** to `ACHIEVEMENTS`, with a unique id, name, description, condition, category and secret flag. Append it after the last entry. Optionally add a skin with `UnlockRule::Achievement(id)`.
6. **Update the tests in `plouto_rs/tests/achievements.rs`:**
   - `ids_are_unique_complete_and_named` asserts `ACHIEVEMENTS.len() == 35`. Update the number.
   - `CASES` (threshold table) must have one entry per achievement, with the exact target. `threshold_table_covers_every_achievement_with_matching_targets` checks this.
   - `each_condition_unlocks_at_threshold_and_not_below` checks each `CASES` entry at target and at target minus one.
   - Add a test for the new stat's hook if one is new (see `tracking_fields_follow_their_hooks`).
7. **Run the tests:** `cargo test -p plouto_rs`. The verified facts for this task record 88 passing tests (17 lib, 23 in `tests/achievements.rs`, 28 in `tests/render_and_ui.rs`, 20 in `tests/sim_and_save.rs`). This document was written without running the suite.

## Tests in tests/achievements.rs

There are 23 `#[test]` functions. They cover: id uniqueness and the 35-count, legacy ids and names, category coverage, threshold table, unlock at and below threshold, unknown keys, secret text hiding, the Untouchable streak (health hit breaks it, shield block does not) in the sim, zero or negative damage, tracking fields and their hooks, unknown boss and arena names, read-only `evaluate_live`, mutator and daily context, legacy `progress.json` load and round trip, dropping unknown names on load, settlement writing once, repeated settlement not re-announcing, daily result saved in the same write, invalid daily dates, Mutant from context, totals matching `apply_run` and `absorb`, and the boss kind list covering every boss name.
