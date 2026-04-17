"""Projectile entity and related functionality."""

from dataclasses import dataclass
import math
import random
from typing import TYPE_CHECKING

from utils import Vec2

if TYPE_CHECKING:
    from weapons import Weapon

@dataclass
class Projectile:
    """Projectile entity."""
    pos: Vec2
    vel: Vec2
    damage: int
    ttl: float = 2.0
    owner: str = "player"  # "player" or "enemy"
    projectile_type: str = "bullet"  # "bullet", "spread", "missile", "plasma", "bomb"
    prev_pos: Vec2 | None = None

    def update(self, dt: float) -> bool:
        """Update projectile position and TTL. Returns False if expired."""
        self.prev_pos = self.pos
        self.pos = self.pos + self.vel * dt
        self.ttl -= dt
        return self.ttl > 0

def _rotate_dir(aim: Vec2, angle_deg: float) -> Vec2:
    """Rotate aim direction by angle_deg degrees."""
    rad = math.radians(angle_deg)
    c, s = math.cos(rad), math.sin(rad)
    return Vec2(aim.x * c - aim.y * s, aim.x * s + aim.y * c)

def spawn_projectiles(
    muzzle: Vec2,
    aim_direction: Vec2,
    weapon: "Weapon",
    current_time: float,
    base_damage: int,
    recoil_deg: float = 0.0,
    rng: random.Random | None = None,
) -> list[Projectile]:
    """Spawn projectiles based on weapon type."""
    projectiles = []
    rng = rng or random
    
    # Weapon damage = weapon base damage + player damage bonus (50%)
    final_damage = weapon.damage + int(base_damage * 0.5)

    recoil = float(recoil_deg) if recoil_deg and recoil_deg > 0 else 0.0
    
    if weapon.projectile_type == "bullet":
        for i in range(weapon.projectile_count):
            angle_offset = (i - weapon.projectile_count / 2 + 0.5) * weapon.spread_angle
            jitter = rng.uniform(-recoil, recoil) if recoil else 0.0
            d = _rotate_dir(aim_direction, angle_offset + jitter)
            vel = d * weapon.projectile_speed
            projectiles.append(Projectile(
                muzzle, vel, final_damage,
                ttl=2.0, owner="player", projectile_type="bullet"
            ))
    
    elif weapon.projectile_type == "spread":
        for i in range(weapon.projectile_count):
            angle_offset = (i - weapon.projectile_count / 2 + 0.5) * weapon.spread_angle
            jitter = rng.uniform(-recoil, recoil) if recoil else 0.0
            d = _rotate_dir(aim_direction, angle_offset + jitter)
            vel = d * weapon.projectile_speed
            projectiles.append(Projectile(
                muzzle, vel, final_damage,
                ttl=2.2, owner="player", projectile_type="spread"
            ))
    
    elif weapon.projectile_type == "missile":
        jitter = rng.uniform(-recoil, recoil) if recoil else 0.0
        d = _rotate_dir(aim_direction, jitter) if jitter else aim_direction
        vel = d * weapon.projectile_speed
        muzzle_extended = muzzle + aim_direction * 4.0
        projectiles.append(Projectile(muzzle_extended, vel, final_damage, ttl=3.0, owner="player", projectile_type="missile"))
    
    elif weapon.projectile_type == "plasma":
        for i in range(weapon.projectile_count):
            angle_offset = (i - weapon.projectile_count / 2 + 0.5) * weapon.spread_angle
            jitter = rng.uniform(-recoil, recoil) if recoil else 0.0
            d = _rotate_dir(aim_direction, angle_offset + jitter)
            vel = d * weapon.projectile_speed
            projectiles.append(Projectile(muzzle, vel, final_damage, ttl=2.5, owner="player", projectile_type="plasma"))
    
    elif weapon.projectile_type == "laser":
        # Fast moving visual beam
        vel = aim_direction * 2000.0
        projectiles.append(Projectile(
            muzzle, vel, final_damage,
            ttl=0.05, owner="player", projectile_type="laser"
        ))
    
        return projectiles

    return projectiles
