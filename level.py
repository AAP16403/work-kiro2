"""Game state and level management."""

import random
from dataclasses import dataclass, field
from typing import List

import config
from enemy import Enemy
from hazards import Trap, LaserBeam, ThunderLine
from projectile import Projectile
from powerup import PowerUp
from utils import Vec2, random_spawn_edge


@dataclass
class GameState:
    """Main game state."""
    time: float = 0.0
    wave: int = 1
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


def spawn_wave(state: GameState, center: Vec2):
    """Spawn a new wave of enemies with varied difficulty."""
    state.wave_active = True

    # Boss wave every 5 waves.
    if state.wave % 5 == 0:
        behavior = get_boss_for_wave(state.wave)
        hp, speed, _attack_mult = _get_enemy_stats(behavior, state.wave)
        pos = random_spawn_edge(center, config.ROOM_RADIUS)
        e = Enemy(pos=pos, hp=hp, speed=speed, behavior=behavior)
        e.attack_cd = random.uniform(0.6, 1.6)
        state.enemies.append(e)
        return
    
    # Scale difficulty: fewer strong enemies at first, more variety later
    base_count = 3 + state.wave * 2
    cap = state.max_enemies
    count = min(base_count, cap)
    
    # Enemy type distribution changes with waves
    for _ in range(count):
        behavior = _get_weighted_behavior(state.wave)
        hp, speed, attack_mult = _get_enemy_stats(behavior, state.wave)
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


def _get_enemy_stats(behavior: str, wave: int) -> tuple:
    """Get HP, speed, and attack multiplier for enemy type.
    
    Returns: (hp, speed, attack_mult)
    """
    base_hp = 22 + wave * 5
    base_speed = 55 + wave * 2

    if behavior == "chaser":
        return (base_hp, base_speed * 1.35, 1.0)
    elif behavior == "ranged":
        return (base_hp - 5, base_speed * 0.85, 1.2)
    elif behavior == "charger":
        return (base_hp + 10, base_speed * 1.05, 0.8)
    elif behavior == "swarm":
        # Many weak, fast enemies
        return (max(8, base_hp // 2), base_speed * 1.55, 0.5)
    elif behavior == "tank":
        # Slow but tanky
        return (base_hp * 2, base_speed * 0.55, 0.9)
    elif behavior == "spitter":
        # Medium stats, spreads fire
        return (base_hp - 3, base_speed * 0.9, 1.5)
    elif behavior == "flyer":
        # Erratic movement
        return (base_hp - 7, base_speed * 1.7, 0.7)
    elif behavior == "engineer":
        # Builds traps; slower, higher HP
        return (base_hp + 6, base_speed * 0.75, 1.1)
    elif behavior == "boss_thunder":
        return (150 + wave * 32, base_speed * 0.9, 1.8)
    elif behavior == "boss_laser":
        return (135 + wave * 28, base_speed * 1.1, 1.8)
    elif behavior == "boss_trapmaster":
        return (170 + wave * 30, base_speed * 0.85, 1.7)
    elif behavior == "boss_swarmqueen":
        return (155 + wave * 26, base_speed * 0.95, 1.7)
    elif behavior == "boss_brute":
        return (190 + wave * 34, base_speed * 1.05, 1.9)
    else:
        return (base_hp, base_speed, 1.0)


def maybe_spawn_powerup(state: GameState, center: Vec2):
    """Randomly spawn a powerup."""
    if random.random() < 0.33:
        kind = random.choice(["heal", "damage", "speed", "firerate", "shield", "laser"])
        if random.random() < 0.06:
            kind = "vortex"
        pos = random_spawn_edge(center, config.ROOM_RADIUS * 0.6)
        state.powerups.append(PowerUp(pos, kind))


def spawn_powerup_on_kill(state: GameState, center: Vec2):
    """Spawn a powerup when an enemy dies."""
    if random.random() < 0.15:  # 15% chance per kill
        kind = random.choice(["heal", "damage", "speed", "firerate", "shield", "laser"])
        if random.random() < 0.03:
            kind = "vortex"
        # Spawn near center
        pos = center + Vec2(random.uniform(-50, 50), random.uniform(-50, 50))
        state.powerups.append(PowerUp(pos, kind))
