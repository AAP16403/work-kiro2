"""Ranged behavior for enemies."""
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

class Ranged(Behavior):
    """A ranged behavior with simple hiding."""

    def __init__(self, desired_min_dist=140.0, desired_max_dist=220.0, hiding_enabled=True):
        self.desired_min_dist = desired_min_dist
        self.desired_max_dist = desired_max_dist
        self.hiding_enabled = hiding_enabled

    def update(self, enemy, player_pos, state, dt, player_vel):
        """Update the enemy's state based on its behavior."""
        
        cover_pos = self._find_cover(enemy, player_pos, state.obstacles)

        if self.hiding_enabled and cover_pos:
            self._do_hiding_behavior(enemy, player_pos, cover_pos, state, dt, player_vel)
        else:
            self._do_kiting_behavior(enemy, player_pos, state, dt, player_vel)

    def _find_cover(self, enemy, player_pos, obstacles):
        """Find the best cover position behind an obstacle."""
        best_cover = None
        min_dist = float('inf')

        for obs in obstacles:
            # Position behind the obstacle, relative to the player
            dir_from_player = (obs.pos - player_pos).normalized()
            cover_pos = obs.pos + dir_from_player * (obs.radius + 20)
            
            dist_to_cover = (enemy.pos - cover_pos).length()
            if dist_to_cover < min_dist:
                min_dist = dist_to_cover
                best_cover = cover_pos
        
        return best_cover

    def _do_hiding_behavior(self, enemy, player_pos, cover_pos, state, dt, player_vel):
        """Move to cover and occasionally peek out to shoot."""
        dist_to_cover = (enemy.pos - cover_pos).length()

        if dist_to_cover > 10:
            # Move towards cover
            dir_to_cover = (cover_pos - enemy.pos).normalized()
            enemy.vel = dir_to_cover * enemy.speed
            enemy.pos = enemy.pos + enemy.vel * dt
        else:
            # In cover, peek to shoot
            enemy.attack_cd -= dt
            if enemy.attack_cd <= 0:
                # Peek
                peek_pos = enemy.pos + (player_pos - enemy.pos).normalized() * 30
                
                # Shoot
                proj_speed = 235.0 + state.wave * 3
                aim = _lead_dir(peek_pos, player_pos, player_vel, proj_speed, mult=0.75)
                vel = aim * proj_speed
                state.projectiles.append(Projectile(peek_pos, vel, 8 + state.wave // 2, ttl=2.6, owner="enemy"))
                enemy.attack_cd = 2.0 + random.uniform(0.0, 0.5)

    def _do_kiting_behavior(self, enemy, player_pos, state, dt, player_vel):
        """Keep a certain distance and fire."""
        dvec = player_pos - enemy.pos
        d = dvec.length()
        dir_to = dvec.normalized() if d > 1e-6 else Vec2(1.0, 0.0)
        sign = -1.0 if (id(enemy) % 2) else 1.0
        strafe = _perp(dir_to) * sign
        wobble = Vec2(math.sin(enemy.t * 1.4 + enemy.seed), math.cos(enemy.t * 1.7 + enemy.seed)) * 0.25

        if d > self.desired_max_dist:
            move = (dir_to * 0.95 + self._separation(enemy, state.enemies) * 0.8 + wobble).normalized()
            speed_mult = 0.95
        elif d < self.desired_min_dist:
            move = ((dir_to * -1.0) * 0.95 + self._separation(enemy, state.enemies) + wobble).normalized()
            speed_mult = 0.95
        else:
            move = (strafe * 0.85 + dir_to * 0.15 + self._separation(enemy, state.enemies) * 0.9 + wobble).normalized()
            speed_mult = 0.75

        enemy.vel = move * (enemy.speed * speed_mult)
        enemy.pos = enemy.pos + enemy.vel * dt

        enemy.attack_cd -= dt
        if enemy.attack_cd <= 0.0 and d < 320:
            proj_speed = 235.0 + state.wave * 3
            aim = _lead_dir(enemy.pos, player_pos, player_vel, proj_speed, mult=0.75)
            vel = aim * proj_speed
            state.projectiles.append(Projectile(enemy.pos, vel, 8 + state.wave // 2, ttl=2.6, owner="enemy"))
            enemy.attack_cd = 1.15 + random.uniform(0.0, 0.35)

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
