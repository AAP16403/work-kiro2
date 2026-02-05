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
        behavior = get_boss_for_wave(state.wave)
        hp, speed, _attack_mult = _get_enemy_stats(behavior, state.wave, state.difficulty)
        pos = random_spawn_edge(center, config.ROOM_RADIUS)
        e = Enemy(pos=pos, hp=hp, speed=speed, behavior=behavior)
        e.attack_cd = random.uniform(0.6, 1.6)
        state.enemies.append(e)
        return
    
    # Scale difficulty: fewer strong enemies at first, more variety later
    base_count = 3 + state.wave * 2
    base_count = max(1, int(base_count * mods["spawn"]))
    cap = state.max_enemies
    count = min(base_count, cap)
    
    # Enemy type distribution changes with waves
    for _ in range(count):
        behavior = _get_weighted_behavior(state.wave)
        hp, speed, attack_mult = _get_enemy_stats(behavior, state.wave, state.difficulty)
        pos = random_spawn_edge(center, config.ROOM_RADIUS)
        e = Enemy(pos=pos, hp=hp, speed=speed, behavior=behavior)
        if behavior == "engineer":
            e.attack_cd = random.uniform(0.6, 1.4)
        else:
            e.attack_cd = random.uniform(0.2, 1.0)
        state.enemies.append(e)


def _get_weighted_behavior(wave: int) -> str:
    """Get enemy behavior weighted by wave difficulty."""
    behaviors = ["chaser", "ranged", "charger"]
    
    # Add new enemy types on later waves
    if wave >= 3:
        behaviors.append("swarm")
    if wave >= 5:
        behaviors.append("tank")
    if wave >= 7:
        behaviors.append("spitter")
    if wave >= 9:
        behaviors.append("flyer")
    if wave >= 4:
        behaviors.append("engineer")
    
    return random.choice(behaviors)


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
        hp, speed, atk = (base_hp, base_speed * 1.35, 1.0)
    elif behavior == "ranged":
        hp, speed, atk = (base_hp - 5, base_speed * 0.85, 1.2)
    elif behavior == "charger":
        hp, speed, atk = (base_hp + 10, base_speed * 1.05, 0.8)
    elif behavior == "swarm":
        # Many weak, fast enemies
        hp, speed, atk = (max(8, base_hp // 2), base_speed * 1.55, 0.5)
    elif behavior == "tank":
        # Slow but tanky
        hp, speed, atk = (base_hp * 2, base_speed * 0.55, 0.9)
    elif behavior == "spitter":
        # Medium stats, spreads fire
        hp, speed, atk = (base_hp - 3, base_speed * 0.9, 1.5)
    elif behavior == "flyer":
        # Erratic movement
        hp, speed, atk = (base_hp - 7, base_speed * 1.7, 0.7)
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
    hp = max(1, int(hp * hp_mult))
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
        pos = random_spawn_edge(center, config.ROOM_RADIUS * 0.6)
        state.powerups.append(PowerUp(pos, kind))


def spawn_powerup_on_kill(state: GameState, center: Vec2):
    """Spawn a powerup when an enemy dies."""
    mods = get_difficulty_mods(state.difficulty)
    chance = 0.15 * mods["powerup"]
    if random.random() < chance:  # base 15% chance per kill
        kind = random.choice(["heal", "damage", "speed", "firerate", "shield", "laser"])
        if random.random() < 0.03:
            kind = "vortex"
        # Spawn near center
        pos = center + Vec2(random.uniform(-50, 50), random.uniform(-50, 50))
        state.powerups.append(PowerUp(pos, kind))
