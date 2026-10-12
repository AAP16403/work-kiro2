"""Game state and level management."""

import random
from dataclasses import dataclass, field

import config
from drone import DRONE_DROP_SHARE, DroneCompanion
from enemy import Enemy
from hazards import Trap, LaserBeam, ThunderLine
from layout import Obstacle
from logic import EnemySpawnLogic, EnemyTuningLogic
from mutators import RunRules
from projectile import Projectile
from powerup import PowerUp
from utils import Vec2, random_spawn_map_edge
from weapons import Weapon, get_upgrade_key_for_wave, get_weapon_key_for_wave


@dataclass
class GameState:
    """Main game state."""
    time: float = 0.0
    wave: int = 1
    difficulty: str = "normal"
    map_type: str = "circle"

    # Deterministic RNG for reproducible runs.
    seed: int = 0
    rng: random.Random = field(default_factory=random.Random, repr=False)

    layout_seed: int = 0
    layout_segment: int = 0
    obstacles: list[Obstacle] = field(default_factory=list)
    enemies: list[Enemy] = field(default_factory=list)
    projectiles: list[Projectile] = field(default_factory=list)
    powerups: list[PowerUp] = field(default_factory=list)
    traps: list[Trap] = field(default_factory=list)
    lasers: list[LaserBeam] = field(default_factory=list)
    thunders: list[ThunderLine] = field(default_factory=list)
    drone: DroneCompanion = field(default_factory=DroneCompanion, repr=False)
    wave_active: bool = False
    last_wave_clear: float = 0.0
    shake: float = 0.0
    max_enemies: int = 12  # Base per-wave head count from the difficulty table; spawn_wave adds the wave ramp (wave_cap)
    enemy_combo_value: int = 0
    enemy_combo_text: str = ""
    arena_event: object | None = None  # Running arena event (events.py), or None
    # Run rules from the run's mutators (stock by default). Set once by Game._init_game.
    rules: RunRules = field(default_factory=RunRules, repr=False)

    def init_rng(self, seed: int | None = None) -> None:
        """Initialize or reseed the deterministic RNG used for reproducible runs."""
        if seed is None:
            seed = random.SystemRandom().randint(0, 2**31 - 1)
        self.seed = int(seed)
        self.rng = random.Random(self.seed)


_TUNING_LOGIC = EnemyTuningLogic()
_SPAWN_LOGIC = EnemySpawnLogic(_TUNING_LOGIC)
_STOCK_RULES = RunRules()


def _run_rules(state) -> RunRules:
    """The state's run rules, or stock rules for state objects that predate them."""
    rules = getattr(state, "rules", None)
    return rules if isinstance(rules, RunRules) else _STOCK_RULES


# Elite affixes and their weights. volatile/swift/shielded are the wave-1 affixes; splitter and reflector are wave 2.
ELITE_AFFIX_WEIGHTS = (("volatile", 3), ("swift", 3), ("shielded", 3), ("splitter", 2), ("reflector", 2))


def _choose_affix(rng: random.Random) -> str:
    """Pick one elite affix by weight from the run RNG, so the same seed gives the same affixes."""
    ids = [affix for affix, _ in ELITE_AFFIX_WEIGHTS]
    weights = [float(weight) for _, weight in ELITE_AFFIX_WEIGHTS]
    return rng.choices(ids, weights=weights, k=1)[0]


def get_difficulty_mods(difficulty: str) -> dict:
    """Return difficulty multipliers for spawn rates and stats."""
    return _TUNING_LOGIC.difficulty_mods(difficulty)


def spawn_wave(state: GameState, center: Vec2):
    """Spawn a new wave of enemies with varied difficulty."""
    state.wave_active = True

    # Boss wave every BOSS_WAVE_EVERY waves.
    if state.wave % config.BOSS_WAVE_EVERY == 0:
        behavior_name = get_boss_for_wave(state.wave)
        hp, speed, attack_mult = _get_enemy_stats(behavior_name, state.wave, state.difficulty)
        speed *= float(_run_rules(state).enemy_speed_mult)
        pos = random_spawn_map_edge(center, config.ROOM_RADIUS, state.map_type, rng=state.rng)
        e = Enemy(pos=pos, hp=hp, speed=speed, behavior=behavior_name, max_hp=hp)
        lo, hi = _TUNING_LOGIC.spawn_attack_cd_range(behavior_name)
        atk_cd_scale = max(0.6, min(1.6, float(attack_mult)))
        e.attack_cd = state.rng.uniform(lo, hi) / atk_cd_scale
        e.ai["attack_mult"] = float(attack_mult)
        state.enemies.append(e)
        state.enemy_combo_value = _SPAWN_LOGIC.boss_combo_value(behavior_name)
        state.enemy_combo_text = f"BOSS {behavior_name[5:].upper()}"
        return

    # Boss adds keep using the base state.max_enemies; only the regular wave head count ramps up.
    wave_cap = _SPAWN_LOGIC.wave_cap(state.wave, state.max_enemies)
    plan = _SPAWN_LOGIC.plan_wave(state.wave, state.difficulty, wave_cap, size_mult=_run_rules(state).spawn_size_mult)
    state.enemy_combo_value = int(plan.combo_value)
    state.enemy_combo_text = str(plan.combo_text)

    for behavior_name, behavior_count in plan.behavior_counts.items():
        for _ in range(int(behavior_count)):
            hp, speed, attack_mult = _get_enemy_stats(behavior_name, state.wave, state.difficulty)
            speed *= float(_run_rules(state).enemy_speed_mult)
            pos = random_spawn_map_edge(center, config.ROOM_RADIUS, state.map_type, rng=state.rng)
            
            # Elite enemies roll on wave 3+
            is_elite = False
            affix = ""
            shield_val = 0
            elite_min_wave = int(getattr(config, "ELITE_SPAWN_BASE_WAVE", 3))
            if state.wave >= elite_min_wave and not behavior_name.startswith("boss_"):
                chance = min(0.35, float(getattr(config, "ELITE_SPAWN_CHANCE", 0.14)) + (state.wave - elite_min_wave) * 0.015)
                if state.rng.random() < chance:
                    is_elite = True
                    affix = _choose_affix(state.rng)
                    hp = int(round(hp * float(getattr(config, "ELITE_HP_MULT", 2.2))))
                    if affix == "swift":
                        speed *= float(config.ELITE_SWIFT_SPEED_MULT)
                    elif affix == "shielded":
                        shield_val = int(round(hp * 0.40))

            e = Enemy(
                pos=pos, hp=hp, speed=speed, behavior=behavior_name,
                max_hp=hp, is_elite=is_elite, elite_affix=affix, shield=shield_val,
            )
            lo, hi = _TUNING_LOGIC.spawn_attack_cd_range(behavior_name)
            atk_cd_scale = max(0.6, min(1.6, float(attack_mult)))
            e.attack_cd = state.rng.uniform(lo, hi) / atk_cd_scale
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
    if not _run_rules(state).pickups_enabled:
        return
    min_wave = int(getattr(config, "ULTRA_SPAWN_MIN_WAVE", 4))
    gap = int(getattr(config, "ULTRA_GUARANTEE_WAVE_GAP", 4))
    last_ultra_wave = int(getattr(state, "_last_ultra_wave", 0))
    force_ultra = int(state.wave) >= min_wave and (int(state.wave) - last_ultra_wave) >= max(1, gap)
    mods = get_difficulty_mods(state.difficulty)
    chance = 0.33 * mods["powerup"]
    if force_ultra or state.rng.random() < chance:
        kind = "ultra" if force_ultra else _pick_powerup_kind_for_wave(state, source="wave")
        pos = random_spawn_map_edge(center, config.ROOM_RADIUS * 0.6, state.map_type, rng=state.rng)
        _append_powerup(state, pos, kind)
        if kind == "ultra":
            state._last_ultra_wave = int(state.wave)
            state._kills_since_ultra = 0


def spawn_powerup_on_kill(state: GameState, center: Vec2):
    """Spawn a powerup when an enemy dies."""
    if not _run_rules(state).pickups_enabled:
        return
    state._kills_since_ultra = int(getattr(state, "_kills_since_ultra", 0)) + 1
    pity_threshold = int(getattr(config, "ULTRA_KILL_PITY_THRESHOLD", 30))
    force_ultra = int(state.wave) >= int(getattr(config, "ULTRA_SPAWN_MIN_WAVE", 4)) and int(getattr(state, "_kills_since_ultra", 0)) >= max(8, pity_threshold)
    mods = get_difficulty_mods(state.difficulty)
    chance = 0.15 * mods["powerup"]
    if force_ultra or state.rng.random() < chance:  # base 15% chance per kill (+ pity force)
        kind = "ultra" if force_ultra else _pick_powerup_kind_for_wave(state, source="kill")
        pos = center + Vec2(state.rng.uniform(-50, 50), state.rng.uniform(-50, 50))
        _append_powerup(state, pos, kind)
        if kind == "ultra":
            state._last_ultra_wave = int(state.wave)
            state._kills_since_ultra = 0


def spawn_loot_on_enemy_death(state: GameState, behavior: str, center: Vec2, current_weapon: Weapon | None = None):
    """Spawn loot when an enemy dies (bosses drop better rewards)."""
    if not _run_rules(state).pickups_enabled:
        return  # Iron Man: no pickups of any kind, boss drops included
    b = str(behavior or "")
    if b.startswith("boss_"):
        # Bosses always drop a weapon (an upgrade over current_weapon when one exists) and at least one regular powerup.
        boss_weapon_key = get_upgrade_key_for_wave(state.wave + 1, current_weapon, rng=state.rng)
        state.powerups.append(PowerUp(center + Vec2(state.rng.uniform(-20, 20), state.rng.uniform(-20, 20)), "weapon", data=boss_weapon_key))
        # One guaranteed sustain/utility drop.
        kind = state.rng.choice(["heal", "shield", "laser"])
        state.powerups.append(PowerUp(center + Vec2(state.rng.uniform(-35, 35), state.rng.uniform(-35, 35)), kind))
        # Guaranteed ultra in later boss waves if starved for several waves.
        if int(state.wave) >= int(getattr(config, "ULTRA_SPAWN_MIN_WAVE", 4)):
            last_ultra_wave = int(getattr(state, "_last_ultra_wave", 0))
            gap = int(getattr(config, "ULTRA_GUARANTEE_WAVE_GAP", 4))
            if state.wave - last_ultra_wave >= max(2, gap):
                state.powerups.append(PowerUp(center + Vec2(state.rng.uniform(-30, 30), state.rng.uniform(-30, 30)), "ultra"))
                state._last_ultra_wave = int(state.wave)
                state._kills_since_ultra = 0
        # Small bonus chance for a second drop.
        if state.rng.random() < 0.35:
            kind2 = state.rng.choice(["damage", "speed", "firerate"])
            r = state.rng.random()
            if r < 0.08:
                kind2 = "vortex"
            elif state.wave >= 5 and r < 0.3:
                kind2 = "ultra"
            state.powerups.append(PowerUp(center + Vec2(state.rng.uniform(-45, 45), state.rng.uniform(-45, 45)), kind2))
        return

    spawn_powerup_on_kill(state, center)


def _append_powerup(state: GameState, pos: Vec2, kind: str) -> None:
    k = str(kind or "")
    if k == "weapon":
        state.powerups.append(PowerUp(pos, k, data=get_weapon_key_for_wave(state.wave, rng=state.rng)))
    else:
        state.powerups.append(PowerUp(pos, k))


# Powerup spawn table. Every ordinary powerup roll goes through these steps, in order:
#   1. r < 0.07 -> boost, r < 0.13 -> vortex, wave >= 3 and r < 0.20 -> weapon (one roll, r, decides all three).
#   2. Otherwise the ordinary pool below is picked by weight. A kind's share of the pool is its weight
#      divided by the sum of all weights. The pool gets 87% of rolls before wave 3 and 80% from wave 3 on.
#   3. The wave and kill pity rules can replace the result with Ultra (see _pick_powerup_kind_for_wave).
# Rarity is separate from weight: homing and time_slow are the rare tier (pickup_rare sound, pickup ring).
# Weights are relative. Changing one changes the pool share of every other kind.
POWERUP_POOL_WEIGHTS = (
    ("heal", 1.0),        # common
    ("damage", 1.0),      # common
    ("speed", 1.0),       # common
    ("firerate", 1.0),    # common
    ("shield", 1.0),      # common
    ("laser", 1.0),       # rare
    ("boost", 1.0),       # common
    ("ricochet", 0.5),    # common, 8 s
    ("homing", 0.3),      # rare, 6 s
    ("time_slow", 0.2),   # rare, 4 s
    ("magnet", 0.5),      # common, 10 s
)
_POOL_KINDS = tuple(k for k, _w in POWERUP_POOL_WEIGHTS)
_POOL_WEIGHTS = tuple(float(w) for _k, w in POWERUP_POOL_WEIGHTS)


def _pick_powerup_kind_for_wave(state: GameState, source: str) -> str:
    # Base pool with balanced utilities, weighted by POWERUP_POOL_WEIGHTS
    kind = state.rng.choices(_POOL_KINDS, weights=_POOL_WEIGHTS, k=1)[0]
    r = state.rng.random()
    if r < 0.07:
        kind = "boost"
    elif r < 0.13:
        kind = "vortex"
    elif state.wave >= 3 and r < 0.20:
        kind = "weapon"
    elif state.wave >= 3 and r < 0.20 + DRONE_DROP_SHARE:
        # Rare tier: a thin slice carved out of the base pool, so the other drop rates barely move.
        kind = "drone"

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

    if state.rng.random() < ultra_chance:
        state._last_ultra_wave = int(state.wave)
        state._kills_since_ultra = 0
        return "ultra"
    return kind
