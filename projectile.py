"""Projectile entity and related functionality."""

from dataclasses import dataclass
import math
import random
from typing import TYPE_CHECKING

from config import PLAYER_DAMAGE
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
    projectile_type: str = "bullet"  # "bullet", "spread", "missile", "plasma", "bomb", "railgun", "flak"
    prev_pos: Vec2 | None = None
    pierce: int = 0
    is_crit: bool = False
    cluster_on_death: bool = False

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
    crit_chance_bonus: float = 0.0,
    crit_mult_bonus: float = 0.0,
) -> list[Projectile]:
    """Spawn projectiles based on weapon type."""
    projectiles = []
    rng = rng or random
    
    # The player's damage scales the whole shot: the weapon's own damage and the 50% player bonus
    # are both multiplied by base_damage / PLAYER_DAMAGE, rounded half-up. At base 10 this is
    # weapon.damage + 5 (basic 15, heavy 25, railgun 45), so the tuning point is unchanged.
    raw_damage = math.floor((weapon.damage + 0.5 * PLAYER_DAMAGE) * float(base_damage) / PLAYER_DAMAGE + 0.5)

    # Roll critical hit
    effective_crit_chance = min(0.85, max(0.0, getattr(weapon, "crit_chance", 0.10) + crit_chance_bonus))
    is_crit = rng.random() < effective_crit_chance
    if is_crit:
        mult = getattr(weapon, "crit_mult", 2.0) + crit_mult_bonus
        final_damage = max(1, int(round(raw_damage * mult)))
    else:
        final_damage = max(1, raw_damage)

    recoil = float(recoil_deg) if recoil_deg and recoil_deg > 0 else 0.0
    pierce_val = int(getattr(weapon, "pierce", 0))
    
    if weapon.projectile_type == "bullet":
        for i in range(weapon.projectile_count):
            angle_offset = (i - weapon.projectile_count / 2 + 0.5) * weapon.spread_angle
            jitter = rng.uniform(-recoil, recoil) if recoil else 0.0
            d = _rotate_dir(aim_direction, angle_offset + jitter)
            vel = d * weapon.projectile_speed
            projectiles.append(Projectile(
                muzzle, vel, final_damage,
                ttl=2.0, owner="player", projectile_type="bullet",
                is_crit=is_crit,
            ))
    
    elif weapon.projectile_type == "spread":
        for i in range(weapon.projectile_count):
            angle_offset = (i - weapon.projectile_count / 2 + 0.5) * weapon.spread_angle
            jitter = rng.uniform(-recoil, recoil) if recoil else 0.0
            d = _rotate_dir(aim_direction, angle_offset + jitter)
            vel = d * weapon.projectile_speed
            projectiles.append(Projectile(
                muzzle, vel, final_damage,
                ttl=2.2, owner="player", projectile_type="spread",
                is_crit=is_crit,
            ))
    
    elif weapon.projectile_type == "missile":
        jitter = rng.uniform(-recoil, recoil) if recoil else 0.0
        d = _rotate_dir(aim_direction, jitter) if jitter else aim_direction
        vel = d * weapon.projectile_speed
        muzzle_extended = muzzle + aim_direction * 4.0
        projectiles.append(Projectile(
            muzzle_extended, vel, final_damage,
            ttl=3.0, owner="player", projectile_type="missile",
            is_crit=is_crit,
        ))
    
    elif weapon.projectile_type == "plasma":
        for i in range(weapon.projectile_count):
            angle_offset = (i - weapon.projectile_count / 2 + 0.5) * weapon.spread_angle
            jitter = rng.uniform(-recoil, recoil) if recoil else 0.0
            d = _rotate_dir(aim_direction, angle_offset + jitter)
            vel = d * weapon.projectile_speed
            projectiles.append(Projectile(
                muzzle, vel, final_damage,
                ttl=2.5, owner="player", projectile_type="plasma",
                is_crit=is_crit,
            ))

    elif weapon.projectile_type == "railgun":
        jitter = rng.uniform(-recoil * 0.4, recoil * 0.4) if recoil else 0.0
        d = _rotate_dir(aim_direction, jitter) if jitter else aim_direction
        vel = d * weapon.projectile_speed
        projectiles.append(Projectile(
            muzzle, vel, final_damage,
            ttl=1.8, owner="player", projectile_type="railgun",
            pierce=pierce_val, is_crit=is_crit,
        ))

    elif weapon.projectile_type == "flak":
        for i in range(weapon.projectile_count):
            angle_offset = (i - weapon.projectile_count / 2 + 0.5) * weapon.spread_angle
            jitter = rng.uniform(-recoil, recoil) if recoil else 0.0
            d = _rotate_dir(aim_direction, angle_offset + jitter)
            vel = d * weapon.projectile_speed * rng.uniform(0.9, 1.1)
            projectiles.append(Projectile(
                muzzle, vel, final_damage,
                ttl=rng.uniform(0.7, 1.1), owner="player", projectile_type="flak",
                is_crit=is_crit, cluster_on_death=True,
            ))
    
    elif weapon.projectile_type == "laser":
        vel = aim_direction * 2000.0
        projectiles.append(Projectile(
            muzzle, vel, final_damage,
            ttl=0.05, owner="player", projectile_type="laser",
            is_crit=is_crit,
        ))

    return projectiles
