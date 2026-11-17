# PLOUTO — Enemy AI Improvement Plan (agent work order)

**Written:** 2026-11-17. **Audience:** implementation agents. **Scope:** the 11 regular enemy roles and the shared AI framework. Bosses come in only where they share that framework (section 8).

This began as an implementation work order. The problem statements below describe the pre-overhaul source and are historical evidence, not claims about today's tree. Check the source-status reconciliation in section 1 before selecting follow-up work; source takes precedence over stale line references.

---

## 0. Rules every agent follows

1. **Determinism is non-negotiable.** AI may only read simulation state and `ctx.rng` (`SimRng`). Never use wall-clock time, thread scheduling, `HashMap` iteration order, or float ordering that depends on parallel reduction order. `steer_formation_batch` runs under rayon above `PARALLEL_MIN_ENEMIES`. Any new parallel pass must compute per-enemy results independently and apply them in index order, the way that function already does.
2. **Clocks.** Enemy decisions, warnings, recoveries, cooldowns and enemy-owned projectile lifetimes advance on `enemy_dt` / `ctx.enemy_time`, which Time Slow scales. They never use `state.time` deltas. See `docs/design/SIMULATION_CLOCKS.md`.
3. **Replay version.** Any change that alters simulation output (new `EnemyAi` fields, new decisions, changed numbers) must bump `SIMULATION_RULES_VERSION` in `plouto_rs/src/sim/replay.rs` by exactly one, once per merged work package. Do it in the same change and say so in your report.
4. **Telegraph contract.** Every damaging regular attack keeps a visible warning that starts on commit, is removed on launch or interrupt, and points at the exact committed target. `cancel_attack_for_interrupt` (behaviors.rs) is the single cleanup path; new attack states must be handled there.
5. **No new blocking obstacles, no sound work, no new enemy roles** (this plan improves the existing 11). Don't launch the game window. Headless `cargo test -p plouto_rs` and `cargo run --release --example profile_sim` are allowed.
6. **Own only your files.** Each work package lists them. If you need a change elsewhere, write it in your report instead of making it.
7. **No panics** in sim code. No `unwrap`/`expect` on runtime data.

---

## 1. Current architecture (reconciled 2026-11-17)

| Piece | Where | What it does |
| --- | --- | --- |
| Enemy data | `sim/enemy.rs` `Enemy`, `EnemyRole`, `EnemyAi`, `EnemySubState` | `Enemy.role` is a typed enum used by regular AI dispatch; `behavior: String` remains the stable key for saves, rendering, and compatibility. `EnemyAi` and `EnemySubState` remain shared flat structures; there is no per-role `RoleState`. |
| Per-tick loop | `sim/step.rs` enemy update and post-update passes | Builds one `Perception` and `AiSkill` snapshot, updates regular enemies through `update_regular_behavior`, resolves `AttackDirector` proposals, commits granted attacks, then computes formation targets and integrates movement. Bosses still use `update_boss_enemy`. |
| Role behaviors | `sim/behaviors.rs` `update_*` | Regular-role updates use typed `EnemyRole` dispatch and return `MoveIntent`; timers and role fields still live in shared `EnemyAi`. Boss behavior remains separate. |
| Formation and locomotion | `sim/steer.rs::compute_formation_targets`, `sim/locomotion.rs::integrate_batch` | Formation v2 maintains an axis/anchor and role slots. One integrator blends intents, slots, turn/acceleration limits, neighbor avoidance, and arena routing; overlap resolution follows it. |
| Attack permission | `sim/director.rs::AttackDirector` | Regular attacks use a deterministic two-pass proposal/grant process with threat score, budget, role/category stagger, visibility, forced grants, and post-hit breathing room. The old `AttackScheduler` type is still instantiated and passed through `BehaviorContext`, but regular attack updates no longer call its request method; it is leftover scaffolding. |
| Perception and skill | `sim/perception.rs`, `sim/ai_skill.rs` | Per-tick perception contains smoothed velocity, input intent, aim, dash/invulnerability, hull, Ultra readiness, view bounds, and breathing room. Difficulty/wave profiles scale reaction, lead, dodge, aim jitter, coordination, and formation movement. |
| Prediction | `sim/behaviors.rs::predict_target` | Regular-role aim uses the perception/skill prediction path. The legacy `lead_dir` helper remains for the boss follow-up; boss aim has not been migrated to the shared predictor. |
| Measurement | `tests/ai_fairness.rs`, `tests/ai_core.rs`, `examples/profile_sim.rs` | Headless tests cover core behavior and report fairness diagnostics. WP-G still lacks persistent `AiTelemetry` and the authored-wave per-role profile table; stationary-target accuracy is only a controlled diagnostic, not proof of live-play fairness. |

### Work-package status

| Package | Status as of 2026-11-17 | Evidence and remaining work |
| --- | --- | --- |
| WP-A — typed roles | **Core implemented; state split incomplete.** | `EnemyRole`, `Enemy.role`, typed regular dispatch, and `attack_phase()` exist. Keep the string key for compatibility. `EnemyAi` remains a flat role/boss grab bag; no role-specific state enum was added. |
| WP-B — perception | **Implemented for regular AI; boss follow-up remains.** | `Perception` and `PerceptionMemory` are built once per tick and passed to regular behaviors. Bosses still use their separate aiming code. |
| WP-C / WP-I — intent and locomotion | **Core implemented.** | Regular updates return `MoveIntent`; `locomotion::integrate_batch` applies one integration pass with per-role kinematics, route points, spatial-grid avoidance, and overlap resolution. Targeted coverage is in `tests/ai_core.rs`, not the separate test files originally named here. |
| WP-D — skill and prediction | **Core implemented; boss migration remains.** | `AiSkill` and regular `predict_target`/dodge logic are in the current path. Verify coverage against the original per-role acceptance list before treating every detail as done. |
| WP-E — attack director | **Regular path implemented.** | `AttackDirector` performs two-pass grants. Legacy `AttackScheduler` scaffolding remains unused by regular updates and should be removed or explicitly retained for a future caller. |
| WP-F — per-role upgrades | **Partial / not reconciled role by role.** | Behavior code has been revised, but the original WP-F acceptance criteria have not all been audited against current source and measurements. |
| WP-G — telemetry and fairness | **Measurement harness implemented; fairness conclusion open.** | `tests/ai_fairness.rs` measures director-budget grants on Easy/Normal/Hard across Circle/Donut/Cross/Diamond, Normal commits during invulnerability, a Ranged minimum warning check, per-role first-attack warning-to-hit samples, and matched Easy/Hard projectile collisions. The five matched seeds each run 180 simulated seconds with both a moving orbit bot and a stationary high-HP target. The stationary sample is only a controlled diagnostic, and its ratio is not a hard test assertion or a fairness verdict. No persistent `AiTelemetry`, authored-wave per-role profile table, or regenerated behavior-sheet metrics table exists yet. |
| WP-H — formation v2 | **Core implemented; performance/reporting acceptance open.** | `FormationState`, weighted crowd axis, rate-limited anchor, centered role slots, angular stability, arena-aware placement, and `tests/ai_core.rs` coverage exist. The originally named `formation_debug` output and dedicated `tests/formation.rs` do not. |

#### WP-G headless run record (2026-11-17)

The harness passed 2/2 tests in 106.38s. It used fixed seeds 71009, 71771, 90001, 90019, and 91771. The all-map budget/invulnerability sweep used 30 simulated seconds per seed, map, and difficulty. Across Normal's 1,017 observed commits, 78 (7.67%) began while the player was invulnerable. The grant-budget assertions passed; maximum active committed weight in the stationary-target comparison was 4 on Easy and 5 on Hard. A separate Ranged assertion confirmed its first physical projectile hit was no earlier than its authored 0.34s warning.

The 180-second moving-orbit runs produced few projectile collisions, so they are useful as a limitation check rather than a stable hit-rate estimate:

| Seed | Easy collisions / shots | Hard collisions / shots |
| --- | ---: | ---: |
| 71009 | 1 / 237 | 3 / 191 |
| 71771 | 0 / 235 | 0 / 182 |
| 90001 | 0 / 222 | 4 / 236 |
| 90019 | 1 / 231 | 1 / 252 |
| 91771 | 2 / 273 | 0 / 239 |
| **Total** | **4 / 1,198** | **8 / 1,100** |

The stationary-target test counts physical enemy-projectile collision events divided by fired enemy projectiles. Easy recorded 887 / 2,360 (37.58%), with 819 accepted damage events; Hard recorded 1,241 / 2,727 (45.51%), with 1,098 accepted damage events. The pooled 1.211× result is descriptive only: it does not measure a moving player's actual damage exposure and must not be used alone to claim the game is fair or that Hard has adequate fairness/readability.

Role commits below are from the moving-orbit runs over five 180-second seeds per difficulty. Warning-time samples are the first physical damaging hit after the first commit in five isolated Normal runs per role; a role may have no hit sample in some seeds. These sample counts are small and do not cover every move variant.

| Role | Commits Easy / Hard | First-attack warning-to-hit median (samples / 5) |
| --- | ---: | ---: |
| Chaser | 99 / 126 | 2.117s (3) |
| Ranged | 269 / 238 | 1.450s (3) |
| Sniper | 198 / 207 | 0.933s (5) |
| Bomber | 203 / 192 | 1.850s (5) |
| Tank | 4 / 5 | 1.233s (5) |
| Charger | 10 / 10 | 1.400s (5) |
| Spitter | 229 / 211 | 1.533s (4) |
| Flyer | 100 / 114 | 0.817s (4) |
| Engineer | 239 / 248 | 1.250s (5) |
| Swarmer | 0 / 0 | No committed attack phase; 5 contact hits had no warning commit |
| Egg Sac | 0 / 0 | No committed attack phase; summons other roles |

**Still open for WP-G:** add reusable per-role telemetry for commits, phases, and warning-to-damage; measure authored waves 5/10/14/15; profile per-role behavior across difficulties; regenerate the behavior-sheet measurement table; and evaluate player damage/hit-rate fairness with a representative moving bot and a larger, robust hit sample. The current test does not gate on Hard/Easy accuracy ratio.

---

## 2. Problems found (each with evidence)

**P1 — Two movement controllers fight every tick.**
Each behavior computes a velocity that includes orbit, zig, dodge, strafe and separation, and integrates it. `steer_formation_batch` then replaces that velocity for every coordinated role that is not holding a telegraph. The behavior's intent survives only through the `vel_dir * 0.45` inertia term in `steer_velocity`, limited by `max_step = speed * 3.2 * steer_mult * dt`. As a result:
- a 0.16s projectile dodge is mostly cancelled by slot seeking (the dodge only lives inside the behavior's velocity);
- the Ranged/Spitter strafe and the Chaser orbit are blended toward the slot, so roles feel alike;
- tuning a role in `behaviors.rs` has an unpredictable result, because `steer.rs` changes it afterwards.

**P2 — Prediction is fooled by dashes and jitter.**
`player_vel = (pos - old_pos) / dt` is a one-step sample. During a dash it is several times normal speed, so the Chaser lunge (`player_vel * 0.22`), Tank (0.6s lead), Bomber (0.25s), Engineer (0.65s) and `lead_dir` users aim far past the player. When the dash ends, shots fly into empty space. The same sample also carries wall-clamp and knockback spikes.

**P3 — Difficulty changes numbers, not decisions.**
Easy, normal and hard differ in formation pressure/arcs and stat multipliers only. Reaction time, prediction quality, dodge willingness and coordination are identical, so Easy enemies make perfect lead shots and Hard enemies never get smarter.

**P4 — The scheduler only counts enemies, not threat.**
`AttackScheduler::for_enemies` sets capacity from `live_non_boss` alone. It ignores:
- whether the attacker is on screen or in the player's view (off-screen snipers can be granted the slot while on-screen chasers wait);
- whether the attack can actually hit soon (distance, range gate);
- how recently the player was hit (no breathing room after damage);
- a fairness order between roles (the first enemy in vector order that asks wins; same-role stagger is the only spreading).

**P5 — Role logic is stringly typed and the state is a grab bag.**
`match enemy.behavior.as_str()` appears in `update_regular_behavior`, `active_attack_weight`, `holding_telegraph`, `is_coordinated_behavior`, `dodge_player_projectiles` (cooldown table), `coord_radius`, `min_forward`, `slot_radius`, `role_weights` and others. A typo silently becomes "unknown role". `EnemyAi` has more than 50 fields, most unused by any given role. The Chaser keeps its state in `lunge_windup`/`lunge_t` instead of `sub_state`, so code that asks "is it attacking?" needs a special case per role (see `holding_telegraph`).

**P6 — Enemies don't read the player's state.**
Nothing in `BehaviorContext` says whether the player is dashing or invulnerable, boosting, low on hull, has an Ultra ready, or which way they are aiming. Enemies cannot:
- hold an attack during dash i-frames (shots are wasted while the player feels nothing);
- back off when aimed at (snipers and ranged stand in the player's crosshair);
- press harder when the player is low.

**P7 — Evasion is all-or-nothing and identical by skill.**
`dodge_player_projectiles` reacts to any player shot within 0.42s, with only a per-role rest period. There is no reaction delay (a perfect same-tick read), no per-difficulty chance or skill, and no account of whether the escape side leads into the arena wall or another shot.

**P8 — Nothing measures whether the AI is fair or readable.**
The bot test proves progress. It does not measure:
- time from an attack becoming visible to damage (readability);
- how many attackers commit at the same moment (pile-ups);
- the share of enemy shots that are aimed into a dash (wasted shots);
- how long each role spends idle versus pressuring.

---

## 3. Target design (one paragraph per idea, then the packages)

- **Intent, then one integrator.** Behaviors stop moving the enemy. Each returns a `MoveIntent { desired_dir, speed_mult, priority, kind }`, where `kind` is one of `Committed`, `Evade`, `RoleMove` or `Idle`. One integration step blends the intent with formation:
  - `Committed` (lunge, charge, flyer dash) ignores formation entirely;
  - `Evade` gets ≥70% weight for its 0.16s;
  - `RoleMove` gets a per-role formation weight from a data table.

  This removes P1 and makes every role tuneable in one place.
- **A perception snapshot built once per tick.** `Perception { player_pos, smoothed_vel, intent_vel, aim_dir, is_dashing, invulnerable_left, boosting, hull_frac, ultra_ready, on_screen_rect }` is computed in `step.rs` before the enemy loop and handed to every behavior. `smoothed_vel` is an exponential average with τ ≈ 0.12s on enemy time. `intent_vel` is the move-input direction × base speed, with dash and knockback excluded. Prediction code uses `intent_vel`, never the raw delta (P2, P6).
- **A skill profile per difficulty.** `AiSkill { reaction_s, lead_quality, dodge_chance, dodge_reaction_s, respects_iframes, aim_jitter_deg, coordination }` comes from difficulty (and optionally wave). Decision code reads skill values instead of constants (P3, P7).
- **A threat-aware attack director** replaces the count-only scheduler. It ranks the attack requests made this tick by a deterministic score, then grants them within a budget that shrinks briefly after the player takes damage (P4).
- **A typed role enum and per-role state.** `EnemyRole` replaces string matching. `RoleState` is an enum with one variant per role holding only that role's fields. Commit/attack detection becomes one method (P5).
- **A telemetry hook** for the headless harness that records the readability and fairness numbers above (P8).

---

## 4. Work packages

Packages are ordered by dependency. **WP-A and WP-B can run in parallel.** WP-C needs A. WP-D needs A and B. WP-E needs B and C. WP-F needs D. WP-G can start any time after A and runs last for its numbers. Every package ends with `cargo check -p plouto_rs --all-targets` and `cargo test -p plouto_rs` passing, plus the replay-version bump if behavior changed.

### WP-A — Typed roles (refactor, no behavior change)
**Owns:** `sim/enemy.rs`, the role-dispatch sites in `sim/behaviors.rs`, the role tables in `sim/steer.rs`, plus `sim/level.rs` and `sim/step.rs` only where they compare role strings.
1. Add `#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)] pub enum EnemyRole { Chaser, Ranged, Sniper, Bomber, Tank, Charger, Spitter, Flyer, Engineer, Swarm, EggSac, Boss }` with `fn from_key(&str) -> Option<Self>` and `fn key(self) -> &'static str`. Boss keys (`boss_*`) map to `Boss`.
2. Add `pub role: EnemyRole` to `Enemy`, set in `Enemy::new` from `behavior`. **Keep `behavior: String`**, because saves, replays, render and the guide read it. `role` is derived from it and never written separately.
3. Replace every `match enemy.behavior.as_str()` in the AI files with `match enemy.role`. Unknown keys log nothing and map to a `Chaser`-like default only where today's code already falls through to a default (preserve each site's current fallback exactly).
4. Add `impl Enemy { pub fn attack_phase(&self) -> AttackPhase }` returning `Idle | Windup { frac } | Active | Recover`. It is computed from today's fields, including the Chaser's `lunge_windup`/`lunge_t`. Rewrite `active_attack_weight` and `holding_telegraph` on top of it.
5. **Acceptance:**
   - the replay fingerprint for a fixed seed is unchanged (run an existing replay test before and after);
   - no version bump, since behavior is unchanged;
   - `grep -n 'behavior.as_str()' sim/behaviors.rs sim/steer.rs` returns only lines that deliberately need the raw key (document each one).

### WP-B — Perception snapshot (additive)
**Owns:** `sim/step.rs` (the enemy-loop preamble only), a new `sim/perception.rs`, and the `BehaviorContext` struct definition in `sim/behaviors.rs`.
1. Create `sim/perception.rs` with `pub struct Perception` (fields as in section 3) and `pub struct PerceptionMemory { smoothed_vel: Vec2 }`, stored in `SimState`.
2. `smoothed_vel += (raw_vel - smoothed_vel) * (1 - exp(-enemy_dt / 0.12))`. Skip the update while `player.is_dashing` or during knockback, which freezes the estimate through dashes.
3. `intent_vel = move_input_dir * player.base_speed * (boost ? boost_mult : 1)`. Read it from the `SimInput` already passed to `step`. `move_dir` is in `SimInput` and is recorded in replays, so it is deterministic.
4. `on_screen_rect`: compute the world-space AABB of the camera view from the same values `render/world.rs` uses (`cam_world`, view size, the iso transform in `sim/math.rs`). If the sim has no view size, use `room_radius` and treat everything inside the arena as visible. Document that choice.
5. Add `perception: &'a Perception` to `BehaviorContext`. Do **not** change any behavior yet.
6. **Acceptance:** compiles; fingerprint unchanged unless `PerceptionMemory` is hashed. If it is hashed, bump the version and say so.

### WP-C — Intent + single integrator (fixes P1)
**Owns:** `sim/behaviors.rs` (all `update_*`), `sim/steer.rs`.
1. Add `pub struct MoveIntent { dir: Vec2, speed_mult: f32, kind: IntentKind }`, where `IntentKind` is `Committed | Evade | RoleMove | Hold`. Change every `update_*` to **return** a `MoveIntent` and **stop** writing `enemy.pos`. They may still set `enemy.vel` for animation only. Leave bosses alone in this package.
2. In `step.rs`, store the intents in a `Vec<(usize, MoveIntent)>` in index order. `steer_formation_batch` takes the intents:
   - `Committed`/`Hold`: velocity = `dir * speed * speed_mult`; no formation; no obstacle steer for committed lunges (today's behavior).
   - `Evade`: `desired = 0.7*dir + 0.3*formation_dir`.
   - `RoleMove`: `desired = (1-w)*dir + w*formation_dir`, where `w` comes from a table: Chaser 0.35, Ranged 0.45, Sniper 0.25, Bomber 0.40, Tank 0.55, Charger 0.45, Spitter 0.45, Flyer 0.20, Engineer 0.45. Swarm and EggSac keep their own controllers with `w = 0`.
   - Then apply the existing steering limit (`max_step`), the max-speed clamp and **one** position integration.
3. Delete the `(new_vel - snap.vel) * dt` correction, because nothing has been integrated before this point any more.
4. **Acceptance:**
   - new test `dodge_survives_formation`: one Ranged enemy and one player shot on a collision course; over the 0.16s evade window its lateral displacement is ≥ 60% of an unconstrained dodge (today it is much lower; record the before number in the report);
   - new test `committed_lunge_ignores_slot`: the lunge heading is constant through `lunge_t`;
   - existing tests pass;
   - version bump.

### WP-D — Prediction and the skill profile (fixes P2, P3, P6, P7)
**Owns:** `sim/behaviors.rs` (aim and dodge code), a new `sim/ai_skill.rs`, and `sim/steer.rs` `formation_profile` only to read `AiSkill`.
1. `sim/ai_skill.rs`: `pub fn ai_skill(difficulty: &str, wave: i32) -> AiSkill`. The wave ramp is linear from wave 1 to wave 20, then clamps.

   | Field | Easy (w1 → w20) | Normal | Hard |
   | --- | --- | --- | --- |
   | `reaction_s` (delay before re-targeting after the player changes direction) | 0.30 → 0.24 | 0.22 → 0.16 | 0.14 → 0.10 |
   | `lead_quality` (0 = aim at current position, 1 = full intent lead) | 0.35 → 0.55 | 0.60 → 0.80 | 0.85 → 1.00 |
   | `dodge_chance` (per threat event, rolled with `ctx.rng`) | 0.25 → 0.40 | 0.45 → 0.65 | 0.70 → 0.85 |
   | `dodge_reaction_s` (threat must be seen this long first) | 0.18 | 0.12 | 0.08 |
   | `respects_iframes` (hold fire while `invulnerable_left` covers the projectile's flight time) | false | true | true |
   | `aim_jitter_deg` (deterministic, from `ctx.rng`, at commit time) | 7 → 5 | 4 → 2.5 | 2 → 1 |
   | `coordination` (scales director budget and flank use) | 0.8 | 1.0 | 1.15 |

2. Add one function, `predict_target(p: &Perception, from: Vec2, proj_speed: f32, max_lead_s: f32, skill: &AiSkill) -> Vec2`. It uses `intent_vel`, then `smoothed_vel` when there is no input, clamps lead time to `max_lead_s`, clamps the result inside the arena, blends by `lead_quality`, then applies `aim_jitter_deg`. **Every** role's aim goes through it. Replace each ad hoc `player_pos + player_vel * k` in Chaser, Ranged, Sniper, Bomber, Tank, Charger, Spitter, Flyer and Engineer. Keep each role's current `max_lead_s` (the k in today's code) so tuning starts from today's numbers.
3. Reaction delay: keep `last_seen_intent` and `retarget_left` in role state. A new player intent direction (angle change > 25°) starts `retarget_left = reaction_s`. Until it reaches 0, prediction uses the previous intent.
4. Dodge:
   - a threat must persist for `dodge_reaction_s` (track by projectile id in a small fixed array of up to 8);
   - then roll `dodge_chance` once per projectile id;
   - reject an escape direction that points within `radius + 24` of the arena edge (use the existing map clamp helpers) or into another threat's lane; try the other side once, then give up.
5. I-frame respect: when `respects_iframes` is true and `perception.invulnerable_left > time_to_impact`, delay the attack commit by up to that amount. This does **not** cancel already-committed attacks.
6. Aim-awareness, for Sniper and Ranged only: if the angle between `perception.aim_dir` and (enemy − player) is under 12° for 0.4s, the next relocation prefers a sidestep perpendicular to the player's aim. Use the existing `relocate_t` / `strafe_sign`.
7. **Acceptance tests:**
   - `prediction_ignores_dash_spike`: the player dashes for 0.2s; a Tank aim point stays within 40 units of the post-dash intent path;
   - `easy_misses_more_than_hard`: the same seed and bot over 60s; enemy hit rate on Easy < Normal < Hard;
   - `iframe_hold`: with the player invulnerable for 0.3s, a Ranged enemy whose shot would land inside that window commits after it ends;
   - `dodge_edge_safe`: an enemy at the arena edge never dodges outward.
   - Version bump.

### WP-E — Attack director (fixes P4)
**Owns:** the `AttackScheduler` in `sim/behaviors.rs` (or move it to a new `sim/director.rs`), and the `step.rs` lines that build and use it.
1. Two-pass grants, deterministic:
   - **pass 1:** behaviors that want to start an attack call `director.propose(enemy_id, weight, score_inputs)` and receive `Pending`;
   - **pass 2:** after the loop, the director sorts proposals by `(score desc, spawn_index asc)` and grants within budget;
   - **next tick:** granted enemies start their windup. This adds one tick (16ms) of latency, which is acceptable, and removes vector-order bias.
2. `score = 3*on_screen + 2*in_range_now + 1.5*min(denied_t/1.6, 1) + role_bonus`. `role_bonus` is +1 for a role whose kind isn't currently attacking: melee (Chaser, Charger, Flyer), ranged (Ranged, Spitter, Sniper, Tank) or area (Bomber, Engineer). This mixes attack types instead of firing three of the same.
3. `budget = base_capacity * coordination`, rounded down, with a minimum of 1. During the 0.6s after the player loses hull (`hull_frac` drop), the budget is `max(1, budget - 1)` (a breathing room). No grants to off-screen enemies while any on-screen proposal is pending, except Sniper (its long telegraph is the counterplay) and forced grants.
4. Keep the forced-grant rule (1.6s denial), but limit it to on-screen enemies or enemies within 1.2× their attack range.
5. Expose `director.debug_counts()` (granted, denied by reason) for WP-G.
6. **Acceptance:**
   - `director_is_order_independent`: shuffling the enemy vector order (rebuilding the state with permuted spawn order but identical `spawn_index`) yields the same grants;
   - `breathing_room`: after a player hit, no more than `budget-1` new commits start within 0.6s;
   - `offscreen_waits`: with an on-screen Chaser and an off-screen Ranged proposing together, the Chaser is granted first.
   - Version bump.

### WP-F — Per-role upgrades (on top of C, D and E)
**Owns:** the role's `update_*` function in `sim/behaviors.rs`. One agent per row is fine if they keep to their own function. Any shared helper change goes in the report, not the code. Numbers are starting points; keep the telegraph contract.

| Role | Change | Why | Acceptance |
| --- | --- | --- | --- |
| **Chaser** | Commit to the lunge from `predict_target` with `max_lead_s` = time-to-contact at lunge speed (cap 0.35s). The orbit sign flips (deterministically from `seed`) when the player is aiming at it. Remove `sep * 0.3` during an active lunge: committed means straight. | Today's lunge leads by a fixed 0.22s, and it drifts after commit. | Lunge path is a straight segment; the orbit flip is observed in a scripted aim test. |
| **Ranged** | Burst of 2: shot 1 at the predicted point, shot 2 at the predicted point offset ±10° toward the player's current move side (cuts off strafing). Relocation picks a point on its slot ring that keeps line-of-sight distance 220–340 and is ≥60° from the nearest other Ranged around the player. | Two identical leads are dodged by one sidestep; ranged units clump. | Spacing test: 3 Ranged keep ≥ 50° angular separation for 80% of 10s. |
| **Sniper** | During aim, track `smoothed_vel` (not raw) and freeze for the last 0.26s (already the case). After firing, relocate if the player is aiming at it (WP-D aim awareness). Off-screen snipers are only granted when they are at least 60 units inside the view edge, so the beam origin is visible. | The beam origin must be visible to be fair. | Beam start point is inside the view AABB in 100% of fires during a 2-minute bot run. |
| **Bomber** | Choose the drop point from three candidates (predicted, predicted ± 60 units along the player's intent normal) and pick the one that covers the most likely escape: the one closest to the player's predicted position *after* `BOMBER_FUSE_SECONDS`, using intent. Keep the 0.60s lock and the exact blast ring. | Today it always drops on the linear prediction; sidestepping always works. | Candidate choice is deterministic; the ring still matches the blast radius exactly. |
| **Tank** | Turret turns at a capped rate (90°/s at Normal, `× coordination`) toward `predict_target`. The cannon lane is locked at windup start and does not move. Tank prefers slots in front of the player's move direction (blocking). | A turret rate makes the threat readable; blocking gives the Tank a role. | Lane angle constant over the 0.48s windup; Tank slot is within ±45° of the player's intent heading 70% of the time. |
| **Charger** | Charge only if the straight path to the target is ≥ 120 units long and not mostly along the arena wall. Otherwise reposition to a flank angle first. On a miss, brake for 0.25s before recovery (visible skid). Use `predict_target` with `max_lead_s = path_len / charge_speed`, capped at 0.5s. | Wall charges look broken and time out. | No charge starts with < 120 units of clear path; the timeout rate in a 2-minute bot run falls below 5% of charges. |
| **Spitter** | Fan centre on the predicted point; alternate fans as today. Narrow fan when the player is moving fast and straight, wide fan when they are strafing short (intent direction changes within 0.5s). | The fan choice should answer the player's movement. | Choice is deterministic from perception. |
| **Flyer** | Pick the dash line to cross the player's predicted path (perpendicular intercept), not to aim at the point. If the intercept is outside the arena, fall back to today's point dash. Keep the 1.35s timeout. | Dashing *across* the path reads well and punishes running straight. | Intercept geometry test. |
| **Engineer** | Place mines on the player's predicted path at 0.65s, but never within 70 units of another live mine, and prefer chokepoints: points where the arena shape narrows (Cross arms, Donut ring). Use the `map_type` and `room_radius` geometry already in `sim/layout.rs` / `sim/math.rs` clamp helpers. | Today mines can stack on top of each other. | Mine spacing ≥ 70 units in a 2-minute run. |
| **Swarm** | No new behavior. Only take `perception` for the surge target (intent lead capped at 0.3s), so a dash doesn't drag the surge. | Consistency with P2. | Surge target unaffected by the dash spike (same test shape as WP-D). |
| **Egg Sac** | No change. | — | — |

Version bump once, for the whole package.

### WP-G — Telemetry and fairness checks (fixes P8)
**Owns:** a new `sim/ai_telemetry.rs` (feature-gated or a plain struct the harness reads), `examples/profile_sim.rs`, and a new test file `tests/ai_fairness.rs`.
1. `AiTelemetry` in `SimState`, **excluded from the replay fingerprint**. Mark it clearly and do not add it to `state_hash`. It counts, per role:
   - commits;
   - commits made while the player was invulnerable;
   - warning-to-damage times (min and mean);
   - simultaneous commits (max concurrent active weight);
   - charges that timed out;
   - shots that landed vs fired;
   - seconds spent in each `AttackPhase`.
2. `profile_sim` prints a per-role table for the authored waves 5/10/14/15 plus the three difficulty presets.
3. `tests/ai_fairness.rs` hard limits:
   - no damaging regular attack lands less than its documented warning time after its commit;
   - max concurrent committed weight ≤ director budget, except forced grants (≤ 1 extra);
   - on Normal, < 10% of commits happen while the player is invulnerable;
   - on Hard, enemy hit rate is at least 1.2× Easy for the same bot and seed.
4. These numbers go into a table at the bottom of `docs/design/ENEMY_BEHAVIOR_SHEETS.md`, regenerated by running the example. Date the table and don't edit it by hand.

### WP-H — Formation system v2 (replaces `build_role_formation`)

**Owns:** `sim/steer.rs` (formation half), plus a new `sim/formation.rs` if the agent splits it out. Depends on WP-A (typed roles), WP-B (perception) and WP-I (locomotion consumes the slot targets).

#### Problems in today's formation (`steer.rs` `build_role_formation`, `assign_arc`, `steer_velocity`)

| # | Problem | Evidence | Effect |
| --- | --- | --- | --- |
| F1 | **Front and back are probably reversed.** | `front_dir = player - centroid(enemies)`; "front" slots are at `anchor + dir(base_ang) * r`, which is the side of the player *away* from the enemy crowd. "Backline" (`base_ang + PI`) is on the crowd's side. | Tanks, Chargers and Chasers are sent *through or around* the player to the far side, while ranged units stay on the near side. **Verify with a test first** (one Tank and one Ranged, both on +x of the player: today the Tank's slot is expected at −x). If confirmed, it is a bug, not a pincer design: the design intent in `role_for_behavior` names it "front". |
| F2 | **One member stands at the arc edge, not the centre.** | `frac = within_ring / (slots_per_ring - 1) - 0.5`; slot 0 gives `frac = -0.5`. | Small squads (the common case) are lopsided: a lone Tank sits 24° off the front axis, and a lone Ranged sits 54° off. |
| F3 | **Slot indices never compact.** | `formation_slot` is kept forever; new members take the lowest free index, but survivors keep high indices. | After deaths, 2 survivors can sit in slots 3 and 4, both on one side of the arc. |
| F4 | **The axis follows a feedback loop.** | The front axis is rebuilt every tick from the centroid of the enemies, who are themselves moving to slots defined by that axis. | The whole formation slowly rotates or drifts around the player with no player input. |
| F5 | **The anchor jumps on a dash.** | `anchor = player_pos + player_vel * lead_time`, using the raw one-step velocity (P2). | The whole formation lurches during a dash, then snaps back. |
| F6 | **Slots outside the arena pile up on the wall.** | `clamp_entity_to_map` projects each invalid slot to the nearest wall point independently. Donut: radially onto the hole edge. Cross/Diamond: onto the nearest edge. | Several enemies share one wall point, the overlap solver pops them apart, and they jitter. |
| F7 | **Assignment ignores where enemies are.** | `assign_arc` orders members by `formation_bias`, then `seed`, not by position. | Enemies cross paths to reach slots on the far side and bump into each other mid-route. |
| F8 | **Cohesion fights slot spread.** | `steer_velocity` adds `cohesion * 0.24` toward the same-role squad centre while slots spread the squad out. | Squads bunch inward between their slots. |
| F9 | **Slot rings ignore arena size.** | Fixed base radii (108–212) with a +8 to +16 step per ring, regardless of `room_radius` or map shape. | In small arenas, rings 2+ fall outside the arena (feeds F6). In big arenas, the backline sits too close. |

#### Design

1. **A stable front axis.** Keep `FormationState { axis: Vec2, anchor: Vec2 }` in `SimState`, included in the fingerprint, with a replay-version bump.
   - The target axis is the direction from the **player** toward the crowd, using a weighted centroid. Weights are front roles 1.0, mid 0.6, backline 0.3 and support 0.2, so a lone engineer behind the player cannot flip the axis.
   - The axis turns toward its target at most **40°/s** (Easy 30, Hard 55), and only if the target differs by more than 15° (hysteresis).
   - The anchor is `player_pos + perception.intent_vel * lead_time`, moved toward its target at most `2 × player_base_speed` per second, so a dash cannot jerk it.
2. **Fix the orientation.** "Front" slots sit **between the player and the crowd**: `anchor + axis * r`, where `axis` points from the player toward the crowd. Backline and support sit farther out on the same side (`r` larger), and flanks at `±flank_offset`. If F1's test shows the encirclement was deliberate, keep encirclement **only** for Flyer and Swarm, through the flank ring.
3. **Centred, compact slots.**
   - A ring of capacity `c` holding `n` members spreads them at `frac_i = (i + 0.5) / n - 0.5` across `arc × min(1, n / c)`. One member is always at the centre, and the arc widens as members join.
   - Each tick, members are re-indexed 0..n−1 by stable sort key. This removes the persistent index gaps (F3).
   - Stability comes from item 4 (assignment), not from frozen indices.
4. **Position-aware, stable assignment (F7).**
   - Within each role group, order the slots by angle and the members by their current angle around the anchor (relative to the axis), then match them in order. This is optimal for points on an arc and has no crossings.
   - Hysteresis: a member keeps its previous slot unless the re-sorted match improves its angular error by more than 10°.
   - Ties break by `spawn_index`. All of this is deterministic: plain sorts with `total_cmp`, then `spawn_index`.
5. **Arena-aware slots (F6, F9).**
   - Ring radius = `base_r * k`, where `k = clamp(room_radius / 420, 0.75, 1.25)`. Calibrate 420 to the "normal" arena: read the default `room_radius` from `sim/config.rs` and record the number used.
   - A slot outside the arena is **not** clamped. Its angle slides along its ring in 6° steps, up to 60°, toward the arc centre until it lands inside the playable area.
   - If no angle works, the slot moves to the next ring inward. Only after that does it fall back to `clamp_entity_to_map`, offset by `index × (2 × radius + 6)` along the wall tangent so slots never share a point.
   - Donut: a slot whose straight line from the anchor crosses the hole is only valid if the member can reach it with the WP-I path rule.
6. **Separation instead of cohesion (F8).** Drop the squad-cohesion term. Keep separation, using the body radius + 8, not `coord_radius × 0.45`. Correct slots already keep the squad together.
7. **Role rings (starting numbers, × k):**

   | Ring | Roles | Radius | Arc | Note |
   | --- | --- | --- | --- | --- |
   | Wall | Tank | 105 | 50° | Blocks the player's intent direction: centre the arc on `lerp(axis, intent_dir, 0.5)` when the player is moving. |
   | Strike | Chaser, Charger | 130 | 80° | Chargers prefer the arc ends (diagonal lines leave the most room for a charge). |
   | Flank | Flyer (Swarm stays on its own controller) | 140 | 60° per side at ±80° | Left/right by `spawn_index` parity, not the RNG bias. |
   | Mid | Bomber | 160 | 90° | Offset +25° from the axis, alternating sign per member. |
   | Back | Ranged, Spitter, Sniper | 190 / 175 / 260 | 110° | Sniper on its own outer ring. Today it has no formation slot; give it one. |
   | Support | Engineer | 215 | 70° | Prefers the side opposite the Bomber offset. |

8. **Debug output:** `formation_debug(&SimState) -> Vec<(u64, Vec2 slot, f32 angular_error)>` for tests and the WP-G telemetry.
9. **Acceptance tests (new `tests/formation.rs`):**
   - `single_member_centered`: 1 Tank → slot angle error < 1° from the axis;
   - `axis_rate_limited`: teleport the crowd to the other side → the axis turns ≤ 40°/s on Normal;
   - `no_crossing_assignment`: 6 Ranged at random angles → the matched pairs' line segments do not intersect;
   - `slots_inside_arena`: for all 4 map shapes and ring counts up to 3, every slot is inside the playable area, and no two slots are closer than the sum of their member radii;
   - `dash_does_not_jerk_anchor`: the anchor moves ≤ `2 × base_speed × dt` per step during a dash;
   - plus F1's orientation test.
   - Version bump.

### WP-I — Self-movement (locomotion) model

**Owns:** a new `sim/locomotion.rs`, the integrator that WP-C introduces (it moves here), and `resolve_enemy_body_overlaps` / `move_enemy_for_clearance` in `sim/step.rs`. Depends on WP-C. Do WP-C and WP-I in **one** package if possible; they touch the same lines.

#### Problems in today's self-movement

| # | Problem | Evidence | Effect |
| --- | --- | --- | --- |
| M1 | **Instant turning and acceleration.** | Behaviors write `enemy.vel = dir * speed * mult` directly. Only coordinated roles outside a telegraph pass through `steer_velocity`'s `max_step`. | Enemies snap 180° in one frame. It looks robotic and makes animation lean impossible. |
| M2 | **No arrival behavior.** | Slot steering desires full speed until the target is passed. | Enemies overshoot slots and oscillate (jitter) at their post. |
| M3 | **Reactive avoidance only.** | Separation acts only once bodies are already within range. There is no look-ahead for an enemy that is about to cross a path. | Head-on approaches resolve only after contact, through the overlap solver. |
| M4 | **The overlap solver teleports.** | `resolve_enemy_body_overlaps` runs 4 passes with up to 22 units of push per enemy per step (`MAX_CLEARANCE_DISPLACEMENT`). At 60 Hz that is about 1,300 units/s of sideways pop. | Visible pops in crowds. The push also ignores mass: a Swarmer can shove a Tank as much as the reverse. |
| M5 | **No route around arena shapes.** | Movement aims straight at the target; `clamp_entity_to_map` stops it at the boundary. | On Donut, enemies whose target is across the hole slide along the hole edge. On Cross, they get stuck in the inside corners between arms. |
| M6 | **Hand-made wobble.** | Chaser `zig = perp * 0.18 * sin(t * 2.6 + seed)`. Other roles have their own variants. | Wobble amplitude depends on frame and speed, and doesn't scale with difficulty. |

#### Design

1. **Per-role kinematics.** `pub struct Kinematics { max_speed_mult, accel, decel, turn_rate_deg_s, arrive_radius, mass }`, from a table keyed by `EnemyRole`. Speeds stay as multiples of today's `enemy.speed`, so the stat scaling in `level.rs` still applies. Starting values:

   | Role | accel (× speed / s) | decel | turn °/s | arrive r | mass |
   | --- | --- | --- | --- | --- | --- |
   | Chaser | 6.0 | 8.0 | 540 | 18 | 1.0 |
   | Charger | 4.0 | 6.0 | 360 (charge: 0, committed) | 20 | 1.6 |
   | Tank | 2.2 | 3.0 | 150 | 24 | 4.0 |
   | Flyer | 7.0 | 5.0 | 720 | 16 | 0.7 |
   | Ranged / Spitter | 4.5 | 6.0 | 420 | 22 | 1.0 |
   | Sniper | 3.0 | 6.0 | 300 | 26 | 1.0 |
   | Bomber | 3.5 | 4.5 | 320 | 24 | 1.3 |
   | Engineer | 4.0 | 6.0 | 360 | 22 | 1.1 |
   | Swarm | 8.0 | 8.0 | 900 | 12 | 0.4 |
   | Egg Sac | — | — | — | — | 3.0 (static) |

2. **One integrator** (`locomotion::integrate`), in this order:
   1. Take the desired velocity from the WP-C intent blend.
   2. **Arrive:** within `arrive_radius × 3` of the target, scale the desired speed by `dist / (arrive_radius × 3)`; inside `arrive_radius`, desired speed is 0 and the enemy faces the player.
   3. **Turn limit:** rotate the current heading toward the desired heading by at most `turn_rate × dt`. A `Committed` intent with `turn_rate 0` keeps its heading.
   4. **Speed change:** limited by `accel` or `decel × speed × dt`.
   5. Integrate the position **once**.
   6. Store `heading: Vec2` and `accel_vec: Vec2` in `EnemyAi` for animation lean. Render reads them; see section 6.
   - Evade intents get `turn_rate × 2` and `accel × 1.5` for their 0.16s, so a dodge still reads as a sharp move.
3. **Predictive avoidance (M3).**
   - For each enemy, look at up to 6 nearest neighbours. They come from a uniform grid built once per tick (cell = 64 units, deterministic insertion by index) instead of today's all-pairs loops.
   - Compute the time of closest approach `t*` for each. If `t* < 0.5s` and the miss distance < r1 + r2 + 6, add a side-step to the desired velocity, perpendicular to the relative velocity.
   - The side is chosen by `spawn_index` parity when the geometry is symmetric, so two enemies never mirror each other forever.
   - Weight = `(1 - t*/0.5)²`. Committed movers do not avoid (they keep their line); others avoid *them* with double weight.
4. **Mass-aware overlap resolution (M4).**
   - Keep the solver as a safety net.
   - Split each push by inverse mass: `push_a = pen × m_b / (m_a + m_b)`.
   - Cap the displacement at `min(22, 0.35 × speed × dt × 60)` per step, so the pop stays under about a third of the enemy's own speed.
   - Use the WP-I grid instead of the O(n²) pair loop.
   - Anchored bodies (`enemy_holds_body_anchor`) keep infinite mass, as today.
5. **Arena routing (M5).** This is not general pathfinding: each map is a fixed convex or near-convex shape. Add a function `route_point(from, to, map_type, room_radius, pad) -> Vec2` that returns an intermediate waypoint when the straight segment leaves the playable area:
   - **Circle:** always direct.
   - **Donut:** if the segment passes through the inner hole, the waypoint is the tangent point on `inner_r + pad + 10` on the shorter side (the side is chosen by the sign of the cross product; ties go by `spawn_index` parity).
   - **Cross:** if the segment leaves the arms, the waypoint is the inner corner of the arm junction nearest to the midpoint, offset `pad + 10` into the open area.
   - **Diamond:** treat it as convex; always direct (clamping is enough).
   - The integrator steers toward `route_point(...)` instead of the final target. Recompute every tick; it's cheap, closed-form geometry.
6. **Wobble as a parameter (M6).** Replace the hand-written `zig` terms with `Kinematics.weave_amp` (0 by default; Chaser 0.15, Swarm 0.25) applied as a heading offset `weave_amp × sin(enemy_time × weave_hz + seed)`. It is frame-independent because it uses enemy time, not `t` accumulation per behavior. Easy uses 1.3 × amp (more readable weaving), Hard 0.8 ×.
7. **Acceptance tests (new `tests/locomotion.rs`):**
   - `turn_rate_respected`: command a 180° reversal; the heading change per step is ≤ `turn_rate × dt + ε`;
   - `arrives_without_oscillation`: an enemy reaching a fixed slot stays within `arrive_radius` with speed < 5% of max after 1.5s, with no sign flips of the radial velocity in the last 0.5s;
   - `head_on_avoidance`: two Chasers approaching head-on never overlap (no solver push needed) in 95% of 100 seeded trials;
   - `mass_push_ratio`: Tank vs Swarmer overlap → the Swarmer moves ≥ 8× more than the Tank;
   - `donut_routes_around_hole`: an enemy on one side with its target on the other reaches it, and never touches the hole edge for more than 0.1s;
   - `cross_corner_not_stuck`: the same on Cross, between opposite arms;
   - `max_pop`: the per-step overlap displacement never exceeds the cap.
   - Version bump.
8. **Performance budget:** the grid build is O(n); avoidance is O(n × 6); routing is O(n) closed-form. Re-run `profile_sim`. The 112-actor p95 must stay < 1.0 ms. Record before and after in the report.

---

## 5. Order and parallelism

```
WP-A ─┬─> WP-C + WP-I (one package: intent → locomotion integrator) ─> WP-H (formation v2) ─┬─> WP-E ─┐
      │                                                                                     │         ├─> WP-F (one agent per role) ─> WP-G numbers
WP-B ─┴──────────────────────────────> WP-D (prediction + skill) ───────────────────────────┘         │
WP-G harness (after A) ───────────────────────────────────────────────────────────────────────────────┘
```

- A and B touch different code and can run in parallel. B adds a field to `BehaviorContext`; A doesn't edit that struct.
- C+I and D both edit `behaviors.rs`. Split strictly by function: C+I owns the movement/integration code and the removal of `pos +=` in each `update_*`; D owns aim/dodge helpers and the aim lines. Otherwise run them sequentially (C+I first).
- H needs I's integrator (arrive, routing) and B's `intent_vel`.
- F's per-role agents each own exactly one `update_*` function. They must not edit shared helpers.

---

## 6. Interfaces the 3D-model / animation work can rely on

The model and animation pass (render side) should read **only**:
- `Enemy::attack_phase() -> AttackPhase { Idle, Windup { frac: f32 }, Active, Recover }` (WP-A);
- `enemy.vel` (still set for animation in WP-C);
- `enemy.ai.heading` and `enemy.ai.accel_vec` (WP-I) → body facing and lean/bank. Until WP-I lands, derive facing from `vel`;
- `enemy.ai.dodge_active_left > 0.0` → evade lean;
- `enemy.is_stunned(now)` → stunned pose;
- `enemy.radius` → the hitbox the sim uses (render must draw the model's body to fit this circle).

Until WP-A lands, the existing per-role fields listed in `docs/design/ANIMATION_STATE_MAP.md` remain the source of truth. Render code must never write sim state.

---

## 7. Risks and how each package avoids them

| Risk | Guard |
| --- | --- |
| Replays break silently | Version bump per package; `state_hash` comparison test before and after WP-A (which must be zero-diff). |
| Enemies become too strong on Normal | Every new skill number has an Easy/Hard pair. The WP-G hit-rate test fails if Normal exceeds the Hard band. Tuning lives in `ai_skill.rs` only. |
| Parallel nondeterminism | Director grants happen in a single-threaded sorted pass. The formation pass keeps independent per-enemy compute plus ordered apply. |
| Readability regression | The telegraph contract (rule 4) plus the WP-G minimum warning-time test. |
| Agents edit the same file at once | Ownership lists above; per-role agents in WP-F own exactly one function each. |
| Performance | All new per-enemy work is O(enemies) except dodge (already O(enemies × player shots), capped at 8 candidates). The director sort is O(proposals log proposals) with proposals ≤ live enemies. The current rules-12 pair measured 0.89–1.21 ms p95 at 112 actors: below the 16.67 ms step budget, but one run exceeds the plan's 1.0 ms target. Re-profile after future AI changes and investigate if the higher tail repeats. |

---

## 8. Bosses (only shared-framework changes)

- Bosses keep their own controllers (`sim/bosses.rs`). WP-B's `Perception` should be passed to `update_boss_enemy`, and boss aiming should switch to `predict_target` so dashes stop dragging boss lead. Each boss keeps its own `max_lead_s`. This is a separate follow-up package after WP-D; do it per boss and bump the version once.
- The director gives a boss its own lane: boss attacks never compete with summons for the budget, and summons still use the 1-slot boss-present budget.

---

## 9. Definition of done (whole plan)

- [ ] All packages merged, each with a version bump where required, and `cargo test -p plouto_rs` green.
- [x] Core intent, formation, and locomotion invariants have headless coverage in `tests/ai_core.rs`; the originally named dedicated `tests/formation.rs` and `tests/locomotion.rs` files do not exist.
- [x] `tests/ai_fairness.rs` runs headlessly across all three difficulties and four arena shapes for director-budget and Normal invulnerability-commit checks; its moving-orbit hit sample is sparse and stationary-target accuracy is diagnostic only.
- [ ] Representative moving-player fairness/readability evidence with a robust hit sample; no current measurement establishes an overall fairness verdict.
- [ ] `profile_sim` table added to `docs/design/ENEMY_BEHAVIOR_SHEETS.md`, with p95 step < 1.0 ms at 112 actors.
- [ ] `docs/design/ENEMY_BEHAVIOR_SHEETS.md` role rows updated to the new behavior, still quoting real constants.
- [ ] No `behavior.as_str()` role dispatch left in the AI files except the documented exceptions.
- [ ] Human play-test still pending. Nothing in this plan claims visual or feel verification.
