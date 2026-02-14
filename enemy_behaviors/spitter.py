"""Spitter behavior for enemies."""
from enemy_behaviors.base import Behavior
from utils import Vec2
from projectile import Projectile
import math
import random

def _perp(v: Vec2) -> Vec2:
    return Vec2(-v.y, v.x)

def _lead_dir(shooter_pos: Vec2, target_pos: Vec2, target_vel: Vec2, proj_speed: float, mult: float = 0.75) -> Vec2:
    d = (target_pos - shooter_pos).length()
    t = (d / max(1.0, float(proj_speed))) * float(mult)
    aim_pos = Vec2(target_pos.x + target_vel.x * t, target_pos.y + target_vel.y * t)
    return (aim_pos - shooter_pos).normalized()

class Spitter(Behavior):
    """A spitter behavior."""

    def update(self, enemy, player_pos, state, dt, player_vel):
        """Update the enemy's state based on its behavior."""
        if "strafe_sign" not in enemy.ai:
            enemy.ai["strafe_sign"] = 1.0 if (id(enemy) % 2) else -1.0
        if "volley_mode" not in enemy.ai:
            enemy.ai["volley_mode"] = 0

        dvec = player_pos - enemy.pos
        d = dvec.length()
        dir_to = dvec.normalized() if d > 1e-6 else Vec2(1.0, 0.0)
        sign = float(enemy.ai["strafe_sign"])
        
        sep = self._separation(enemy, state.enemies, radius=44.0, weight=1.1)
        dodge = self._dodge_player_projectiles(enemy, getattr(state, "projectiles", []))

        if d > 200:
            move = (dir_to * 0.75 + sep * 0.8 + dodge * 0.8).normalized()
            enemy.vel = move * (enemy.speed * 0.8)
            enemy.pos = enemy.pos + enemy.vel * dt
        elif d < 120:
            move = ((dir_to * -1.0) * 0.75 + sep + dodge * 1.1).normalized()
            enemy.vel = move * (enemy.speed * 0.95)
            enemy.pos = enemy.pos + enemy.vel * dt
        else:
            strafe = _perp(dir_to) * sign
            move = (strafe * 0.9 + sep * 0.8 + dir_to * 0.1 + dodge).normalized()
            enemy.vel = move * (enemy.speed * 0.95)
            enemy.pos = enemy.pos + enemy.vel * dt
            
        enemy.attack_cd -= dt
        if enemy.attack_cd <= 0.0 and d < 320:
            aim = _lead_dir(enemy.pos, player_pos, player_vel, proj_speed=210.0, mult=0.85)
            if enemy.ai["volley_mode"] == 0:
                angles = [-22, 0, 22]
                speed = 210.0
                damage = 6
                enemy.attack_cd = 1.4 + random.uniform(0.0, 0.3)
            else:
                angles = [-40, -14, 14, 40]
                speed = 195.0
                damage = 5
                enemy.attack_cd = 1.75 + random.uniform(0.0, 0.35)
                enemy.ai["strafe_sign"] *= -1.0
            for angle_offset in angles:
                angle_rad = math.radians(angle_offset)
                cos_a = math.cos(angle_rad)
                sin_a = math.sin(angle_rad)
                vel_x = aim.x * cos_a - aim.y * sin_a
                vel_y = aim.x * sin_a + aim.y * cos_a
                vel = Vec2(vel_x, vel_y) * speed
                state.projectiles.append(Projectile(enemy.pos, vel, damage, ttl=2.5, owner="enemy", projectile_type="spread"))
            enemy.ai["volley_mode"] = 1 - int(enemy.ai["volley_mode"])

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

    def _dodge_player_projectiles(self, enemy, projectiles, danger_radius: float = 95.0) -> Vec2:
        steer = Vec2(0.0, 0.0)
        count = 0
        for p in projectiles:
            if getattr(p, "owner", "") != "player":
                continue
            rel = enemy.pos - p.pos
            d2 = rel.length_squared()
            if d2 > danger_radius * danger_radius:
                continue
            vel = getattr(p, "vel", Vec2(0.0, 0.0))
            if vel.length_squared() <= 1e-6:
                continue
            toward = rel.dot(vel.normalized())
            if toward >= 0.0:
                continue
            evade = _perp(vel.normalized())
            side = 1.0 if rel.dot(evade) >= 0 else -1.0
            steer += evade * side * (1.0 - (math.sqrt(d2) / danger_radius))
            count += 1
            if count >= 4:
                break
        if count == 0:
            return Vec2(0.0, 0.0)
        return (steer / count).normalized()
