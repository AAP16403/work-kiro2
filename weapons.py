"""Weapon system with different projectile types."""

from dataclasses import dataclass

from utils import Vec2
from config import (
    PLAYER_FIRE_RATE,
    FIRE_RATE_MIN,
    FIRE_RATE_RATIO_MIN,
    FIRE_RATE_RATIO_MAX,
    FIRE_RATE_CURVE,
    WEAPON_WAVE_UPGRADE_CHANCE,
)
import random
import math




@dataclass
class Weapon:
    """Weapon type with stats."""
    name: str
    damage: int
    fire_rate: float
    projectile_count: int
    spread_angle: float  # degrees
    projectile_speed: float
    projectile_type: str  # "bullet", "spread", "laser", "missile", "plasma", "railgun", "flak"
    recoil_kick: float  # degrees added per shot
    recoil_recover: float  # degrees per second
    recoil_max: float  # max recoil in degrees
    cadence_jitter: float  # +/- percent of cooldown
    pierce: int = 0
    crit_chance: float = 0.10
    crit_mult: float = 2.0
    # Upgrade order, ascending expected single-target DPS at PLAYER_DAMAGE:
    # (damage + 5) * projectile_count * (1 + crit_chance * (crit_mult - 1)) / fire_rate. See is_weapon_upgrade.
    rank: int = 0


# Weapon definitions
WEAPONS = {
    "basic": Weapon(
        name="Basic Gun",
        rank=1,
        damage=10,
        fire_rate=0.28,
        projectile_count=1,
        spread_angle=0,
        projectile_speed=360.0,
        projectile_type="bullet",
        recoil_kick=0.9,
        recoil_recover=10.0,
        recoil_max=4.0,
        cadence_jitter=0.05,
    ),
    "spread": Weapon(
        name="Spread Shot",
        rank=5,
        damage=8,
        fire_rate=0.35,
        projectile_count=3,
        spread_angle=30,
        projectile_speed=320.0,
        projectile_type="spread",
        recoil_kick=1.3,
        recoil_recover=8.0,
        recoil_max=6.0,
        cadence_jitter=0.07,
    ),
    "rapid": Weapon(
        name="Rapid Fire",
        rank=3,
        damage=6,
        fire_rate=0.12,
        projectile_count=1,
        spread_angle=5,
        projectile_speed=340.0,
        projectile_type="bullet",
        recoil_kick=0.45,
        recoil_recover=14.0,
        recoil_max=2.5,
        cadence_jitter=0.12,
    ),
    "heavy": Weapon(
        name="Heavy Cannon",
        rank=2,
        damage=20,
        fire_rate=0.40,
        projectile_count=1,
        spread_angle=0,
        projectile_speed=280.0,
        projectile_type="missile",
        recoil_kick=1.8,
        recoil_recover=6.5,
        recoil_max=7.0,
        cadence_jitter=0.03,
    ),
    "plasma": Weapon(
        name="Plasma Rifle",
        rank=6,
        damage=12,
        fire_rate=0.26,
        projectile_count=2,
        spread_angle=20,
        projectile_speed=300.0,
        projectile_type="plasma",
        recoil_kick=1.1,
        recoil_recover=9.0,
        recoil_max=5.0,
        cadence_jitter=0.08,
        crit_chance=0.15,
        crit_mult=2.1,
    ),
    "railgun": Weapon(
        name="Hyper Railgun",
        rank=4,
        damage=40,
        fire_rate=0.50,
        projectile_count=1,
        spread_angle=0,
        projectile_speed=780.0,
        projectile_type="railgun",
        recoil_kick=2.4,
        recoil_recover=6.0,
        recoil_max=8.0,
        cadence_jitter=0.02,
        pierce=3,
        crit_chance=0.22,
        crit_mult=2.6,
    ),
    "flak": Weapon(
        name="Flak Battery",
        rank=7,
        damage=11,
        fire_rate=0.35,
        # Balance pass: 3 pellets across a 72-degree fan (was 5 across 144). The rank above still counts
        # every pellet, so it is an upper bound on single-target DPS until playtest confirms it.
        projectile_count=3,
        spread_angle=36,
        projectile_speed=340.0,
        projectile_type="flak",
        recoil_kick=1.5,
        recoil_recover=8.5,
        recoil_max=6.5,
        cadence_jitter=0.06,
        crit_chance=0.14,
        crit_mult=1.85,
    ),
}

def get_weapon_pool_for_wave(wave: int) -> list[str]:
    """Return the allowed weapon keys for a given wave."""
    if wave <= 2:
        return ["basic"]
    if wave <= 4:
        return ["basic", "rapid", "spread"]
    if wave <= 6:
        # Flak is held back until wave 7: as the top rank it can never be replaced, so an early roll
        # would turn every later weapon pickup into a shield top-up for the rest of the run.
        return ["rapid", "spread", "plasma"]
    return ["spread", "plasma", "heavy", "railgun", "flak"]


def _pool_weights_for_wave(w: int) -> list[float]:
    """Selection weights, aligned with get_weapon_pool_for_wave(w)."""
    if w <= 2:
        return [1.0]
    if w <= 4:
        # Keep basic common early; introduce rapid/spread gradually.
        return [0.50, 0.25, 0.25]
    if w <= 6:
        return [0.30, 0.25, 0.25]  # matches get_weapon_pool_for_wave: flak is not in this pool
    # High wave variety
    return [0.22, 0.22, 0.18, 0.18, 0.20]


def get_weapon_key_for_wave(wave: int, rng: random.Random | None = None) -> str:
    """Pick a weapon key appropriate for the wave.

    Pass the run's seeded RNG so the pick is reproducible; the global random module is the fallback.
    """
    w = int(wave)
    pool = get_weapon_pool_for_wave(w)
    weights = _pool_weights_for_wave(w)
    chooser = random if rng is None else rng
    return chooser.choices(pool, weights=weights, k=1)[0]


def is_weapon_upgrade(current: Weapon | None, candidate: Weapon | None) -> bool:
    """True when candidate strictly outranks current (any real weapon beats having none)."""
    if candidate is None:
        return False
    if current is None:
        return True
    return int(candidate.rank) > int(current.rank)


def get_upgrade_key_for_wave(wave: int, current: Weapon | None, rng: random.Random | None = None) -> str:
    """Pick a wave-pool weapon that outranks `current`, for boss drops.

    Rolls among the pool weapons above the current rank, weighted like get_weapon_key_for_wave.
    When nothing in the pool outranks the current weapon, returns the highest-ranked pool weapon;
    apply_powerup then treats that pickup as a shield top-up rather than a downgrade.
    """
    w = int(wave)
    pool = get_weapon_pool_for_wave(w)
    weights = _pool_weights_for_wave(w)
    cur_rank = int(current.rank) if current is not None else 0
    above = [(key, wt) for key, wt in zip(pool, weights) if int(WEAPONS[key].rank) > cur_rank]
    if not above:
        return max(pool, key=lambda k: int(WEAPONS[k].rank))
    chooser = random if rng is None else rng
    keys = [key for key, _ in above]
    return chooser.choices(keys, weights=[wt for _, wt in above], k=1)[0]


def roll_wave_clear_upgrade(
    current: Weapon | None,
    wave: int,
    rng: random.Random | None = None,
    chance: float = WEAPON_WAVE_UPGRADE_CHANCE,
) -> Weapon | None:
    """Wave-clear weapon roll: with probability `chance` draw a pool weapon and return it only if it outranks `current`.

    Returns None when there is no upgrade, so the current weapon stays. Draws come from `rng` so the run stays reproducible.
    """
    chooser = random if rng is None else rng
    if chooser.random() >= float(chance):
        return None
    candidate = WEAPONS[get_weapon_key_for_wave(int(wave), rng=rng)]
    return candidate if is_weapon_upgrade(current, candidate) else None


def get_effective_fire_rate(weapon: Weapon, player_fire_rate: float) -> float:
    """Compute the actual cooldown used for shooting.

    Player fire_rate acts as a global modifier relative to PLAYER_FIRE_RATE,
    while each weapon has its own base fire_rate.
    """
    base = max(FIRE_RATE_MIN, float(weapon.fire_rate))
    ratio = float(player_fire_rate) / max(FIRE_RATE_MIN, float(PLAYER_FIRE_RATE))
    ratio = max(FIRE_RATE_RATIO_MIN, min(FIRE_RATE_RATIO_MAX, ratio))
    ratio = pow(ratio, FIRE_RATE_CURVE)
    return max(FIRE_RATE_MIN, base * ratio)


def get_weapon_for_wave(wave: int, rng: random.Random | None = None) -> Weapon:
    """Get a random weapon appropriate for the wave."""
    return WEAPONS[get_weapon_key_for_wave(int(wave), rng=rng)]


def get_weapon_color(weapon_type: str) -> tuple:
    """Get color for weapon projectile visuals."""
    colors = {
        "bullet": (255, 245, 190),      # Yellow
        "spread": (255, 200, 100),      # Orange
        "missile": (200, 100, 100),     # Red
        "plasma": (150, 100, 255),      # Purple
        "railgun": (120, 245, 255),     # Electric cyan
        "flak": (255, 140, 50),         # Fiery amber
    }
    return colors.get(weapon_type, (255, 255, 255))
