# Simulation Clock Inventory

**Prepared:** 2026-11-16  
**Last checked against code: 2026-11-17**  
**Scope:** Rust source re-check of `plouto_rs/src/sim/` (step.rs, behaviors.rs, bosses.rs, powerup.rs, specials.rs, weapons.rs, config.rs). No tests were run in the 2026-11-17 pass and no game was launched.

## Clock policy

| Clock | Owner | Advances when | Used for |
| --- | --- | --- | --- |
| `state.time` | Simulation/world | Each accepted simulation step; paused by hit-stop and screen pause | Player cooldown deadlines, pickup expiry, player-applied stun deadlines, run time, score timers and replay frames |
| `dt` | Simulation step | Accepted step delta, clamped to `1/30 s` | Player motion, input abilities, player projectiles, player hazards and pickup timers |
| `enemy_dt` | Enemy simulation step | `dt × enemy_time_scale`; the scale is `TIME_SLOW_SCALE` (0.5) while Time Slow is active and 1.0 otherwise. Not computed during hit-stop, because `step()` returns first | Delta used for enemy motion, attack/recovery timers, enemy projectiles and hazards, enemy-local animation clocks (`Enemy.t`), and elite reflect/mender timers |
| `state.enemy_time` | Accumulated enemy clock | Adds accepted `enemy_dt` each step; pauses during hit-stop and screens that do not step | Attack-start timestamps, same-role staggering, forced-attack spacing, and swarm subgroup clock comparisons |
| `visual_dt` | Presentation | Render/update cadence, independent of combat slowdown | Particle lifetime, UI fades, mender pulse fade, camera presentation and cosmetic transitions |
| `state.time` interpolation | Rendering | Fixed at the latest accepted simulation time | Gameplay model poses, warning progress, pickup countdowns and boss phase presentation |

`step()` returns before advancing any gameplay timer while hit-stop is active. The application does not call simulation steps while the run is paused or on non-gameplay screens.

## Ownership by system

### Player and pickups

- `ultra_cd_until`, `dash_cooldown`, timed pickup deadlines, temporary weapon expiry, and `RepulsorSystem.cooldown_until` are absolute `state.time` deadlines.
- Weapon fire scheduling uses `state.player.next_shot_time` against `state.time`. Temporary weapon swaps preserve the current reload deadline and enforce the new weapon's minimum interval.
- Player hit grace (`invincibility_timer`), Repulsor-applied enemy stun, boost-ram recontact interval, power-up expiry, pickup lifetime, combo decay, and wave-clear schedule also use accepted world `dt`/`state.time`. They do not slow with enemy AI.
- Healing, shield, damage, speed, and fire-rate pickups resolve immediately. Timed effects refresh their own deadline. Ultra and Repulsor add charges within their caps and convert overflow to another benefit.
- Time Slow reduces enemy time only. It does not lengthen the player's temporary pickups or pause the player's own weapon and ability timers.

### Regular enemies and bosses

- `Enemy.t`, `Enemy.attack_cd`, and `EnemyAi`'s `state_timer`, `sub_timer`, lunge timers, burst gaps, relocation, brace/push, hatch, forward-lock, dodge response/cooldown, reflect cooldown, mender heal cooldown, boss phase recovery, and beam ticks update with `enemy_dt`.
- `Enemy.t` also drives the Chaser's zig-zag steering, so that motion slows under Time Slow. The render-side idle oscillation uses the enemy's own elapsed clock (not re-checked in this pass).
- Enemies with an active stun (`stun_until > state.time`) are skipped by the regular update loop in `step()`. Every enemy-owned timer for a stunned enemy freezes until the stun ends. This is separate from the clock table above: the stun length itself is on world time.
- `attack_denied_t` accumulates `enemy_dt`. `last_attack_started_at` and `last_forced_attack_started_at` are timestamps on `state.enemy_time`; same-role stagger and forced-grant spacing therefore slow consistently with the attack sequences they schedule.
- `stun_until` and `boost_ram_ready_at` are absolute world-time deadlines by design: stun is applied by the player's ability, and the ram interval belongs to the player's boost contact.
- Boss phase and attack states use the same `enemy_dt` context. The shared phase recovery deadline is based on enemy time so a slow-time effect cannot silently consume a recovery window.
- Elite reflector and mender cooldowns use `enemy_dt`. The mender pulse's visible fade uses `visual_dt` because it is a presentation envelope, not a gameplay delay.
- Enemy projectile travel, fuse clocks, enemy traps, laser beams and thunder lines advance with `enemy_dt`.
- Meteor avoidance consumes the same enemy clock as the event warning. The player's meteor damage window remains on normal simulation time.

### Player weapons, hazards and score

- Player projectiles use `dt`; hostile projectiles use `enemy_dt`. Temporary weapon expiry and the firing schedule use player/world time, so Time Slow cannot extend a weapon pod or delay the player's shots.
- `Trap` and `ThunderLine` objects are hostile and use `enemy_dt`. Hostile and windup `LaserBeam` objects (owner `enemy` or `telegraph`) use `enemy_dt`; any other beam uses `dt`.
- `ChainArc`, `RepulsorRing`, `EchoRing`, and afterburn drop deadlines are measured against `state.time`. Their visible fade is presentation-only and does not extend their gameplay effect.
- Arena events, score-combo decay, run duration, and wave cooldown advance on world `dt`; event damage and event warning share the same world-time event state. Enemy meteor dodges react on enemy time to the remaining world-time warning.

### UI and model presentation

- HUD countdowns read the authoritative absolute deadline and current simulation time; active power-up rings use the duration from the shared power-up definition table.
- Enemy and boss poses receive a normalized attack progress derived from the active sub-state timer. Idle movement uses the enemy's own elapsed clock (see above). Reduced-motion mode removes idle oscillation while preserving attack/charge poses and warning geometry (render side; not re-checked in this pass).
- Menu animation, toast fade and comms animation use presentation delta. These do not advance cooldowns, alter replay state or change combat timing (render and UI side; not re-checked in this pass).

## Source changes and policy status

The 2026-11-16 source audit found no gameplay cooldown driven by render time. The two discovered exceptions, elite mender and reflector cooldowns, now decrement with `enemy_dt`. The audit also found that attack-start spacing used world-time timestamps even though attack denial and sequences use enemy time; scheduler timestamps now use accumulated `state.enemy_time`.

The 2026-11-17 re-check confirmed those two changes in code (`step.rs`: reflect cooldown decrement on `enemy_dt`, mender tick on `enemy_dt`; `behaviors.rs`: `AttackScheduler::request` uses `enemy_time`). It found no new gameplay clock that uses render time. It also added the stunned-enemy freeze and the `Enemy.t` zig-zag note above, which the 2026-11-16 inventory did not list.

If a future ability is intentionally exempt, its deadline should be named as a global player clock or presentation timer and recorded here. New enemy attack delays must use `enemy_dt`; UI should display the resulting authoritative remaining time rather than maintain a second countdown.

## Evidence limits

This is a static source inventory, re-checked on 2026-11-17 by reading source. Render and UI claims were not re-checked.

The latest full `cargo test -p plouto_rs` run passes 155 tests, with one adapter-dependent GPU check ignored. The `swarm_mode_clock_obeys_enemy_time_scale` check covers swarm movement under Time Slow; weapon and pickup contracts cover player cooldown/expiry paths. Regular-role and boss Time Slow permutations, hit-stop boundaries, pause behavior, stun freeze, and HUD countdown alignment are not exhaustively covered. Those are valid headless follow-ups; reduced-motion and on-screen countdown alignment still need visual review. No human play-testing has been done.
