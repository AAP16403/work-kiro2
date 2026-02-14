"""Game state and level management."""

import random
from dataclasses import dataclass, field
from typing import List

import config
from enemy import Enemy
from hazards import Trap, LaserBeam, ThunderLine
from layout import Obstacle
from projectile import Projectile
from powerup import PowerUp
from utils import Vec2, random_spawn_edge
from weapons import get_weapon_key_for_wave


@dataclass
class GameState:
    """Main game state."""
    time: float = 0.0
    wave: int = 1
    difficulty: str = "normal"
    layout_seed: int = 0
    layout_segment: int = 0
    obstacles: List[Obstacle] = field(default_factory=list)
    enemies: List[Enemy] = field(default_factory=list)
    projectiles: List[Projectile] = field(default_factory=list)
    powerups: List[PowerUp] = field(default_factory=list)
    traps: List[Trap] = field(default_factory=list)
    lasers: List[LaserBeam] = field(default_factory=list)
    thunders: List[ThunderLine] = field(default_factory=list)
    wave_active: bool = False
    last_wave_clear: float = 0.0
    shake: float = 0.0
    max_enemies: int = 12  # Limit concurrent enemies


def get_difficulty_mods(difficulty: str) -> dict:
    """Return difficulty multipliers for spawn rates and stats."""
    d = (difficulty or "normal").lower()
    if d == "easy":
        return {
            "spawn": 0.85,
            "hp": 0.88,
            "speed": 0.92,
            "powerup": 1.15,
            "boss_hp": 0.92,
        }
    if d == "hard":
        return {
            "spawn": 1.12,
            "hp": 1.16,
            "speed": 1.08,
            "powerup": 0.9,
            "boss_hp": 1.08,
        }
    return {
        "spawn": 1.0,
        "hp": 1.0,
        "speed": 1.0,
        "powerup": 1.0,
        "boss_hp": 1.0,
    }


def spawn_wave(state: GameState, center: Vec2):
    """Spawn a new wave of enemies with varied difficulty."""
    state.wave_active = True
    mods = get_difficulty_mods(state.difficulty)

    # Boss wave every 5 waves.
    if state.wave % 5 == 0:
        behavior_name = get_boss_for_wave(state.wave)
        hp, speed, _attack_mult = _get_enemy_stats(behavior_name, state.wave, state.difficulty)
        pos = random_spawn_edge(center, config.ROOM_RADIUS)
        e = Enemy(pos=pos, hp=hp, speed=speed, behavior=behavior_name)
        e.attack_cd = random.uniform(0.6, 1.6)
        state.enemies.append(e)
        return
    
    # Scale difficulty: ramp enemy count a bit more gradually (caps at max_enemies).
    base_count = 4 + int(state.wave * 1.4)
    base_count = max(1, int(base_count * mods["spawn"]))
    cap = state.max_enemies
    count = min(base_count, cap)
    
    # Enemy type distribution changes with waves
    for _ in range(count):
        behavior_name = _get_weighted_behavior(state.wave)
        hp, speed, attack_mult = _get_enemy_stats(behavior_name, state.wave, state.difficulty)
        pos = random_spawn_edge(center, config.ROOM_RADIUS)
        
        e = Enemy(pos=pos, hp=hp, speed=speed, behavior=behavior_name)

        if behavior_name == "engineer":
            e.attack_cd = random.uniform(0.6, 1.4)
        else:
            e.attack_cd = random.uniform(0.2, 1.0)
        state.enemies.append(e)


def _get_weighted_behavior(wave: int) -> str:
    """Get enemy behavior weighted by wave difficulty."""
    # Base trio stay common.
    pool: list[tuple[str, float]] = [
        ("chaser", max(3.0, 6.0 - wave * 0.12)),
        ("ranged", 3.0),
        ("charger", 2.8),
    ]

    # Add new enemy types on later waves; keep their weights modest so waves don't
    # randomly become "all flyers" or "all engineers".
    if wave >= 3:
        pool.append(("swarm", 2.0))
    if wave >= 4:
        pool.append(("engineer", 1.4))
    if wave >= 5:
        pool.append(("tank", 1.2))
    if wave >= 7:
        pool.append(("spitter", 1.6))
    if wave >= 9:
        pool.append(("flyer", 1.1))

    names = [n for n, _w in pool]
    weights = [max(0.1, float(w)) for _n, w in pool]
    return random.choices(names, weights=weights, k=1)[0]


def get_boss_for_wave(wave: int) -> str:
    bosses = ["boss_thunder", "boss_laser", "boss_trapmaster", "boss_swarmqueen", "boss_brute"]
    idx = (wave // 5 - 1) % len(bosses)
    return bosses[idx]


def _get_enemy_stats(behavior: str, wave: int, difficulty: str = "normal") -> tuple:
    """Get HP, speed, and attack multiplier for enemy type.
    
    Returns: (hp, speed, attack_mult)
    """
    mods = get_difficulty_mods(difficulty)
    base_hp = 22 + wave * 5
    base_speed = 55 + wave * 2

    if behavior == "chaser":
        hp, speed, atk = (base_hp, base_speed * 1.32, 1.0)
    elif behavior == "ranged":
        hp, speed, atk = (base_hp - 5, base_speed * 0.85, 1.2)
    elif behavior == "charger":
        hp, speed, atk = (base_hp + 10, base_speed * 1.05, 0.8)
    elif behavior == "swarm":
        # Many weak, fast enemies
        hp, speed, atk = (max(8, base_hp // 2), base_speed * 1.45, 0.5)
    elif behavior == "tank":
        # Slow but tanky
        hp, speed, atk = (base_hp * 2, base_speed * 0.55, 0.9)
    elif behavior == "spitter":
        # Medium stats, spreads fire
        hp, speed, atk = (base_hp - 3, base_speed * 0.9, 1.5)
    elif behavior == "flyer":
        # Erratic movement
        hp, speed, atk = (base_hp - 7, base_speed * 1.55, 0.7)
    elif behavior == "engineer":
        # Builds traps; slower, higher HP
        hp, speed, atk = (base_hp + 6, base_speed * 0.75, 1.1)
    elif behavior == "boss_thunder":
        hp, speed, atk = (150 + wave * 32, base_speed * 0.9, 1.8)
    elif behavior == "boss_laser":
        hp, speed, atk = (135 + wave * 28, base_speed * 1.1, 1.8)
    elif behavior == "boss_trapmaster":
        hp, speed, atk = (170 + wave * 30, base_speed * 0.85, 1.7)
    elif behavior == "boss_swarmqueen":
        hp, speed, atk = (155 + wave * 26, base_speed * 0.95, 1.7)
    elif behavior == "boss_brute":
        hp, speed, atk = (190 + wave * 34, base_speed * 1.05, 1.9)
    else:
        hp, speed, atk = (base_hp, base_speed, 1.0)

    is_boss = behavior.startswith("boss_")
    hp_mult = mods["boss_hp"] if is_boss else mods["hp"]
    hp = float(hp) * float(hp_mult)
    if is_boss:
        # Bosses need to stay relevant even as the player stacks upgrades.
        hp *= (1.25 + 0.01 * float(wave))
    hp = max(1, int(hp))
    speed = float(speed) * mods["speed"]
    return (hp, speed, atk)


def maybe_spawn_powerup(state: GameState, center: Vec2):
    """Randomly spawn a powerup."""
    mods = get_difficulty_mods(state.difficulty)
    chance = 0.33 * mods["powerup"]
    if random.random() < chance:
        kind = random.choice(["heal", "damage", "speed", "firerate", "shield", "laser"])
        if random.random() < 0.06:
            kind = "vortex"
        elif state.wave >= 4 and random.random() < 0.03:
            kind = "ultra"
        elif state.wave >= 3 and random.random() < 0.05:
            kind = "weapon"
        pos = random_spawn_edge(center, config.ROOM_RADIUS * 0.6)
        if kind == "weapon":
            state.powerups.append(PowerUp(pos, kind, data=get_weapon_key_for_wave(state.wave)))
        else:
            state.powerups.append(PowerUp(pos, kind))


def spawn_powerup_on_kill(state: GameState, center: Vec2):
    """Spawn a powerup when an enemy dies."""
    mods = get_difficulty_mods(state.difficulty)
    chance = 0.15 * mods["powerup"]
    if random.random() < chance:  # base 15% chance per kill
        kind = random.choice(["heal", "damage", "speed", "firerate", "shield", "laser"])
        if random.random() < 0.03:
            kind = "vortex"
        elif state.wave >= 4 and random.random() < 0.015:
            kind = "ultra"
        elif state.wave >= 4 and random.random() < 0.02:
            kind = "weapon"
        # Spawn near center
        pos = center + Vec2(random.uniform(-50, 50), random.uniform(-50, 50))
        if kind == "weapon":
            state.powerups.append(PowerUp(pos, kind, data=get_weapon_key_for_wave(state.wave)))
        else:
            state.powerups.append(PowerUp(pos, kind))


def spawn_loot_on_enemy_death(state: GameState, behavior: str, center: Vec2):
    """Spawn loot when an enemy dies (bosses drop better rewards)."""
    b = str(behavior or "")
    if b.startswith("boss_"):
        # Bosses always drop a weapon and at least one regular powerup.
        state.powerups.append(PowerUp(center + Vec2(random.uniform(-20, 20), random.uniform(-20, 20)), "weapon", data=get_weapon_key_for_wave(state.wave + 1)))
        # One guaranteed sustain/utility drop.
        kind = random.choice(["heal", "shield", "laser"])
        state.powerups.append(PowerUp(center + Vec2(random.uniform(-35, 35), random.uniform(-35, 35)), kind))
        # Small bonus chance for a second drop.
        if random.random() < 0.35:
            kind2 = random.choice(["damage", "speed", "firerate"])
            r = random.random()
            if r < 0.08:
                kind2 = "vortex"
            elif state.wave >= 5 and r < 0.3:
                kind2 = "ultra"
            state.powerups.append(PowerUp(center + Vec2(random.uniform(-45, 45), random.uniform(-45, 45)), kind2))
        return

    spawn_powerup_on_kill(state, center)
