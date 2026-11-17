# PLOUTO — Enemy, Elite, Aura & Boss Overhaul Report

**Date:** 2026-11-17  
**Scope:** `plouto_rs/src/sim/`, `plouto_rs/src/render/`, `plouto_rs/src/ui/screens.rs`, and `plouto_rs/tests/`  
**Original pass:** `SIMULATION_RULES_VERSION` bumped `8` → `10` (`src/sim/replay.rs`). This report's original implementation/check results are historical; current source uses rules version 13.

---

## 1. Original Audit Findings (Root Causes Found)

### A. Auras, Circles & Visual Indicators That Did Nothing or Misled
1. **Tank (`push_t` / `brace_t` & unwarned Death Blast):**
   - `models3d/mod.rs` drew a bright pulsing orange ring + vents on `push_t > 0.0` (and `world.rs` 2D fallback drew a permanent green ring on `brace_t.is_some()`), while `steer_formation_batch` overwrote Tank's velocity every tick and `push_t` conferred no armor, attack benefit, or AoE.
   - Tank's cannon telegraph beam (`220` units) was less than half the bullet range (`185 × 2.8 = 518` units), damage (`12`) did not scale with wave, and `tank_death_blast` (`70`-unit `15`-dmg explosion) triggered on only 3/12 kill paths with zero ground warning ring and no Field Guide entry.
2. **Engineer:**
   - Drew a permanent spinning green "repair" arc (`models3d/mod.rs`, `world.rs`) despite having zero repair/support mechanics in simulation.
   - Clamped mine coordinates with a circular check (`p.length() <= room_radius * 0.86`), allowing mines to spawn inside the Donut pit or outside Cross/Diamond arms; mines could stack on the exact same pixel; no tether connected Engineer to `EngineerWindup` drop sites; `AttackScheduler::request` was called before checking `MAX_ACTIVE_CONSTRUCTIONS`, wasting slots when capped.
3. **Elite Affixes (`mender`, `reflector`, `volatile`, `shielded`, `warden`, `splitter`):**
   - **Mender:** Flat `8 HP / 2.8s` single-target heal was negligible late-game, had no `165`-unit range ring, no heal tether beam, and no `+HP` popup.
   - **Reflector:** Shield arcs spun identically during its `3.0s` cooldown; instant un-telegraphed reflection dealt uncapped player damage back (capable of one-shotting the player on Railgun/Heavy Cannon crits), spawned an untagged orb, and wasted cooldown on Critical Shards.
   - **Volatile:** Body-hugging ring (`r_vis + 6.5`) hid the actual `130`-unit death blast radius.
   - **Shielded:** Affix ring + 4 orbital dots persisted permanently after `e.shield <= 0`.
   - **Warden:** Emitted `SimEvent::ShieldHit` splash rings on non-shielded allies (`absorbed > 0`), and drew its `170`-unit aura around elevated `cy` instead of ground level `sy - 6.0`.
   - **Splitter:** Children spawned at `e.pos + offset` without `clamp_entity_to_map`.
4. **Bomber & Boss Floor Traps:**
   - Bomber's `72`-unit ground blast ring disappeared for the first `0.73s` of its `1.25s` flight (`p.ttl <= 0.52` gate), and mid-air player contact detonated bombs early.
   - Gorgon Juggernaut's `slam_warn` (`ttl = 1.1`) lingered after `slam` armed (`0.62s`); Origin Nexus's `womb_warn` (`ttl = 1.0`) outlived `womb_pulse` (`ttl = 0.9`), and `"womb_pulse"` fell into the `_ =>` orange cross-mine renderer fallback.

### B. Systemic AI, Steering & Scheduler Bugs
1. **Two Fighting Movement Controllers:** `behaviors.rs` integrated `enemy.pos += vel * dt`, and `steer_formation_batch` (`steer.rs`) immediately overwrote `vel` and `pos`—erasing `0.16s` projectile dodges, Tank speeds/stops, and role distance bands.
2. **Reversed Formation Axis (`F1`):** `front_dir = player_pos - center` placed `front_heavy`/`front_dive`/`front` (Tank, Charger, Chaser) *behind* the player and `backline`/`support` (Ranged, Spitter, Engineer) *between* the player and crowd; single members sat at `-0.5 * arc`; dead slots never compacted.
3. **Dash-Baited Prediction:** Raw 1-step `player_vel` caused dashes to fling enemy aim and formation anchors into empty space/walls.
4. **`AttackScheduler` Deadlock:** `weight = 2` (`Charger`, `Spitter`, `Sniper`) against `capacity = 1` (`live_non_boss < 5` or boss alive) failed `within_budget` on every tick, stalling every attack for `1.6s`; `Flyer` polled only once per `0.10s` (~`10s` forced-grant delay).

### C. Individual Regular & Boss Bugs
- **Regulars:** Chaser lunge drifted with `sep * 0.3` and mismatched random `lunge_t` vs fixed beam reach; Ranged shot #2 fired untelegraphed from `None`; Sniper fired off-screen (`< 740`) and tracked dashes; Charger left `charge_dir` stale during `ChargerWindup` (wrong 3D facing) and used unclamped aim targets (grinding walls for `1.15s`); Spitter drew 1 center beam for 3/4-lane fans and lacked wave scaling; Flyer dashed straight at stale `player_pos` and orbited only counter-clockwise; Swarmer `Surge` stayed orbiting at `72–116` units and ignored inter-subgroup separation; Egg Sac hardcoded `/ 4.0` hatch progress (breaking `3.0s` sacs) and spawned unscaled Swarmers.
- **Bosses:** All 8 bosses never set `enemy.vel` (breaking facing & speed-driven 3D animations in `thunder.rs` / `laser.rs` / `eclipse.rs`); boss-summoned adds skipped difficulty/mutators/`spawn_attack_cd_range`; Storm Sovereign streaked across the screen on teleport (`prev_pos` not reset); Prisma Overlord's `0.13s` discrete beams lagged `0.30s` behind its `0.15–0.22s` sweep tick with gaps + had a random `1%` untelegraphed Phase 2 ring; Forge Warden didn't telegraph Phase 2 `perp` fans and silently dropped spikes at cap `14`; Brood Matriarch fell back to an untelegraphed volley if cap filled mid-windup; Ocular Abyss fired untelegraphed Phase 1/2 `fire_ring`s; Origin Nexus fired its entire projectile salvo on frame-0 of `WombPulseTelegraph`; Eclipse Archon never rotated its `safe_angle` across bursts despite code comments and Field Guide text, and its safe-sector rails sat in dead 2D fallback code.

---

## 2. Implemented Fixes (3-Task Overhaul)

### Task 1 — Core AI Architecture, Perception, Locomotion, Formation v2 & AttackDirector
- [`src/sim/enemy.rs`](file:///d:/work%20kiro2/plouto_rs/src/sim/enemy.rs): Added typed `EnemyRole`, `AttackPhase` (`Idle`, `Windup { frac }`, `Active`, `Recover`), `Enemy::attack_phase`, and deterministic `EnemyAi` locomotion/perception/director fields.
- [`src/sim/perception.rs`](file:///d:/work%20kiro2/plouto_rs/src/sim/perception.rs): Added `Perception`, `PerceptionMemory`, `WorldRect`, exponential `smoothed_vel` (freezing across dashes & boss knockback), `intent_vel` from `SimInput.move_dir`, `breathing_room_left` (`0.60s` on hull loss), and deterministic camera `on_screen_rect`.
- [`src/sim/ai_skill.rs`](file:///d:/work%20kiro2/plouto_rs/src/sim/ai_skill.rs): Added `ai_skill(difficulty, wave)` (`Easy`/`Normal`/`Hard` linear ramps across waves `1..=20` for reaction delay, lead quality, dodge chance/reaction, i-frame respect, aim jitter, coordination, axis turn rate, and weave).
- [`src/sim/director.rs`](file:///d:/work%20kiro2/plouto_rs/src/sim/director.rs): Implemented deterministic two-pass `AttackDirector` + `AttackDirectorState` (`[f32; 12]` by role index), `(score desc, spawn_index asc, enemy_id asc)` ranking, `{2, 4, 6}` base budget (eliminating the `weight=2` vs `capacity=1` deadlock), post-hit breathing room, on-screen gating, and same-tick `commit_granted_attacks`.
- [`src/sim/steer.rs`](file:///d:/work%20kiro2/plouto_rs/src/sim/steer.rs): Implemented Formation v2 (`FormationState { axis, anchor }`), fixed `axis` orientation (`weighted_centroid - player_pos`), 15° axis hysteresis + turn cap, anchor speed cap, `k`-scaled role rings, centered compact slots `(i + 0.5)/n - 0.5`, crossing-free angle-matched assignment, and 6° arena-aware angle sliding.
- [`src/sim/locomotion.rs`](file:///d:/work%20kiro2/plouto_rs/src/sim/locomotion.rs): Implemented `MoveIntent` / `IntentKind`, per-role `Kinematics`, Donut hole & Cross corner `route_point`, deterministic 64-unit `SpatialGrid` (zero `HashMap`), predictive neighbor avoidance (`t* < 0.5s`), Arrive curve, turn/accel limits, single position integration (`integrate_batch`), and mass-weighted `resolve_enemy_body_overlaps`.
- [`src/sim/behaviors.rs`](file:///d:/work%20kiro2/plouto_rs/src/sim/behaviors.rs): Added exact quadratic intercept `predict_target` with reaction delay and jitter, reaction/chance/edge-safe `dodge_player_projectiles` (Donut pit + Cross/Diamond clamp-safe, dodge prioritized over strafe), and refactored all 11 regular `update_*` functions to return `MoveIntent` without direct `enemy.pos` writes.
- [`tests/ai_core.rs`](file:///d:/work%20kiro2/plouto_rs/tests/ai_core.rs): Added 10 integration tests verifying dodge retention, straight lunge, dash-spike immunity, i-frame hold, edge-safe dodge, order-independent & deadlock-free director, reversed-axis fix, Donut routing, mass-weighted push ratio, and Easy vs Hard skill/determinism.

### Task 2 — All 11 Regular Enemies, 7 Elite Affixes & Visual/Mechanical Aura Parity
- **Tank:** `push_t > 0.0` now grants `0.65×` Armored Surge damage reduction + amber hit sparks (`step.rs`) and trims `attack_cd` (`behaviors.rs`); 2D ring matches `push_t > 0.0`; telegraph beam matches full `518.0` range; cannon damage scales `(12 + wave / 3).min(24)`; `tank_death_blast` consolidated inside `kill_enemy_inner` for all kill paths with unconditional `Shockwave` + `<= 40%` HP ground warning ring (`world.rs`).
- **Engineer:** Added genuine `tick_engineer_support` periodic Shield Reinforce Pulse (`+8` shield every `3.6s` within `165.0` units, capped at `25% max_hp`, with `TetherBeam` + popup); hid permanent idle green arc so it glows only on `support_pulse > 0.0`; added `EngineerWindup` fabricator tether beam to mine drop point; fixed `clamp_entity_to_map` and `>= 70.0`-unit mine spacing before `director.propose`.
- **Elite Affixes:**
  - `Mender`: `2.0s` interval, heals up to 2 lowest-HP% allies for `8 + round(0.12 * max_hp)`, emits `+HP` popup + `TetherBeam`, renders `165`-unit ground ring.
  - `Reflector`: Ignores Critical Shards, caps reflected damage `6..=(18 + wave/2)`, adds `PendingReflect` (`0.16s` telegraph beam + `.with_source("reflector")`), hides bright arcs on cooldown with a dim recharge arc, adds `"reflector"` shot visual.
  - `Volatile`: Renders true `130`-unit ground ring (intensifying `< 40%` HP) and emits `130`-unit death `Shockwave`.
  - `Shielded`: Hides active shield ring & dots when `e.shield <= 0`.
  - `Warden`: Emits `SimEvent::WardAbsorb` steel-blue sparks instead of `ShieldHit` splash rings; `170`-unit ring rendered on ground plane.
  - `Splitter`: Clamps child spawn positions to map.
- **Regular Role Polish:** Chaser straight lunge + exact beam reach + aim-flip; Ranged telegraphed `0.20s` shot #2 + lateral cutoff strafing; Sniper viewport-gated firing + dash-immune lock + magenta lock tint/offscreen chevron; Bomber continuous `72`-unit ground blast ring across full `1.25s` parabolic arc (no mid-air player detonation) + dodge; Charger `120`-unit clear-path check + clamped aim + live windup `charge_dir`; Spitter 3/4-lane telegraph rails + wave damage scaling; Flyer perpendicular path-intercept dash + alternating `det_sign` orbit; Swarmer true inward `Surge` dive (`ring_r = 14`) + cross-subgroup separation; Egg Sac `max_hatch_timer` visual normalization + wave/difficulty/Frenzy-scaled hatched Swarmers.
- [`tests/enemies_and_elites.rs`](file:///d:/work%20kiro2/plouto_rs/tests/enemies_and_elites.rs): Added 12 regression tests covering Tank, Engineer, Mender, Reflector, Shielded, Volatile, Warden, Splitter, Bomber, Charger, Ranged, Spitter, Sniper, Swarmer, and Egg Sac.

### Task 3 — All 8 Bosses, Telegraphs, Replay & Field Guide Sync
- **Shared Boss Fixes:** All 8 bosses now populate `enemy.vel` accurately (`bosses.rs`) and Storm Sovereign's `CRUISE_SPEED` scales to `(e.speed * 0.4).max(1.0)` (`thunder.rs`); `boss_laser` and `boss_abyss_gaze` orient toward `charge_dir` during telegraphs (`world.rs`); `make_summoned_enemy` (`level.rs`) + `enemy_speed_mult` (`step.rs`) apply difficulty, profiles, Frenzy speed, and `spawn_attack_cd_range` to all boss-summoned adds.
- **Individual Boss Fixes:**
  - **Storm Sovereign:** Resets `prev_pos = pos` on teleport + emits `SimEvent::BossTeleport` dissolve/arrival FX and teleport rings.
  - **Prisma Overlord:** Continuous sweeping `LaserBeam`s (`warn = 0.0, ttl = 0.08`, periodic `hit_done` reset, cleared in `cancel_attack_for_interrupt`), translucent `LaserCharge` sweep sector, removed random `1%` untelegraphed Phase 2 ring.
  - **Forge Warden:** Telegraphs Phase 2 `perp(aim)` spread rails; prunes oldest `"spike"`/`"mine"` traps to guarantee `summon_target_count` spikes deploy.
  - **Brood Matriarch:** Transitions to telegraphed `QueenVolleyTelegraph` instead of firing untelegraphed fallback volleys when cap fills; reserves `summon_target_count` slots against mid-windup `egg_sac` hatches.
  - **Gorgon Juggernaut:** `slam_warn` `ttl = 0.62` expires when `slam` arms (`render/world.rs` hides `"slam"` pre-arm / `"slam_warn"` post-arm).
  - **Ocular Abyss:** Locks Phase 1/2 `fire_ring` angle into `sniper_aim` and renders 8 radial spoke cues during `AbyssTelegraph`.
  - **Origin Nexus:** Separates `womb_warn` (`ttl = 0.52`) / `womb_pulse` (`ttl = 0.9, armed_delay = 0.52`, dedicated violet renderer) from projectile salvo/add spawns until `WombPulseTelegraph` finishes; renders locked fan & ring telegraph rails.
  - **Eclipse Archon:** Exports & uses `eclipse_safe_angle(enemy, volley)` (`±0.34 rad` P1, `±0.38 rad` P2) so the safe wedge genuinely rotates between bursts; moves full-arena safe-sector rails & wedge above `draw_boss_model` for both `EclipseCharge` and `EclipseBurst` and aligns 3D facing.
  - **Task 3 QA (`qa_reviewer` Subagent 3C) Additional Fixes:**
    - `boss_brute` wall-impact deadlock (`src/sim/bosses.rs`): updated `brute_charge_lane` and `BruteCharge` wall-impact checks to use `clamp_entity_to_map(pos, room_radius, enemy.radius + 6.0, map_type)` instead of `room_radius * 0.96` (which `step.rs` prevented reaching when `room_radius < 900`).
    - `boss_laser` double `sub_timer` decrement (`src/sim/bosses.rs`): removed duplicate decrement in `LaserWingWindup` so windup lasts the full `0.46s` matching `src/render/world.rs`.
    - `boss_thunder` teleport wall padding (`src/sim/bosses.rs`): changed `ThunderTeleportOut` clamping pad from `24.0` to `enemy.radius + 6.0` (`36.0`) to match `step.rs`.
    - `boss_trapmaster` `summon_target_count` (`src/sim/bosses.rs`, `src/render/world.rs`): capped `summon_target_count` by `MAX_ACTIVE_CONSTRUCTIONS.saturating_sub(non_prunable)` and used it directly without fallback.
- **Replay & Guide:** `SIMULATION_RULES_VERSION = 10` (`src/sim/replay.rs`); Field Guide updated for `tank`, `engineer`, `reflector`, `mender`, and `boss_laser` (`src/ui/screens.rs`).

---

## 3. Verification at the Time of the Original Pass
- **Cargo Check:** `cargo check -p plouto_rs --all-targets` passed with **0 errors, 0 warnings**.
- **Full Test Suite:** `cargo test -p plouto_rs --no-fail-fast` passed **132 / 132** tests (**0 failed, 0 ignored**):
  - `28` unit tests (`plouto_rs` lib)
  - `23` `achievements`
  - `10` `ai_core` (Task 1 integration tests)
  - `11` `bosses_and_parity` (Task 3 boss/parity regression tests)
  - `12` `enemies_and_elites` (Task 2 regression tests)
  - `28` `render_and_ui`
  - `20` `sim_and_save`
- **Performance Benchmark (`cargo run --release -p plouto_rs --example profile_sim`):** Verified cleanly after all edits (`synthetic-mixed-roles-24-actors`: `148.4 us` median; `64-actors`: `348.8 us` median; `112-actors`: `555.8 us` median; `authored-wave-14-normal`: `17.0 us` median; `authored-wave-15-boss`: `6.6 us` median).
- **Android layout follow-up:** The current project hypothesis is [`ANDROID_LAYOUT_HYPOTHESIS.md`](../design/ANDROID_LAYOUT_HYPOTHESIS.md). It distinguishes existing input/HUD behavior from proposed touch controls; Android touch input and device checks remain unimplemented.

## 4. Follow-Up Boss and Gameplay Verification — 2026-11-17

- Current full headless suite: **155 passed, 1 graphics-adapter test ignored**. No game window was launched.
- Added `plouto_rs/tests/boss_phase_transition_contract.rs`: every boss is stepped through a phase-I to phase-II transition; it checks cancellation of unlaunched tells/projectiles, Laser beam cleanup, and the committed Origin Nexus pulse-warning/damage pairing. The focused test passes.
- Source review of all eight boss routines found no reproduced tell/attack geometry or phase-cleanup defect. Already-committed hazards retain their matching warning; death cleanup removes boss-owned hazards.
- Wave 5 and Wave 10 HP are doubled, and Ultra's three variants now combine broader fan coverage with a 220-unit pulse. The profile details and version/loadout confounds are recorded in [`GAME_IMPROVEMENT_REPORT.md`](GAME_IMPROVEMENT_REPORT.md); the rules-11 versus rules-12 comparison is not an isolated HP experiment.
- No new gameplay sectors or sound work were added. The existing open-arena and visual-only sector-signature policy remains.
