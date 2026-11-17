# Level Design, Arena Events, and Difficulty Calibration

**Prepared:** 2026-11-16  
**Last checked against code: 2026-11-17**  
**Evidence type:** Rust source audit (`plouto_rs/src/sim/`) and formula-derived projections. The game was not launched, no play test was run, and no tests were run in this pass. Numbers below are what the source computes; they are not measured difficulty.

## Encounter direction

The Rust game uses open arenas. The arena shape is one of four map types (`circle`, `donut`, `cross`, `diamond`, `sim/config.rs`). Enemy arrivals come from legal arena-edge positions, collision spacing and role-driven movement. A new spawn tries up to 36 edge candidates and takes the first one that clears other enemies and the player by a minimum gap; if none does, it takes the best candidate found.

There are no solid obstacles in a normal run. The obstacle code path in `sim/step.rs` runs only when `RuntimeConfig.enable_obstacles` is true. That flag defaults to `false` (`sim/config.rs`), and `save/settings.rs` sets it to `false`.

The wave director teaches close pressure, ranged angles, explosives, swarm movement, control units, heavy frames, flank pressure and marksmen in a staged sequence. Every fifth wave is a boss-only encounter.

### Authored wave templates: waves 1–20

The director chooses the following class combinations for the first twenty waves. Within a selected class, member selection and counts remain seeded and deterministic. A fixed, unlock-aware fallback order keeps a future missing or relocked class from producing an undersized encounter.

The number of distinct classes per wave is capped: wave 1 allows one class, waves 2–6 allow two, and wave 7 onward allows three. Any class in a template beyond that cap is not used. This is why wave 6 has two classes, not three.

| Wave | Composition | Learning or recombination intent |
| ---: | --- | --- |
| 1 | Frontline | Establish movement and close pressure. |
| 2 | Frontline + gunline | Add a readable aimed shot while retaining a familiar pursuer. |
| 3 | Frontline + explosive | Introduce a delayed blast marker and a clear escape decision. |
| 4 | Frontline + swarmers | Add a fast group that rewards lane changes. |
| 5 | Boss: Storm Sovereign | First boss sequence; event hazards remain disabled. |
| 6 | Frontline + control | Introduce engineering support beside the close pursuer. The gunline class from the template is not used at this wave (two-class cap). |
| 7 | Frontline + bruisers + gunline | Add a durable body and keep a ranged lane visible. |
| 8 | Frontline + marksmen + explosive | Teach the lock reticle alongside the known blast cue. |
| 9 | Frontline + pressure + swarmers | Combine flank angles with a familiar fast group. |
| 10 | Boss: Prisma Overlord | Second boss sequence; no arena event overlap. |
| 11 | Frontline + control + pressure | Reuse control units while changing the secondary flank source. |
| 12 | Frontline + bruisers + gunline | Recombine heavy bodies and ranged fire. |
| 13 | Frontline + marksmen + swarmers | Contrast a fixed lock with fast orbiting pressure. |
| 14 | Frontline + control + explosive | Place delayed floor denial beside support behavior. |
| 15 | Boss: Forge Warden | Third boss sequence; spike markers remain the only arena-wide floor pattern. |
| 16 | Frontline + bruisers + swarmers | Combine slow mass with orbiting close pressure. |
| 17 | Frontline + marksmen + pressure | Ask players to cross between a lock lane and flank approach. |
| 18 | Frontline + control + explosive | Reuse support and delayed area damage with more bodies. |
| 19 | Frontline + gunline + pressure | Recombine two ranged angles around close pressure. |
| 20 | Boss: Brood Matriarch | Fourth boss sequence; summons obey the shared non-boss cap. |

The class choices are stable; the number and specific member within a class can vary by seed. The `pressure` class may produce a Spitter or Flyer, and the `frontline` class may produce a Chaser or Charger. Those variants retain the same family lane but should continue to receive distinct art, telegraphs, and guide descriptions.

### Post-wave-20 composition

After wave 20 the director stops using authored templates. Each wave:

1. Adds a frontline class.
2. From wave 7 on, adds one gunline or pressure class, chosen at random between the two.
3. Fills the remaining class slots (three in total from wave 7) by weighted choice from the unlocked classes.

Total population is capped by difficulty plus the wave-cap progression (see the formula section below).

### Boss schedule

| Wave | Boss | Behavior id |
| ---: | --- | --- |
| 5 | Storm Sovereign | `boss_thunder` |
| 10 | Prisma Overlord | `boss_laser` |
| 15 | Forge Warden | `boss_trapmaster` |
| 20 | Brood Matriarch | `boss_swarmqueen` |
| 25 | Gorgon Juggernaut | `boss_brute` |

From wave 30, the boss index is `wave / 5 − 1`. The late pool rotates through Ocular Abyss (`boss_abyss_gaze`), Origin Nexus (`boss_womb_core`) and Eclipse Archon (`boss_eclipse_archon`), using index `(wave / 5 − 6) mod 3`. Wave 40 is always Eclipse Archon, which is its debut. On every other wave from 30 on, there is a 28% chance that the boss is instead Forge Warden, Brood Matriarch or Gorgon Juggernaut.

## Difficulty matrix

### Source modifiers

| Setting | Easy | Normal | Hard |
| --- | ---: | ---: | ---: |
| Spawn-count multiplier | 0.85× | 1.00× | 1.12× |
| Regular-enemy HP multiplier | 0.88× | 1.00× | 1.16× |
| Movement-speed multiplier | 0.92× | 1.00× | 1.08× |
| Power-up chance multiplier | 1.15× | 1.00× | 0.90× |
| Boss HP multiplier | 0.92× | 1.00× | 1.08× |
| Dash cooldown multiplier | 0.90× | 1.00× | 1.12× |
| Base live-enemy cap | 10 | 12 | 14 |

Effects in the code:

- The dash cooldown is `1.5 s` (`DASH_COOLDOWN`) times the difficulty multiplier and a progression modifier (`sim/player.rs`). On Normal the base is 1.5 s; on Easy 1.35 s; on Hard 1.68 s.
- Wave power-up chance is `0.33 ×` the power-up multiplier. Kill drop chance is `0.15 ×` the same multiplier.
- The regular-enemy HP multiplier also scales boss attack damage (`sim/bosses.rs`, `boss_damage`). It does not change boss health.

### Regular enemy stats

Regular enemy health and speed are computed in `sim/level.rs` (`enemy_stats`):

- Health = `(22 + 5 × wave + HP offset) × HP multiplier × difficulty HP multiplier`. Swarm uses `(22 + 5 × wave) × 0.5`, with a floor of 8.
- Speed = `(55 + 2 × wave) × speed multiplier × difficulty speed multiplier × run-rule speed multiplier`.
- Attack multiplier divides the spawn-time attack cooldown roll, clamped to 0.6–1.6 at spawn.

| Role | HP offset | HP × | Speed × | Attack × |
| --- | ---: | ---: | ---: | ---: |
| Chaser | 0 | 1.00 | 1.32 | 1.00 |
| Bomber | −8 | 1.00 | 1.20 | 1.00 |
| Ranged | −5 | 1.00 | 0.85 | 1.20 |
| Charger | +10 | 1.00 | 1.05 | 0.80 |
| Swarm | (×0.5 applied first) | 0.50 | 1.45 | 0.50 |
| Tank | 0 | 2.00 | 0.55 | 0.90 |
| Spitter | −3 | 1.00 | 0.90 | 1.50 |
| Flyer | −7 | 1.00 | 1.55 | 0.70 |
| Engineer | +6 | 1.00 | 0.75 | 1.10 |
| Sniper | −10 | 1.00 | 0.78 | 1.15 |

Example, Normal difficulty, wave 10: Chaser has 72 HP and speed 99; Tank has 144 HP and speed 41.

Spawn-time attack cooldown ranges (seconds): regular roles 0.2–1.0; Engineer 0.6–1.4; Sniper 1.0–1.8; bosses 0.6–1.6.

### Elite enemies

Elites start at wave 3 (`ELITE_SPAWN_BASE_WAVE`). The chance per spawned non-boss enemy is `0.14 + 0.015 × (wave − 3)`, capped at 0.35. An elite has 2.2× HP. Its affix is chosen by weight from volatile, swift, shielded, splitter, reflector, mender and warden. Swift multiplies speed by 1.30. Shielded adds a shield equal to 40% of its (already multiplied) HP.

### Boss stats

Boss health is `(base + wave × gain) × boss HP multiplier × growth`, where `growth = min(1.14 + 0.007 × wave, 1.75)`.

| Boss | Base HP | Gain per wave |
| --- | ---: | ---: |
| Storm Sovereign | 150 | 32 |
| Prisma Overlord | 135 | 28 |
| Forge Warden | 170 | 30 |
| Brood Matriarch | 155 | 26 |
| Gorgon Juggernaut | 190 | 34 |
| Ocular Abyss | 210 | 32 |
| Origin Nexus | 240 | 36 |
| Eclipse Archon | 225 | 34 |

Example, Storm Sovereign, wave 5, Normal: `(150 + 5 × 32) × 1.00 × 1.175 = 364` HP.

### Formula samples

The raw non-boss count is `4 + floor(1.4 × wave)`. It is multiplied by the spawn multiplier and the run-size multiplier, truncated to an integer, and limited by the wave cap. The wave cap is the base live-enemy cap plus one enemy every three waves after wave 5, up to eight additions. The run-size multiplier is 1.0 by default; the `frenzy` mutator sets it to 1.25 (`sim/mutators.rs`).

| Wave | Raw base count | Easy projected count | Normal projected count | Hard projected count | Note |
| ---: | ---: | ---: | ---: | ---: | --- |
| 1 | 5 | 4 | 5 | 5 | First encounter; no cap pressure. |
| 4 | 9 | 7 | 9 | 10 | Each of the first four waves adds at most one new class. |
| 7 | 13 | 10 | 12 | 14 | Easy and Normal meet their live caps; Hard reaches its cap exactly. |
| 8 | 15 | 11 | 13 | 15 | Cap rises by one at wave 8. |
| 10 | 18 | 1 boss | 1 boss | 1 boss | Boss rounds bypass regular wave counts and arena events. |
| 19 | 30 | 14 | 16 | 18 | Uses the wave cap, not the raw count. |

Count projections assume the default run-size multiplier (1.0) and `max_enemies` values of 10/12/14. They do not estimate practical difficulty, clear time or survival probability.

## Arena events and escape budget

From wave 4 onward, each non-boss wave has a 1/3 chance of one arena event (`sim/events.rs`). If an event is chosen, one of the three kinds is picked with equal chance. Boss waves never get an event. Events do not overlap: one event slot exists, the event is created when the wave spawns, and it is removed when the wave clears.

| Event | Warning geometry and impact | Duration / escape affordance | Compatibility |
| --- | --- | --- | --- |
| Meteor Shower | Three impact circles, radius 38 units, each at least 90 units from the others and placed within 0.7 of the arena radius. Each warning is drawn from the same centers and radius used by damage. | 1.5-second warning per impact, staggered by 0.7 seconds. The impact stays live for 0.25 seconds. Damage is 16 to the player and to enemies inside a circle. Enemy roles ranged, sniper, spitter, flyer and engineer steer away from a zone during the final 0.8 seconds before impact. | Non-boss waves only; no simultaneous event. |
| Solar Flare | A 110° angular warning sweeps to the same live line segment and width used for damage. | 2.0-second warning followed by a 2.6-second sweep. Beam damage is 18, applied at most once every 0.5 seconds per target. | Non-boss waves only; no simultaneous event. |
| Nebula Cloud | Warning and active field share the same center and 110-unit radius used by enemy shield logic. Center lies within half the arena radius. | 1.0-second warning, then an 8-second field. Each enemy inside the field gains a 24-point shield; the shield is removed when the enemy leaves the field or the wave clears. | Non-boss waves only; no simultaneous event. |

There are no solid obstacles in a normal run. The escape budget comes from visible warning geometry, edge-safe event placement, role commitment spacing, bounded enemy overlap and the player's dash. Meteor, Flare and Nebula effects may coexist with regular enemy attacks, so event-plus-elite or event-plus-ranged density still requires approved scenario review. Boss/event combinations are not legal in the current director.

## Balance boundaries and remaining evidence

- Easy, Normal and Hard keep the same attack vocabulary and warning durations. Difficulty changes spawn pressure, health, movement speed, power-up chance, boss health, boss attack damage, dash cooldown and population cap.
- The current source does not scale the warning floors down on Hard. A future balance change should use spacing, recovery and enemy count before reducing warning time.
- Role class weights and the first twenty templates are source-defined. The exact run length produced by a real player, practical pickup availability, simultaneous threat load and boss clear timing are not measured here.
- A multi-seed comparison can now be run headless, since the project allows headless tests; none was run for this document. Visual readability still requires a human play-test, which has not been done.

## Source references

- `plouto_rs/src/sim/level.rs`: wave templates, class unlocks, count formula, difficulty modifiers, enemy and boss stats, elite chance, boss schedule and wave cap.
- `plouto_rs/src/sim/events.rs`: event selection, warning clocks, damage geometry, and event expiration.
- `plouto_rs/src/sim/config.rs`: difficulty-independent constants (event timings, enemy radii, elite constants, `DASH_COOLDOWN`, `BOSS_WAVE_EVERY`).
- `plouto_rs/src/sim/step.rs`: event creation and integration, wave cleanup, and enemy meteor avoidance.
- `plouto_rs/src/sim/bosses.rs`: boss damage scaling and boss summons.
- `plouto_rs/src/sim/mutators.rs`: `frenzy` run-size and speed multipliers.
- `plouto_rs/src/render/world.rs`: event warning and impact rendering.
