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
        if "burst_left" not in enemy.ai:
            enemy.ai["burst_left"] = 0
        if "burst_gap" not in enemy.ai:
            enemy.ai["burst_gap"] = 0.0
        if "relocate_t" not in enemy.ai:
            enemy.ai["relocate_t"] = 0.0
        if "strafe_sign" not in enemy.ai:
            enemy.ai["strafe_sign"] = 1.0 if (id(enemy) % 2) else -1.0
        
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
        strafe = _perp(dir_to) * float(enemy.ai.get("strafe_sign", 1.0))
        wobble = Vec2(math.sin(enemy.t * 1.4 + enemy.seed), math.cos(enemy.t * 1.7 + enemy.seed)) * 0.25
        dodge = self._dodge_player_projectiles(enemy, getattr(state, "projectiles", []))
        relocate_t = float(enemy.ai.get("relocate_t", 0.0))
        enemy.ai["relocate_t"] = max(0.0, relocate_t - dt)

        if d > self.desired_max_dist:
            move = (dir_to * 0.95 + self._separation(enemy, state.enemies) * 0.8 + wobble + dodge * 0.9).normalized()
            speed_mult = 0.95
        elif d < self.desired_min_dist:
            move = ((dir_to * -1.0) * 0.95 + self._separation(enemy, state.enemies) + wobble + dodge * 1.15).normalized()
            speed_mult = 0.95
        else:
            lateral = strafe * (1.0 if enemy.ai["relocate_t"] > 0.0 else 0.72)
            move = (lateral + dir_to * 0.1 + self._separation(enemy, state.enemies) * 0.9 + wobble + dodge).normalized()
            speed_mult = 0.75

        enemy.vel = move * (enemy.speed * speed_mult)
        enemy.pos = enemy.pos + enemy.vel * dt

        enemy.attack_cd -= dt
        enemy.ai["burst_gap"] = max(0.0, float(enemy.ai.get("burst_gap", 0.0)) - dt)

        if d < 330 and enemy.attack_cd <= 0.0:
            if enemy.ai["burst_left"] <= 0:
                enemy.ai["burst_left"] = random.randint(1, 2)
                enemy.ai["burst_gap"] = 0.0

            if enemy.ai["burst_gap"] <= 0.0:
                proj_speed = 205.0 + state.wave * 2.2
                aim = _lead_dir(enemy.pos, player_pos, player_vel, proj_speed, mult=0.78)
                if enemy.ai["burst_left"] == 1:
                    aim = _lead_dir(enemy.pos, player_pos, player_vel, proj_speed, mult=0.66)
                # Light inaccuracy so sustained fire is dodgeable.
                aim_jitter = random.uniform(-7.0, 7.0)
                ca = math.cos(math.radians(aim_jitter))
                sa = math.sin(math.radians(aim_jitter))
                aim = Vec2(aim.x * ca - aim.y * sa, aim.x * sa + aim.y * ca).normalized()
                vel = aim * proj_speed
                state.projectiles.append(Projectile(enemy.pos, vel, 6 + state.wave // 3, ttl=2.4, owner="enemy"))
                enemy.ai["burst_left"] -= 1
                enemy.ai["burst_gap"] = 0.16 + random.uniform(0.0, 0.08)
                if enemy.ai["burst_left"] <= 0:
                    enemy.attack_cd = 1.45 + random.uniform(0.2, 0.55)
                    enemy.ai["relocate_t"] = 0.5 + random.uniform(0.0, 0.6)
                    enemy.ai["strafe_sign"] *= -1.0
                else:
                    enemy.attack_cd = 0.0

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

    def _dodge_player_projectiles(self, enemy, projectiles, danger_radius: float = 90.0) -> Vec2:
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
            side = _perp(vel.normalized())
            side_sign = 1.0 if rel.dot(side) >= 0 else -1.0
            steer += side * side_sign * (1.0 - (math.sqrt(d2) / danger_radius))
            count += 1
            if count >= 4:
                break
        if count == 0:
            return Vec2(0.0, 0.0)
        return (steer / count).normalized()
