"""Weapon system with different projectile types."""

from dataclasses import dataclass
from typing import List
from projectile import Projectile
from utils import Vec2
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
        fire_rate=0.6,
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


def spawn_weapon_projectiles(
    muzzle: Vec2,
    aim_direction: Vec2,
    weapon: Weapon,
    current_time: float,
    base_damage: int
) -> List[Projectile]:
    """Spawn projectiles based on weapon type."""
    projectiles = []
    
    # Weapon damage = weapon base damage + player damage bonus (50%)
    final_damage = weapon.damage + int(base_damage * 0.5)
    
    if weapon.projectile_type == "bullet":
        for i in range(weapon.projectile_count):
            angle_offset = (i - weapon.projectile_count / 2 + 0.5) * weapon.spread_angle
            angle_rad = math.radians(angle_offset)
            
            # Rotate aim direction
            cos_a = math.cos(angle_rad)
            sin_a = math.sin(angle_rad)
            rotated_x = aim_direction.x * cos_a - aim_direction.y * sin_a
            rotated_y = aim_direction.x * sin_a + aim_direction.y * cos_a
            
            vel = Vec2(rotated_x, rotated_y) * weapon.projectile_speed
            
            projectiles.append(Projectile(
                muzzle, vel, final_damage,
                ttl=2.0, owner="player"
            ))
    
    elif weapon.projectile_type == "spread":
        for i in range(weapon.projectile_count):
            angle_offset = (i - weapon.projectile_count / 2 + 0.5) * weapon.spread_angle
            angle_rad = math.radians(angle_offset)
            
            cos_a = math.cos(angle_rad)
            sin_a = math.sin(angle_rad)
            rotated_x = aim_direction.x * cos_a - aim_direction.y * sin_a
            rotated_y = aim_direction.x * sin_a + aim_direction.y * cos_a
            
            vel = Vec2(rotated_x, rotated_y) * weapon.projectile_speed
            
            projectiles.append(Projectile(
                muzzle, vel, final_damage,
                ttl=2.2, owner="player"
            ))
    
    elif weapon.projectile_type == "missile":
        # Larger, slower projectiles
        vel = aim_direction * weapon.projectile_speed
        muzzle_extended = muzzle + aim_direction * 4.0
        proj = Projectile(muzzle_extended, vel, final_damage, ttl=3.0, owner="player")
        proj.projectile_type = "missile"
        projectiles.append(proj)
    
    elif weapon.projectile_type == "plasma":
        # Multiple projectiles with spread
        for i in range(weapon.projectile_count):
            angle_offset = (i - weapon.projectile_count / 2 + 0.5) * weapon.spread_angle
            angle_rad = math.radians(angle_offset)
            
            cos_a = math.cos(angle_rad)
            sin_a = math.sin(angle_rad)
            rotated_x = aim_direction.x * cos_a - aim_direction.y * sin_a
            rotated_y = aim_direction.x * sin_a + aim_direction.y * cos_a
            
            vel = Vec2(rotated_x, rotated_y) * weapon.projectile_speed
            
            proj = Projectile(muzzle, vel, final_damage, ttl=2.5, owner="player")
            proj.projectile_type = "plasma"
            projectiles.append(proj)
    
    return projectiles


def get_weapon_for_wave(wave: int) -> Weapon:
    """Get a random weapon appropriate for the wave."""
    if wave <= 2:
        return WEAPONS["basic"]
    elif wave <= 4:
        return random.choice([WEAPONS["basic"], WEAPONS["rapid"], WEAPONS["spread"]])
    elif wave <= 6:
        return random.choice([WEAPONS["rapid"], WEAPONS["spread"], WEAPONS["plasma"]])
    else:
        return random.choice([WEAPONS["spread"], WEAPONS["plasma"], WEAPONS["heavy"]])


def get_weapon_color(weapon_type: str) -> tuple:
    """Get color for weapon projectile visuals."""
    colors = {
        "bullet": (255, 245, 190),      # Yellow
        "spread": (255, 200, 100),      # Orange
        "missile": (200, 100, 100),     # Red
        "plasma": (150, 100, 255),      # Purple
    }
    return colors.get(weapon_type, (255, 255, 255))
