"""Game state and level management."""

import random
from dataclasses import dataclass, field

import config
from enemy import Enemy
from hazards import Trap, LaserBeam, ThunderLine
from layout import Obstacle
from logic import EnemySpawnLogic, EnemyTuningLogic
from projectile import Projectile
from powerup import PowerUp
from utils import Vec2, random_spawn_map_edge
from weapons import get_weapon_key_for_wave


@dataclass
class GameState:
    """Main game state."""
    time: float = 0.0
    wave: int = 1
    difficulty: str = "normal"
    map_type: str = "circle"
    layout_seed: int = 0
    layout_segment: int = 0
    obstacles: list[Obstacle] = field(default_factory=list)
    enemies: list[Enemy] = field(default_factory=list)
    projectiles: list[Projectile] = field(default_factory=list)
    powerups: list[PowerUp] = field(default_factory=list)
    traps: list[Trap] = field(default_factory=list)
    lasers: list[LaserBeam] = field(default_factory=list)
    thunders: list[ThunderLine] = field(default_factory=list)
    wave_active: bool = False
    last_wave_clear: float = 0.0
    shake: float = 0.0
    max_enemies: int = 12  # Limit concurrent enemies
    enemy_combo_value: int = 0
    enemy_combo_text: str = ""


_SPAWN_LOGIC = EnemySpawnLogic()
_TUNING_LOGIC = EnemyTuningLogic()


def get_difficulty_mods(difficulty: str) -> dict:
    """Return difficulty multipliers for spawn rates and stats."""
    return _TUNING_LOGIC.difficulty_mods(difficulty)


def spawn_wave(state: GameState, center: Vec2):
    """Spawn a new wave of enemies with varied difficulty."""
    state.wave_active = True

    # Boss wave every 5 waves.
    if state.wave % 5 == 0:
        behavior_name = get_boss_for_wave(state.wave)
        hp, speed, attack_mult = _get_enemy_stats(behavior_name, state.wave, state.difficulty)
        pos = random_spawn_map_edge(center, config.ROOM_RADIUS, state.map_type)
        e = Enemy(pos=pos, hp=hp, speed=speed, behavior=behavior_name)
        lo, hi = _TUNING_LOGIC.spawn_attack_cd_range(behavior_name)
        atk_cd_scale = max(0.6, min(1.6, float(attack_mult)))
        e.attack_cd = random.uniform(lo, hi) / atk_cd_scale
        e.ai["attack_mult"] = float(attack_mult)
        state.enemies.append(e)
        state.enemy_combo_value = _SPAWN_LOGIC.boss_combo_value(behavior_name)
        state.enemy_combo_text = f"BOSS {behavior_name[5:].upper()}"
        return

    plan = _SPAWN_LOGIC.plan_wave(state.wave, state.difficulty, state.max_enemies)
    state.enemy_combo_value = int(plan.combo_value)
    state.enemy_combo_text = str(plan.combo_text)

    for behavior_name, behavior_count in plan.behavior_counts.items():
        for _ in range(int(behavior_count)):
            hp, speed, attack_mult = _get_enemy_stats(behavior_name, state.wave, state.difficulty)
            pos = random_spawn_map_edge(center, config.ROOM_RADIUS, state.map_type)
            e = Enemy(pos=pos, hp=hp, speed=speed, behavior=behavior_name)
            lo, hi = _TUNING_LOGIC.spawn_attack_cd_range(behavior_name)
            atk_cd_scale = max(0.6, min(1.6, float(attack_mult)))
            e.attack_cd = random.uniform(lo, hi) / atk_cd_scale
            e.ai["attack_mult"] = float(attack_mult)
            state.enemies.append(e)


def get_boss_for_wave(wave: int) -> str:
    return _TUNING_LOGIC.get_boss_for_wave(wave)


def _get_enemy_stats(behavior: str, wave: int, difficulty: str = "normal") -> tuple:
    """Get HP, speed, and attack multiplier for enemy type.
    
    Returns: (hp, speed, attack_mult)
    """
    return _TUNING_LOGIC.enemy_stats(behavior, wave, difficulty)


def maybe_spawn_powerup(state: GameState, center: Vec2):
    """Randomly spawn a powerup."""
    min_wave = int(getattr(config, "ULTRA_SPAWN_MIN_WAVE", 4))
    gap = int(getattr(config, "ULTRA_GUARANTEE_WAVE_GAP", 4))
    last_ultra_wave = int(getattr(state, "_last_ultra_wave", 0))
    force_ultra = int(state.wave) >= min_wave and (int(state.wave) - last_ultra_wave) >= max(1, gap)
    mods = get_difficulty_mods(state.difficulty)
    chance = 0.33 * mods["powerup"]
    if force_ultra or random.random() < chance:
        kind = "ultra" if force_ultra else _pick_powerup_kind_for_wave(state, source="wave")
        pos = random_spawn_map_edge(center, config.ROOM_RADIUS * 0.6, state.map_type)
        _append_powerup(state, pos, kind)
        if kind == "ultra":
            state._last_ultra_wave = int(state.wave)
            state._kills_since_ultra = 0


def spawn_powerup_on_kill(state: GameState, center: Vec2):
    """Spawn a powerup when an enemy dies."""
    state._kills_since_ultra = int(getattr(state, "_kills_since_ultra", 0)) + 1
    pity_threshold = int(getattr(config, "ULTRA_KILL_PITY_THRESHOLD", 30))
    force_ultra = int(state.wave) >= int(getattr(config, "ULTRA_SPAWN_MIN_WAVE", 4)) and int(getattr(state, "_kills_since_ultra", 0)) >= max(8, pity_threshold)
    mods = get_difficulty_mods(state.difficulty)
    chance = 0.15 * mods["powerup"]
    if force_ultra or random.random() < chance:  # base 15% chance per kill (+ pity force)
        kind = "ultra" if force_ultra else _pick_powerup_kind_for_wave(state, source="kill")
        pos = center + Vec2(random.uniform(-50, 50), random.uniform(-50, 50))
        _append_powerup(state, pos, kind)
        if kind == "ultra":
            state._last_ultra_wave = int(state.wave)
            state._kills_since_ultra = 0


def spawn_loot_on_enemy_death(state: GameState, behavior: str, center: Vec2):
    """Spawn loot when an enemy dies (bosses drop better rewards)."""
    b = str(behavior or "")
    if b.startswith("boss_"):
        # Bosses always drop a weapon and at least one regular powerup.
        state.powerups.append(PowerUp(center + Vec2(random.uniform(-20, 20), random.uniform(-20, 20)), "weapon", data=get_weapon_key_for_wave(state.wave + 1)))
        # One guaranteed sustain/utility drop.
        kind = random.choice(["heal", "shield", "laser"])
        state.powerups.append(PowerUp(center + Vec2(random.uniform(-35, 35), random.uniform(-35, 35)), kind))
        # Guaranteed ultra in later boss waves if starved for several waves.
        if int(state.wave) >= int(getattr(config, "ULTRA_SPAWN_MIN_WAVE", 4)):
            last_ultra_wave = int(getattr(state, "_last_ultra_wave", 0))
            gap = int(getattr(config, "ULTRA_GUARANTEE_WAVE_GAP", 4))
            if state.wave - last_ultra_wave >= max(2, gap):
                state.powerups.append(PowerUp(center + Vec2(random.uniform(-30, 30), random.uniform(-30, 30)), "ultra"))
                state._last_ultra_wave = int(state.wave)
                state._kills_since_ultra = 0
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


def _append_powerup(state: GameState, pos: Vec2, kind: str) -> None:
    k = str(kind or "")
    if k == "weapon":
        state.powerups.append(PowerUp(pos, k, data=get_weapon_key_for_wave(state.wave)))
    else:
        state.powerups.append(PowerUp(pos, k))


def _pick_powerup_kind_for_wave(state: GameState, source: str) -> str:
    # Base pool.
    kind = random.choice(["heal", "damage", "speed", "firerate", "shield", "laser"])
    r = random.random()
    if r < 0.06:
        kind = "vortex"
    elif state.wave >= 3 and r < 0.11:
        kind = "weapon"

    min_wave = int(getattr(config, "ULTRA_SPAWN_MIN_WAVE", 4))
    if int(state.wave) < min_wave:
        return kind

    last_ultra_wave = int(getattr(state, "_last_ultra_wave", 0))
    gap = int(getattr(config, "ULTRA_GUARANTEE_WAVE_GAP", 4))

    # Wave-clear pity: guaranteed ultra if too many waves without one.
    if source == "wave" and (int(state.wave) - last_ultra_wave) >= max(1, gap):
        state._last_ultra_wave = int(state.wave)
        state._kills_since_ultra = 0
        return "ultra"

    # Kill pity: if many kills since last ultra, force one on the next powerup drop.
    kills_since_ultra = int(getattr(state, "_kills_since_ultra", 0))
    pity_threshold = int(getattr(config, "ULTRA_KILL_PITY_THRESHOLD", 30))
    if source == "kill" and kills_since_ultra >= max(8, pity_threshold):
        state._last_ultra_wave = int(state.wave)
        state._kills_since_ultra = 0
        return "ultra"

    if source == "wave":
        base = float(getattr(config, "ULTRA_WAVE_SPAWN_BASE", 0.03))
        per = float(getattr(config, "ULTRA_WAVE_SPAWN_PER_WAVE", 0.004))
        mx = float(getattr(config, "ULTRA_WAVE_SPAWN_MAX", 0.2))
        ultra_chance = min(mx, base + max(0.0, state.wave - min_wave) * per)
    else:
        ultra_chance = float(getattr(config, "ULTRA_KILL_BASE_CHANCE", 0.015))

    if random.random() < ultra_chance:
        state._last_ultra_wave = int(state.wave)
        state._kills_since_ultra = 0
        return "ultra"
    return kind
