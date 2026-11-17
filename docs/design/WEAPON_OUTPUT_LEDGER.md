# Rust Weapon Output Ledger

**Prepared:** 2026-11-16  
**Last checked against code: 2026-11-17**  
**Evidence type:** Formula-derived from the current Rust source. These are nominal outputs before hit probability, enemy armor, ward reduction, upgrades, and travel time. The 2026-11-17 pass re-read `weapons.rs`, `projectile.rs`, `step.rs`, `config.rs`, and `powerup.rs`. No runtime damage sample or gameplay test is claimed.

## Calculation rules

At the default player damage of 10, each projectile's uncritical base damage is:

`floor(weapon.damage + PLAYER_DAMAGE × 0.5 + 0.5)`

This is `compute_player_raw_damage` in `projectile.rs` with base player damage 10. Player damage upgrades scale it by `base_player_damage / 10` and by a separate damage multiplier, which this ledger leaves out.

The weapon's crit check is rolled once per trigger. A successful crit multiplies the projectile's scaled damage by the weapon's crit multiplier and rounds it, and every projectile in that trigger receives the same crit result. The nominal trigger interval is the weapon's base fire rate at default player fire rate. The game samples cadence jitter per shot (`cadence_jitter`). Heavy Cannon, Flak Battery, and Siege Mortar have hard minimum reloads of 0.70s, 0.85s, and 1.30s (`weapon_min_cooldown`).

## Primary weapons

| Weapon | Base projectile damage | Projectiles per trigger | Base interval | Full-connect payload before crit | Practical role and bounds |
| --- | ---: | ---: | ---: | ---: | --- |
| Basic Gun | 15 | 1 | 0.28s | 15 | Stable single-target baseline; 10% crit chance at 2×. |
| Heavy Cannon | 25 | 1 | 0.95s | 25 direct | 10% crit at 2×. Missile blast reaches 112 units. Each additional target in the blast receives 10–20 damage before armor when uncritical (20–40 when the shell is critical), excluding the direct target. Eight seconds is about 8.4 nominal reload slots. |
| Rapid Fire | 11 | 1 | 0.12s | 11 | Highest steady single-projectile cadence; 10% crit at 2×. Its speed is balanced around low per-shot output. |
| Hyper Railgun | 45 | 1 | 0.50s | 45 per target | 22% crit at 2.6×. Starts with three pierces, allowing up to four ordered target contacts per shot; four aligned targets would be 180 base damage per trigger. |
| Spread Shot | 13 | 3 | 0.35s | 39 if all connect | Pellet offsets are −30°, 0°, +30° (`spread_angle` 30). Designed for close targets or broad crowds; full-payload output falls quickly against small or distant targets. |
| Plasma Rifle | 14 | 3 | 0.26s | 42 if all connect | Pellet offsets are −20°, 0°, +20°. 15% crit chance at 2.1×; the central projectile keeps its aim lane useful against small targets. |
| Flak Battery | 16 | 3 | 1.10s | 48 direct if all connect | 14% crit at 1.85×. Pellets diverge at ±22°. Each shell has a 76-unit blast that deals 80% of the shell's damage with the same falloff, then releases four short-lived fragments (speed 340–460, lifetime 0.24–0.40s). A fragment deals 0.45 × the shell's final damage: 7 for an uncritical shell, about 14 for a critical one. At the configured three shells, the volley can release at most 12 fragments. Six seconds is about 5.5 nominal reload slots. |
| Siege Mortar | 37 | 1 | 1.45s | 37 direct; about 30–15 secondary splash | 12% crit at 2×. Ground-locks a 200–520-unit placement, measured from a muzzle 40 units ahead of the player, and travels at 260 units/s. Its 168-unit blast applies 80% damage with falloff from 100% at the enemy's edge to 50% at the blast edge. Homing and Ricochet do not redirect it. The five-second pickup gives about 3.4 nominal reload slots. |

## Useful comparisons

These are potential ceilings rather than observed damage rates:

- **Single target:** Rapid's raw full-connect cadence is 11 / 0.12 = 91.7 uncritical damage per second. Railgun is 45 / 0.50 = 90 before pierces. Basic Gun is 15 / 0.28 = 53.6.
- **Spread target:** Spread Shot's 39 / 0.35 = 111.4 and Plasma's 42 / 0.26 = 161.5 require all three projectiles to connect. These are area/alignment ceilings, not likely results against a small target.
- **Line targets:** Railgun's four-contact upper bound is 180 base damage each half-second, but only if four enemies occupy the swept path and are not removed by earlier effects.
- **Dense targets:** Heavy Cannon, Flak, and Siege Mortar add area output beyond their direct payload. Heavy offers a fast 112-unit missile blast; Flak covers three diverging shell paths and produces bounded fragments; Mortar trades long travel and deliberate floor placement for one larger 168-unit area hit.

## Temporary pod cadence

| Weapon class | Pickup duration | Nominal interval slots during duration |
| --- | ---: | ---: |
| Heavy Cannon | 8s | 8.4 |
| Flak Battery | 6s | 5.5 |
| Hyper Railgun | 12s | 24 |
| Plasma Rifle | 12s | 46.2 |
| Siege Mortar | 5s | 3.4 |
| Basic, Rapid, Spread | 20s | 71.4, 166.7, 57.1 respectively |

The number of complete triggers depends on acquisition time relative to the inherited reload deadline. Temporary swaps preserve that deadline, enforce the replacement weapon's minimum cadence from the last shot when necessary (`preserve_weapon_reload`), and restore the stored base weapon at expiry (`expire_weapon_pickup`).

## Scope limits and next measurement

- The formulas do not account for practical hit rate, target sizes, boss armor/phase, shields, enemy wards, player damage upgrades, permanent rewards, temporary rewards, mutators, or weapon-specific projectile travel.
- Mortar travel depends on target distance and arena-boundary projection. The count above is cadence slots, not a promise that every shell lands before the pickup expires; launched shells continue through their flight.
- Critical values are included in definitions but full-trigger expected values are intentionally omitted from the ceilings above; a volley shares one crit roll, so per-pellet independent-crit assumptions would be wrong.
- A future approved headless measurement should report sparse, aligned, and clustered targets, plus first-shot delay and observed complete volleys before expiry. That measurement is not claimed here.

## Evidence limits

The latest full `cargo test -p plouto_rs` run passes 155 tests, with one adapter-dependent GPU check ignored. `mortar_contract` checks Mortar reload, splash radius, visual lifetime, and temporary-pickup expiry; `powerup_contract` checks timed refresh, weapon replacement/restoration, Repulsor queueing, and Ultra caps. Existing cadence and explosive-splash checks remain in `sim_and_save`. This is not a complete observed-hit-rate table: no current test sweeps exact damage for every weapon across every upgrade, target size, and buff combination, and Mortar target-range clamping remains a focused follow-up.

## Sources

- `plouto_rs/src/sim/weapons.rs`
- `plouto_rs/src/sim/projectile.rs`
- `plouto_rs/src/sim/step.rs`
- `plouto_rs/src/sim/config.rs`
- `plouto_rs/src/sim/powerup.rs`
- `plouto_rs/src/sim/math.rs`
- `plouto_rs/src/render/world.rs` (not re-checked on 2026-11-17)

## Change log (2026-11-17 check)

- Heavy Cannon splash: the 10–20 figure is for uncritical shells. A critical shell gives 20–40, because splash is 80% of the shell's crit-scaled damage.
- Flak: the 7-damage fragment figure holds only for uncritical shells. Fragments take 0.45 × the shell's final damage, so a critical shell gives about 14. Added the shell blast and fragment speed and lifetime.
- Mortar: splash falloff is measured from the enemy's edge, not its center. Added that the placement is measured from a muzzle 40 units ahead of the player.
- Evidence limits: added the 2026-11-17 test facts and the test names that touch weapon output.
- Values checked and unchanged: all base damages (after the +5 at default damage), fire rates, pellet counts and offsets, crit chances and multipliers, pierce count, blast radii (112, 76, 168), Mortar speed (260), placement range (200–520), minimum reloads, and pod durations (8, 6, 12, 12, 5, 20 s).
