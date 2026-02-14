"""Tank behavior for enemies."""
from enemy_behaviors.base import Behavior
from utils import Vec2
from projectile import Projectile
import math
import random

def _lead_dir(shooter_pos: Vec2, target_pos: Vec2, target_vel: Vec2, proj_speed: float, mult: float = 0.75) -> Vec2:
    d = (target_pos - shooter_pos).length()
    t = (d / max(1.0, float(proj_speed))) * float(mult)
    aim_pos = Vec2(target_pos.x + target_vel.x * t, target_pos.y + target_vel.y * t)
    return (aim_pos - shooter_pos).normalized()

class Tank(Behavior):
    """A tank behavior."""

    def update(self, enemy, player_pos, state, dt, player_vel):
        """Update the enemy's state based on its behavior."""
        dvec = player_pos - enemy.pos
        d = dvec.length()
        dir_to = dvec.normalized() if d > 1e-6 else Vec2(1.0, 0.0)
        
        sep = self._separation(enemy, state.enemies, radius=44.0, weight=1.1)

        if d > 100:
            # Move slowly toward player
            move = (dir_to * 0.7 + sep * 0.6).normalized()
            enemy.vel = move * (enemy.speed * 0.65)
            enemy.pos = enemy.pos + enemy.vel * dt
        else:
            enemy.vel = Vec2(0.0, 0.0)
        
        # Stop and attack when close
        enemy.attack_cd -= dt
        if enemy.attack_cd <= 0.0 and d < 150:
            proj_speed = 185.0
            aim = _lead_dir(enemy.pos, player_pos, player_vel, proj_speed, mult=0.6)
            vel = aim * proj_speed
            state.projectiles.append(Projectile(enemy.pos, vel, 12, ttl=2.8, owner="enemy"))
            enemy.attack_cd = 1.9 + random.uniform(0.0, 0.3)

    def _separation(self, enemy, others, radius: float = 44.0, weight: float = 1.1) -> Vec2:
        """Repel from nearby enemies to reduce stacking."""
        r = float(radius)
        acc = Vec2(0.0, 0.0)
        count = 0
        for o in others:
            if o is enemy:
                continue
            dvec = enemy.pos - o.pos
            d = dvec.length()
            if d <= 1e-6 or d > r:
                continue
            acc = acc + dvec * (1.0 / (d * d))
            count += 1
        if count == 0:
            return Vec2(0.0, 0.0)
        return acc.normalized() * weight
