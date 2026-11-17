# Weapons, Power-ups, Elites, Boss Rage and Mutators

Every number here is read from the code file named in its section. Shot damage is for the base player damage, `PLAYER_DAMAGE` = 10, unless a row says otherwise.

## Weapons (weapons.py)

There are seven player weapons. `rank` sets the upgrade order: a weapon is equipped only when it outranks the weapon the player holds.

| Rank | Weapon (key) | Shot dmg | Crit dmg | Pellets (spread between neighbours) | Cooldown (s) | Speed (px/s) | Crit chance / mult | Pierce | Formula DPS |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | Basic Gun (`basic`) | 15 | 30 | 1 | 0.28 | 360 | 10% / 2.0 | 0 | 58.9 |
| 2 | Heavy Cannon (`heavy`) | 25 | 50 | 1 | 0.40 | 280 | 10% / 2.0 | 0 | 68.8 |
| 3 | Rapid Fire (`rapid`) | 11 | 22 | 1 | 0.12 | 340 | 10% / 2.0 | 0 | 100.8 |
| 4 | Hyper Railgun (`railgun`) | 45 | 117 | 1 | 0.50 | 780 | 22% / 2.6 | 3 | 121.7 |
| 5 | Spread Shot (`spread`) | 13 | 26 | 3 (30 deg) | 0.35 | 320 | 10% / 2.0 | 0 | 122.6 |
| 6 | Plasma Rifle (`plasma`) | 17 | 36 | 2 (20 deg) | 0.26 | 300 | 15% / 2.1 | 0 | 152.3 |
| 7 | Flak Battery (`flak`) | 16 | 30 | 3 (36 deg) | 0.35 | 340 | 14% / 1.85 | 0 | 153.5 |

- Formula DPS is the expected single-target DPS from the comment in weapons.py: `(damage + 5) * pellets * (1 + crit_chance * (crit_mult - 1)) / cooldown`, at base damage. Read in order, the ranks give ascending DPS.
- `spread` is the angle between neighbouring pellets. Pellets sit at offsets `(i - pellets / 2 + 0.5) * spread`, so Spread Shot fires at -30, 0 and +30 degrees.
- Rapid Fire has `spread_angle` 5 in its definition, but with one pellet that offset is always 0.
- The run starts with the Basic Gun (`get_weapon_for_wave(1)`).

## Damage (projectile.py, game.py, rpg.py)

- Player damage starts at 10. Each Damage power-up adds 1, and each permanent Core Damage reward adds 1. The temporary Overdrive reward multiplies it by 1.28, and Glass Cannon multiplies it by 1.5.
- Effective player damage is `floor(damage * Overdrive * Glass Cannon + 0.5)`. It is the `base_damage` passed to `spawn_projectiles`.
- Shot damage per pellet is `floor((weapon damage + 0.5 * PLAYER_DAMAGE) * base / PLAYER_DAMAGE + 0.5)`. At base 10 this is weapon damage + 5.
- Crit: one roll per volley, so every pellet of a volley is a crit or none is. Chance is the weapon's crit chance plus run bonuses, capped at 0.85. Crit damage is `round(shot damage * (crit mult + bonus))`, at least 1.
- Crit bonuses: permanent Precision Calibration gives +0.10 chance and +0.4 mult. Temporary Targeting Optics gives +0.25 chance and +0.5 mult for 2 waves.
- Cooldown: `max(0.08, weapon cooldown * clamp(player fire rate / 0.28, 0.65, 1.65) ** 0.85)`, then multiplied by a random factor in `1 +/- cadence_jitter`.
- Recoil: each shot adds `recoil_kick` degrees, up to `recoil_max`. It recovers at `recoil_recover` degrees per second. Pellets are jittered by the current recoil angle.
- Pierce: each enemy hit uses one pierce. The shot is removed on a hit when no pierce is left, so the railgun damages up to four enemies along its path.

## Weapon pools and upgrades (weapons.py, states.py, level.py)

| Waves | Pool (relative weights) |
| --- | --- |
| 1-2 | Basic (1.0) |
| 3-4 | Basic (0.50), Rapid (0.25), Spread (0.25) |
| 5-6 | Rapid (0.30), Spread (0.25), Plasma (0.25) |
| 7 and up | Spread (0.22), Plasma (0.22), Heavy (0.18), Railgun (0.18), Flak (0.20) |

- Flak is held back until wave 7, because as the top rank it could never be replaced.
- Wave clear: a 50% roll (`WEAPON_WAVE_UPGRADE_CHANCE`) draws from the pool for the next wave. The weapon is equipped only if it outranks the current one.
- Weapon pickups from ordinary drops (wave 3 and up) draw from the current wave's pool. If the weapon does not outrank the current one, the pickup gives +20 shield instead.
- Boss drop: always one weapon pickup, drawn from pool weapons that outrank the current weapon for the next wave. If none does, the highest-ranked pool weapon drops, and as a non-upgrade it gives +20 shield.

## Projectile looks (projectile_art.py)

Visual only. Physics and hit detection never read these values.

| Weapon | Head colour (RGB) | Head radius (px) | Trail | Impact |
| --- | --- | --- | --- | --- |
| Basic Gun | 255, 235, 120 (yellow) | 3.0 | tracer | tracer |
| Spread Shot | 255, 215, 225 (pale pink) | 2.4 | dots | pellet |
| Rapid Fire | 200, 255, 140 (lime) | 2.2 | dashes | dash |
| Heavy Cannon | 255, 190, 70 (orange) | 6.0 | slug | slug |
| Plasma Rifle | 175, 110, 255 (violet) | 4.5 | orb | orb |
| Hyper Railgun | 120, 245, 255 (cyan) | 3.6 | streak, 60 px | rail |
| Flak Battery | 205, 210, 220 (grey) | 4.2 | shell | flak burst |

- Crit shots have a gold trail (255, 212, 64) whatever the weapon.
- Enemy shots have a red-orange head (255, 85, 45) and trail, so they never read as player fire.
- Flak: a flak shot fires 3 pellets. When a flak shot ends, by a hit or by its time running out, it bursts into four shrapnel shots at 0, 90, 180 and 270 degrees (each +/- 20). Shrapnel moves at 340 to 460 px/s, deals 45% of the shot's damage (at least 1), and lives 0.24 to 0.40 s.

## Power-ups (powerup.py, level.py, config.py)

Drops and kinds:

- Wave clear: 33% chance of a drop at the arena centre. Each kill: 15%. Both chances are multiplied by the difficulty factor (Easy 1.15, Normal 1.0, Hard 0.9).
- Each drop rolls once more for its kind, with one value `r`:
  - `r < 0.07`: boost
  - `r < 0.13`: vortex
  - from wave 3, `r < 0.20`: weapon
  - from wave 3, `r < 0.23`: drone
  - otherwise a weighted pool: heal, damage, speed, firerate, shield, laser and boost at 1.0 each, magnet 0.5, ricochet 0.5, homing 0.3, time_slow 0.2.
- Ultra is forced on a wave clear once 4 or more waves have passed since the last Ultra (from wave 4). On a kill it is forced after 30 kills since the last Ultra (from wave 4). Otherwise it has a chance: 0.03 + 0.004 per wave above 4, capped at 0.20, on a wave clear, and 1.5% per kill.
- Boss loot: always one weapon pickup, plus one of heal, shield or laser. From wave 4, an Ultra is guaranteed if at least 4 waves have passed since the last one. There is a 35% chance of one more drop: 8% vortex, from wave 5 a further 22% Ultra, and otherwise damage, speed or firerate.
- Rare tier (rare pickup sound and ring): ultra, weapon, vortex, laser, drone, homing and time_slow.
- Iron Man turns every pickup off, boss loot included.

| Kind | Glyph | Effect | Duration |
| --- | --- | --- | --- |
| heal | + | +25 HP, capped at max HP | instant |
| damage | ! | +1 player damage | run |
| speed | > | +18 move speed | run |
| firerate | * | fire-rate value -0.03 s, never below 0.16 s | run |
| shield | O | +45 shield, cap 120 (`SHIELD_MAX`) | instant |
| laser | = | beams replace bullets, each dealing `int(0.9 * effective player damage) + 14` (23 at base) | 8 s |
| vortex | @ | 70 px aura that deals 38 damage per second to enemies inside | 10 s |
| weapon | W | equips the weapon if it is an upgrade, otherwise +20 shield | instant |
| ultra | U | +1 Ultra charge, up to the cap | instant |
| boost | B | refills boost energy, infinite boost, +20 shield | 6 s |
| drone | D | companion that fires basic-gun shots at the nearest enemy within 300 px of the drone | 12 s |
| ricochet | <> | each bullet bounces once off the arena edge | 8 s |
| homing | H | bullets steer to the nearest live enemy within 260 px, at up to 2.4 rad/s | 6 s |
| time_slow | ~ | enemies and enemy shots run at 0.5x; the player does not | 4 s |
| magnet | M | pickup radius x3, pull speed x1.5 | 10 s |

- Timed power-ups refresh their timer when picked up again. They never stack.
- Drone: one drone at a time, orbiting at 40 px. Its shots are ordinary player bullets, with the player's damage and crit rolls.

Ultra (`ultra` pickup, RMB or Q):

- A run starts with 0 charges. The cap starts at 2 (`ULTRA_MAX_CHARGES`). Each permanent Ultra+ reward raises it by 1, up to 4.
- Cooldown is 10 s, multiplied by 0.7 while Ultra Flux is active.
- Damage is `int(55 + 2.7 * effective player damage)`, which is 82 at base damage.
- Variants cycle in order on each use: Beam (a piercing line at full damage), Tri-Beam (three beams 16 degrees apart at 72% damage each), then Shockwave (a 160 px blast at 58% damage and a forward beam at 62%).

## Elite affixes (level.py, states.py, config.py)

- Spawn: from wave 3 (`ELITE_SPAWN_BASE_WAVE`), never on bosses. The chance is 14% at wave 3, plus 1.5% per wave after that, capped at 35%.
- An elite has 2.2x HP (`ELITE_HP_MULT`) and gives 2.5x score (`ELITE_SCORE_MULT`).
- Each elite gets one affix, chosen by weight: Volatile 3, Swift 3, Shielded 3, Splitter 2, Reflector 2. All five are available from wave 3.
- Volatile: on death, a 130 px blast deals 45 damage to enemies inside it. It also deals 20 damage to the player if the player is inside (fixed in states.py, not in config). Screen shake 14.
- Swift: speed x1.30.
- Shielded: a shield of 40% of the elite's HP. Shield takes damage before HP.
- Splitter: on death, 2 copies (`ELITE_SPLIT_COUNT`) appear 26 px around the death spot. Each has 50% of the elite's max HP (`ELITE_SPLIT_HP_FRAC`) and no affix, so a copy never splits again.
- Reflector: the first player shot in each 3.0 s window (`ELITE_REFLECT_COOLDOWN`) is sent back at the player at 260 px/s (`ELITE_REFLECT_SPEED`), dealing the shot's damage. The reflector takes no damage from that shot.

## Bosses and boss rage (enemy.py, boss_rage.py, logic.py)

Bosses arrive every fifth wave (`BOSS_WAVE_EVERY`). Scheduled bosses, with HP at normal difficulty on their first wave:

| Wave | Boss | HP |
| --- | --- | --- |
| 5 | Thunder | 364 |
| 10 | Laser | 502 |
| 15 | Trapmaster | 771 |
| 20 | Swarm Queen | 863 |
| 25 | Brute | 1367 |
| 30 and up | Abyss Gaze or Womb Core, alternating | formula below |

- From wave 30, each boss wave has a 28% chance of a random pick from Trapmaster, Swarm Queen and Brute instead.
- HP is `(base + wave * gain) * difficulty boss HP * min(1.75, 1.14 + 0.007 * wave)`. Base and gain by boss: Thunder 150 / 32, Laser 135 / 28, Trapmaster 170 / 30, Swarm Queen 155 / 26, Brute 190 / 34, Abyss Gaze 210 / 32, Womb Core 240 / 36.
- Phases: a boss is in phase 2 at 66% HP or less, and in phase 3 at 33% HP or less. A phase change cuts the current attack cooldown to at most 0.35 s.
- Personality: each boss picks aggressive, cautious or trickster from its own seed.

Boss rage (boss_rage.py):

- Once per boss, the first time its HP is at or below 35% of max (`RAGE_HP_FRACTION`), it enters rage.
- Entering rage multiplies the boss's pending attack cooldown by 0.75. While raged, the boss's attack cooldowns are 0.75 of their normal length, and each volley gets one extra projectile, beam or pulse (`RAGE_EXTRA_SHOTS`).
- The player sees a "BOSS RAGE" banner with the boss name and "ATTACKS QUICKEN", and hears the `rage_warn` cue.
- Boss kill: a camera-style flash and the victory fanfare play, and the boss drops loot. The boss reward screen opens after the boss wave is cleared, not on the kill.
- The rage constants live in boss_rage.py. config.py has `BOSS_RAGE_HP_FRAC`, `BOSS_RAGE_COOLDOWN_MULT` and `BOSS_RAGE_EXTRA_PROJECTILES` with the same values, but only the Guide reads them.

## Mutators (mutators.py)

Opt-in run modifiers. Click a chip on the title screen to toggle one. The chosen set is saved under `mutators` in `user_settings.json`. Each run plays with the set chosen when it starts. A daily run uses exactly one mutator instead.

| Mutator (id) | Rule | Score x |
| --- | --- | --- |
| Glass Cannon (`glass_cannon`) | Outgoing player damage x1.5. Max HP x0.6 (100 becomes 60). | 1.25 |
| Bullet Hell (`bullet_hell`) | Enemy shots fly 1.25x as fast. Every volley gains one extra shot. A lone shot gets its extra shot 12 degrees to one side. | 1.20 |
| Drift (`drift`) | Steering eases in at rate 5 per second and slides out at rate 2.4 per second. | 1.10 |
| Frenzy (`frenzy`) | Enemy speed x1.2. Regular waves (not bosses) have 1.25x the head count, still within the wave cap. | 1.30 |
| Iron Man (`iron_man`) | No pickups at all. Shield recharges at 2.0 points per second. | 1.15 |

- The score multiplier of a run is the product of its mutators' multipliers. The Game Over screen shows it.
- Stock rules are the default. Apart from the score multiplier, a mutator only changes `RunRules` values. They are set once when the run starts, and the game reads them from then on.
