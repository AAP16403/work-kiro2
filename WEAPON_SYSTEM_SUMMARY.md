## Weapons, Loot, and Boss Combat - Summary

### Weapons (`weapons.py`)
- 5 weapon types: Basic, Spread Shot, Rapid Fire, Heavy Cannon, Plasma Rifle
- `spawn_weapon_projectiles()` spawns weapon-specific projectile patterns
- Wave-based weapon pools via `get_weapon_pool_for_wave()` / `get_weapon_key_for_wave()`
- Player fire-rate upgrades now modify weapon fire rate via `get_effective_fire_rate()`

### Weapon pickups (`powerup.py` / `level.py` / `visuals.py`)
- New powerup kind: `weapon` (stored as `PowerUp(kind="weapon", data="<weapon_key>")`)
- Bosses always drop a weapon pickup + at least one additional powerup (`spawn_loot_on_enemy_death()`)
- Weapon pickup visuals:
  - Glyph `W` (`visuals.py`)
  - Color mapping (`config.POWERUP_COLORS["weapon"]`)

### Ultra ability (`powerup.py` / `config.py` / `Untitled-1.py`)
- New powerup kind: `ultra` (glyph `U`) grants an Ultra charge
- Use Ultra with right-click; uses a high-damage beam and then goes on cooldown

### Boss upgrades (`enemy.py`)
- Bosses now use:
  - HP-based phases (3 phases)
  - A random “persona” that nudges spacing/attack cadence and pattern choices
  - Mixed bullet patterns (fans and rings) layered with their hazards

### Integration (`Untitled-1.py`)
- Loot spawning uses `level.spawn_loot_on_enemy_death()` for all enemy death paths (including boss deaths)
- Powerups have a light magnet-to-player pull and slightly larger pickup radius for weapon drops

### Sanity check
- `python -m py_compile` succeeds for all `*.py` modules
