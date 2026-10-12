"""Daily-run mutators: small fixed rule changes that the daily seed picks from.

Each mutator is a set of multipliers. A run applies the product of the multipliers of its mutator ids.
daily.py gives every daily run exactly one id, so the effect is always one rule and never a stack.

Public API:

    MUTATORS             dict id -> Mutator. daily.mutator_pool() reads its keys, sorted.
    Mods                 the combined multipliers a run applies (see the field comments).
    combined(ids) -> Mods
        Product of the multipliers for ids. An empty tuple gives the identity Mods() (no effect).
        Unknown ids raise KeyError, so a bad id fails loudly instead of being ignored.

Game hooks: player_damage in game._effective_player_damage, player_speed in
game._effective_player_speed, player_fire_rate in game._effective_player_fire_rate, and the enemy
fields in level.spawn_wave (HP, speed and attack cooldown of every wave enemy and wave boss).

Pure data with no pyglet or I/O, so it loads without a window.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Mods:
    """Combined multipliers for one run. 1.0 means no change."""

    player_damage: float = 1.0      # damage per shot
    player_speed: float = 1.0       # movement speed
    player_fire_rate: float = 1.0   # shots per second (a higher value fires faster)
    enemy_hp: float = 1.0           # HP of enemies spawned by a wave
    enemy_speed: float = 1.0        # movement speed of enemies spawned by a wave
    enemy_fire_rate: float = 1.0    # attack frequency of enemies spawned by a wave (a higher value attacks more often)


@dataclass(frozen=True)
class Mutator:
    """One daily rule. ``name`` and ``description`` are shown to the player."""

    id: str
    name: str
    description: str
    player_damage: float = 1.0
    player_speed: float = 1.0
    player_fire_rate: float = 1.0
    enemy_hp: float = 1.0
    enemy_speed: float = 1.0
    enemy_fire_rate: float = 1.0


MUTATORS: dict[str, Mutator] = {m.id: m for m in (
    Mutator("bullet_hell", "Bullet Hell", "Enemies attack 1.5x as often.", enemy_fire_rate=1.5),
    Mutator("drift", "Drift", "You move 1.25x faster.", player_speed=1.25),
    Mutator("frenzy", "Frenzy", "You fire 1.3x as fast and enemies move 1.2x faster.",
            player_fire_rate=1.3, enemy_speed=1.2),
    Mutator("glass_cannon", "Glass Cannon", "Your shots hit 1.5x harder.", player_damage=1.5),
    Mutator("iron_man", "Iron Man", "Enemies have 1.5x HP.", enemy_hp=1.5),
)}

_FIELDS = ("player_damage", "player_speed", "player_fire_rate", "enemy_hp", "enemy_speed", "enemy_fire_rate")


def combined(ids) -> Mods:
    """Multiply the multipliers of every id in ``ids``. Raises KeyError for an unknown id."""
    totals = {field: 1.0 for field in _FIELDS}
    for mutator_id in ids:
        mutator = MUTATORS[mutator_id]
        for field in _FIELDS:
            totals[field] *= getattr(mutator, field)
    return Mods(**totals)
