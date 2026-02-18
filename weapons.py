"""Weapon system with different projectile types."""

from dataclasses import dataclass

from utils import Vec2
from config import PLAYER_FIRE_RATE
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
    projectile_type: str  # "bullet", "spread", "laser", "missile", "plasma"


# Weapon definitions
WEAPONS = {
    "basic": Weapon(
        name="Basic Gun",
        damage=10,
        fire_rate=0.28,
        projectile_count=1,
        spread_angle=0,
        projectile_speed=360.0,
        projectile_type="bullet"
    ),
    "spread": Weapon(
        name="Spread Shot",
        damage=8,
        fire_rate=0.35,
        projectile_count=3,
        spread_angle=30,
        projectile_speed=320.0,
        projectile_type="spread"
    ),
    "rapid": Weapon(
        name="Rapid Fire",
        damage=6,
        fire_rate=0.12,
        projectile_count=1,
        spread_angle=5,
        projectile_speed=340.0,
        projectile_type="bullet"
    ),
    "heavy": Weapon(
        name="Heavy Cannon",
        damage=20,
        fire_rate=0.38,
        projectile_count=1,
        spread_angle=0,
        projectile_speed=280.0,
        projectile_type="missile"
    ),
    "plasma": Weapon(
        name="Plasma Rifle",
        damage=12,
        fire_rate=0.25,
        projectile_count=2,
        spread_angle=20,
        projectile_speed=300.0,
        projectile_type="plasma"
    ),
}

def get_weapon_pool_for_wave(wave: int) -> list[str]:
    """Return the allowed weapon keys for a given wave."""
    if wave <= 2:
        return ["basic"]
    if wave <= 4:
        return ["basic", "rapid", "spread"]
    if wave <= 6:
        return ["rapid", "spread", "plasma"]
    return ["spread", "plasma", "heavy"]


def get_weapon_key_for_wave(wave: int) -> str:
    """Pick a random weapon key appropriate for the wave."""
    w = int(wave)
    pool = get_weapon_pool_for_wave(w)
    if w <= 2:
        weights = [1.0]
    elif w <= 4:
        # Keep basic common early; introduce rapid/spread gradually.
        weights = [0.55, 0.25, 0.20]  # basic, rapid, spread
    elif w <= 6:
        weights = [0.35, 0.35, 0.30]  # rapid, spread, plasma
    else:
        # Heavy is intentionally rarer; it's a high-commitment weapon.
        weights = [0.45, 0.45, 0.10]  # spread, plasma, heavy
    return random.choices(pool, weights=weights, k=1)[0]


def get_effective_fire_rate(weapon: Weapon, player_fire_rate: float) -> float:
    """Compute the actual cooldown used for shooting.

    Player fire_rate acts as a global modifier relative to PLAYER_FIRE_RATE,
    while each weapon has its own base fire_rate.
    """
    base = max(0.06, float(weapon.fire_rate))
    mult = float(player_fire_rate) / max(0.06, float(PLAYER_FIRE_RATE))
    mult = max(0.45, min(2.25, mult))
    return max(0.06, base * mult)





def get_weapon_for_wave(wave: int) -> Weapon:
    """Get a random weapon appropriate for the wave."""
    return WEAPONS[get_weapon_key_for_wave(int(wave))]


def get_weapon_color(weapon_type: str) -> tuple:
    """Get color for weapon projectile visuals."""
    colors = {
        "bullet": (255, 245, 190),      # Yellow
        "spread": (255, 200, 100),      # Orange
        "missile": (200, 100, 100),     # Red
        "plasma": (150, 100, 255),      # Purple
    }
    return colors.get(weapon_type, (255, 255, 255))
