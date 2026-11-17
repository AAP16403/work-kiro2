# Rust Enemy Behavior Sheets

**Prepared:** 2026-11-16  
**Last checked against code: 2026-11-17**  
**Status:** Source audit and implementation notes. Re-checked on 2026-11-17 against `plouto_rs/src/sim/` (behaviors.rs, enemy.rs, step.rs, steer.rs, config.rs, bosses.rs). This records the current Rust behavior. It does not claim live-play or visual review.

Core typed-role AI, perception, the regular attack director, formation v2, and unified locomotion are implemented. The remaining role-validation and fairness work is tracked in [../plans/ENEMY_AI_PLAN.md](../plans/ENEMY_AI_PLAN.md). This sheet describes current code and does not claim live-play balance.

## Timing contract

Regular enemy decisions, warning timers, recovery timers, and enemy-owned projectile lifetimes advance with `enemy_dt` (`dt × enemy_time_scale`). Time Slow sets that scale to 0.5, so the whole enemy attack clock slows together. Hit-stop and pause do not advance an active combat step. Player dash and boost clocks remain on the player/world clock.

Most ranges below are source values before the attack-speed modifier. `sustained_cd_scale` uses `1 + (attack_mult − 1) / 2`, with `attack_mult` clamped to 0.6–1.6. The scale is therefore 0.8–1.3, and attack cooldowns are divided by it, so a listed cooldown becomes 0.77×–1.25× as long. Warning windows are not shortened by that modifier. Chaser lunge timers, Charger, Flyer, Swarmer, and Egg Sac timers do not use this scale.

Warnings are removed when their attack commits or is interrupted. Chaser, Charger, Flyer, Bomber, Tank, Sniper, Ranged, and Spitter each draw a windup telegraph beam (`TELEGRAPH_OWNER`) and remove it at launch or interruption. The Engineer's placement warning is state-driven (`EngineerWindup`) and adds no telegraph beam.

Enemies with an active Repulsor stun (`stun_until`, 1.5 s) are skipped by the regular update loop in `step.rs`. Their attack, movement, and recovery timers freeze for the length of the stun; they do not slow down.

## Regular roster

| Role | Movement and attack cycle | Current timing and target lock | Recovery, cap, or timeout |
| --- | --- | --- | --- |
| **Chaser** | Pursues with orbiting movement and projectile avoidance. Inside 80–240 units of the player it pauses, marks its lunge heading, then rushes on the committed heading. | 0.22s warning; heading is the player's position plus 0.22 s of player velocity, fixed at launch; active lunge lasts 0.28–0.38s; next lunge delay 1.4–2.0s. | No projectile volley. Lunge warning is removed at launch. Evasive steering is unavailable during windup and lunge. |
| **Ranged** | Backs off inside 140 units, closes beyond 220, and strafes between. Fires only inside 330 units. Its burst contains one or two shots. | 0.34s warning (beam length 390); lead factor 0.72 for the first shot and 0.66 for the follow-up shot. The two shots of a two-shot burst are separated by 0.18–0.26s. Shot speed 205 + 2.2 × wave; damage 6 + wave/3; lifetime 2.4s. | After the burst, reload is 1.65–2.0s and it relocates for 0.5–1.1s. Projectile avoidance has a per-role cooldown. |
| **Sniper** | Keeps a 300–520 unit comfort band: approaches beyond 520, backs off inside 300, and strafes between. Fires only when 90 < distance < 740. | 0.92s aim (`SNIPER_AIM_SECONDS`); the aim point stops updating for the last 0.26s (`SNIPER_LOCK_SECONDS`); the aim point is the player plus 0.32 s of player velocity. Beam is active for 0.12s, 11 units thick, damage 12 + wave/3. | 0.58s recovery (`SNIPER_RECOVER_SECONDS`) and 2.80–3.25s base reload. Avoidance is suppressed during the committed windup and available again in recovery. |
| **Bomber** | Keeps 130–250 units from the player: backs off inside 130, closes beyond 250, and orbits between. Fires only inside 360 units. | 0.60s warning. Landing point is the player plus 0.25 s of player velocity, clamped to the arena. The bomb has a 1.25s fuse and velocity `(landing − pos) / 1.25`, so it reaches the marked point. Bomb damage 14 + wave/3. | 2.8–3.3s base reload. Blast radius is 72 units (`BOMB_BLAST_RADIUS`). The floor ring that shows the blast is render-side and was not re-checked in this pass. |
| **Tank** | Advances behind heavy armor. Normally moves at 0.65× speed; within 220 units it pushes at 0.95× for 0.45–0.67s every 2.0–2.7s; it stops within 100 units. Marks one aimed cannon lane inside 150 units. | 0.48s warning. Aim point is 220 units along a direction led with projectile speed 185 and a flight-time multiplier of 0.6 (this is not a 0.6 s lead). Projectile speed 185, damage 12, lifetime 2.8s. | 1.9–2.2s base reload. |
| **Charger** | Repositions (inverse-linear separation from nearby enemies) until it is within 200 units, locks a predicted direction, then charges straight. | 0.50s warning; aim point uses half the flight-time lead. Charge speed is 3× base; committed target and direction are captured at launch. | Charge is capped at 1.15s and ends early when within 30 units of the aim point or when its direction reverses. 1.0s cooldown while decelerating, then reposition. Warning is removed at launch. Charger has no projectile-evasion code path. |
| **Spitter** | Approaches beyond 200 units, backs off inside 120, and strafes between. Fires only inside 320 units. Alternates between a three-shot narrow fan and a four-shot wide fan. | 0.38s warning (beam length 350); lead uses projectile speed 210 and a 0.85 factor. Narrow volley: ±22°, speed 210, damage 6, lifetime 2.5s. Wide volley: ±40° and ±14°, speed 195, damage 5. | Narrow reload 1.4–1.7s; wide reload 1.75–2.10s. Avoidance is limited by the Spitter's own cooldown. |
| **Flyer** | Circles at about 150 units from the player (radial correction outside ±20 units), then darts across the committed line. | Circling 1.55–2.55s (2.05 ± 0.5); 0.45s warning; dash at 4× speed toward the point marked at windup start. | Returns to circling on reaching the point (within 20 units) or when the dash timeout ends. Timeout is the dash distance over dash speed, clamped to 0.18–1.35s (`FLYER_DASH_TIMEOUT_SECONDS`). Warning is removed at launch. |
| **Engineer** | Holds a 180–260 unit orbit (closes beyond 260, backs off inside 180). Fires inside 420 units. Places a mine where the player is predicted to be after 0.65s, with ±24 unit jitter, clamped to 86% of the arena radius. | 0.54s placement warning (state-driven, no beam). Mine: trigger radius 28, damage 16, armed after 0.7s, lifetime 10s. | Reload 2.9–3.5s base after a placed mine. The hostile trap cap is `MAX_ACTIVE_CONSTRUCTIONS` (14), counted over all traps in `state.traps`. If the cap is reached at commit, no windup starts; if it is reached at deployment, the mine is dropped. Either case retries after 0.85s. |
| **Swarmer** | Three persistent spawn-keyed subgroups follow independent, staggered Encircle → Surge Telegraph → Surge → Regroup cycles. Fighters flock only with their own subgroup and retain a stable subgroup/lane key. Lane depth increases every eight lanes (`lane / 8`). | Encircle 1.8–2.5s; surge telegraph 0.30s; surge 1.05–1.40s; regroup 1.15–1.60s. All mode clocks advance on enemy time. | The 0.30s floor ring and model tint use the same subgroup state and remaining-time fraction as the upcoming dive (render-side; not re-checked in this pass). Mixed-role body clearance remains active. Crowd-motion and final visual review remain pending; subgroup splitting is implemented, not an open E07 item. |
| **Egg Sac** | Stationary until its hatch timer runs out, then commits up to three Swarmers. | Regular sac timer is 4s (`hatch_timer`). Brood Matriarch sacs use 4s in phase I and 3s in later phases (`bosses.rs`). | Hatch count is `min(3, cap − live non-boss − queued non-boss)`. Each child searches up to 16 clamped, separated positions; if none is available, a clamped fallback is passed through the global body-clearance step. Death before the deadline cancels the hatch, because dead enemies are skipped by the update loop. Once hatch or summon children are queued and admitted under the cap, they are independent and survive a later owner's death. Full-capacity and owner-death cases have no test name in the suite (see Evidence limits). |

## Shared behavior rules

- Projectile evasion is a 0.16s dodge with a role-specific rest period before the next dodge: Chaser 0.58s, Flyer 0.52s, Ranged 0.72s, Spitter 0.76s, Sniper 0.92s, and Tank 1.15s. Unknown regular roles use 0.82s. The timers follow enemy time. Evasion is evaluated only in movement states: Sniper in its idle and recovery states, Chaser outside its lunge, Flyer while circling. Charger has no evasion path.
- Swarm surge preparation is a subgroup-level 0.30s warning. Only that subgroup tightens its orbit during the tell; the other two keep their own staggered modes. The floor ring, tint ramp, and movement transition all read the shared `SwarmBrain` timer.
- Attack scheduler: the committed weight allowed in flight at once is 1 while a boss is alive, 3 with 12 or more live regulars, 2 with 5–11 live regulars, and 1 otherwise. Starts of the same role are spaced by 0.20s (0.28s while a boss is alive). A request denied for 1.6s can be forced through the budget and stagger: at most one forced bypass per simulation step, and at least 0.35s after the previous forced start.
- Heavy regular commitments reserve two scheduler slots for the whole windup: Charger, Spitter, and the Sniper's aimed beam request weight 2. The same weight is kept on each following simulation step while the commitment is active.
- Sniper, Charger, and Flyer stop evasion when their attack is committed. Chaser also stops evasion during its lunge windup and active lunge. Other ranged roles can react only while their behavior is in a movement state.
- Repulsor stun and boss phase transitions both call `cancel_attack_for_interrupt`. It removes the active warning beam, clears committed movement and leftover volley or burst state, and raises the attack cooldown to at least the recovery value: 0.65s for the Repulsor, `BOSS_PHASE_RECOVERY_SECONDS` for boss phases.
- Boost ram damage is limited to one hit per target every 0.45s (`boost_ram_ready_at`, world time). While the player is boosting, a stunned normal enemy deals no boost-contact damage. Boss contact keeps its own boss contact damage path.
- Role formation slots are assigned once per role lane and kept in `formation_slot` (steer.rs); a vacancy is reused. Swarmers, Egg Sacs, and summoned adds stay outside these role formations.

## Sources

- `plouto_rs/src/sim/behaviors.rs`
- `plouto_rs/src/sim/enemy.rs`
- `plouto_rs/src/sim/step.rs`
- `plouto_rs/src/sim/steer.rs`
- `plouto_rs/src/sim/config.rs`
- `plouto_rs/src/sim/bosses.rs`
- `plouto_rs/src/render/world.rs`, `plouto_rs/src/render/models3d.rs`, `plouto_rs/src/ui/screens.rs` (render and UI claims; not re-checked on 2026-11-17)

## Evidence limits

The 2026-11-17 pass re-read the simulation sources listed above and corrected the values noted in the change log. Render and UI claims (floor rings, tint ramps, reduced motion) were not re-checked.

The latest full `cargo test -p plouto_rs` run passes 155 tests, with one adapter-dependent GPU check ignored. AI coverage includes ten `ai_core` contracts, the matched-seed `ai_fairness` diagnostic, regular-enemy and elite scenarios, squad movement, and the new wave/event schedule tests. Render tests check model geometry and poses, not final GPU presentation.

The moving-orbit fairness harness still produces too few projectile hits for a stable Easy/Hard accuracy estimate; its stationary-target numbers are diagnostic only. The current suite also does not exhaustively validate every role across all authored waves and every combination of buffs, arena events, and squad sizes. No human play-testing or final GPU review has been done.

## Change log (2026-11-17 check)

- Added the "Last checked" line and the link to `../plans/ENEMY_AI_PLAN.md`.
- Swarmer: "lane depth increases every eight slots" corrected to every eight lanes. `swarm_formation_key` returns `(slot % 3, slot / 3)`, and the ring depth uses `lane / 8`, so the step is every 24 spawn slots.
- Ranged: the 0.78 follow-up lead factor is not reachable for a burst of at most two shots, so only 0.66 is listed for the follow-up.
- Evidence limits: replaced "no simulation test suite" and the `cargo check --workspace --bin plouto` statement with the current test facts.
- Bomber: "kites around a target point" corrected to the 130–250 unit distance band. Added the 360 unit gate, bomb damage, and 72 unit blast radius.
- Tank: "aim leads the player by 0.6s" corrected. The 0.6 value is a flight-time multiplier in `lead_dir`. Added the brace and push cycle.
- Ranged: "burst gaps 0.16–0.24s" corrected. The gap between the two shots of a two-shot burst is 0.18–0.26s; the 0.16–0.24s branch is not reached by a burst of at most two shots. Added the fire range and projectile values.
- Engineer: the warning is state-driven and has no telegraph beam. Added the armed delay, the trap cap detail (counts all hostile traps), and the retry rules.
- Charger: has no projectile-evasion path. The charge ends within 30 units of the aim point (not "at target").
- Sniper, Spitter, Chaser, Flyer: added range gates, lead values, and damage or speed values that the sheet did not state.
- Timing contract: added the Time Slow factor (0.5), the attack-speed scale range (0.8–1.3, giving 0.77×–1.25× cooldowns), the list of timers that bypass that scale, and the freeze of stunned enemies.
- Shared rules: added the attack scheduler capacity, stagger, and forced-grant rules. Corrected the evasion description (Charger has none; Sniper and Flyer evade only in movement states). Corrected the boost-ram rule to the boost-contact path only. Named the interrupt cleanup values (0.65s and `BOSS_PHASE_RECOVERY_SECONDS`).
- Egg Sac: the hatch count formula is now stated. Dead sacs are skipped by the update loop, which is why death cancels the hatch.
- Unchanged after checking: Chaser lunge timers, Sniper aim/lock/recover timings, Spitter volleys, Flyer timings, swarm mode timers, egg sac timers, the 0.16s evasion window and rest values, and the 0.30s surge telegraph.
