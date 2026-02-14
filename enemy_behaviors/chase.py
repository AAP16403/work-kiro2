"""Chase behavior for enemies."""
from enemy_behaviors.base import Behavior
from utils import Vec2
import math
import random

def _perp(v: Vec2) -> Vec2:
    return Vec2(-v.y, v.x)

class Chase(Behavior):
    """A simple chase behavior."""

    def update(self, enemy, player_pos, state, dt, player_vel):
        """Update the enemy's state based on its behavior."""
        if "lunge_cd" not in enemy.ai:
            enemy.ai["lunge_cd"] = random.uniform(0.4, 1.2)
        if "lunge_t" not in enemy.ai:
            enemy.ai["lunge_t"] = 0.0
        if "orbit_sign" not in enemy.ai:
            enemy.ai["orbit_sign"] = 1.0 if ((int(enemy.seed * 1000) + id(enemy)) % 2) else -1.0

        dist_to_player = (player_pos - enemy.pos).length()
        look_ahead_time = dist_to_player / enemy.speed if enemy.speed > 0 else 0
        predicted_player_pos = player_pos + player_vel * look_ahead_time

        dir_to = (predicted_player_pos - enemy.pos).normalized()
        orbit = _perp(dir_to) * enemy.ai["orbit_sign"]
        zig = _perp(dir_to) * (0.18 * math.sin(enemy.t * 2.6 + enemy.seed))
        dodge = self._dodge_player_projectiles(enemy, getattr(state, "projectiles", []))
        sep = self._separation(enemy, state.enemies, radius=44.0, weight=1.1)

        pressure = 0.0
        if dist_to_player < 160:
            pressure = (160 - dist_to_player) / 160.0

        enemy.ai["lunge_cd"] -= dt
        enemy.ai["lunge_t"] = max(0.0, float(enemy.ai["lunge_t"]) - dt)

        if enemy.ai["lunge_t"] <= 0.0 and enemy.ai["lunge_cd"] <= 0.0 and 80.0 < dist_to_player < 240.0:
            enemy.ai["lunge_t"] = 0.28 + random.uniform(0.0, 0.1)
            enemy.ai["lunge_cd"] = 1.4 + random.uniform(0.0, 0.6)
            enemy.ai["lunge_dir"] = (player_pos + player_vel * 0.22 - enemy.pos).normalized()

        if enemy.ai["lunge_t"] > 0.0:
            lunge_dir = enemy.ai.get("lunge_dir", dir_to)
            move = (lunge_dir + dodge * 0.4 + sep * 0.3).normalized()
            speed_mult = 1.7
        else:
            move = (
                dir_to * (1.0 + pressure * 0.25)
                + orbit * (0.28 + pressure * 0.35)
                + zig
                + sep
                + dodge * 1.05
            ).normalized()
            speed_mult = 1.0 + pressure * 0.22

        enemy.vel = move * enemy.speed * speed_mult
        enemy.pos = enemy.pos + enemy.vel * dt

    def _separation(self, enemy, others, radius: float, weight: float = 1.0) -> Vec2:
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

    def _dodge_player_projectiles(self, enemy, projectiles, danger_radius: float = 70.0) -> Vec2:
        steer = Vec2(0.0, 0.0)
        count = 0
        for p in projectiles:
            if getattr(p, "owner", "") != "player":
                continue
            rel = enemy.pos - p.pos
            d2 = rel.length_squared()
            if d2 > danger_radius * danger_radius:
                continue
            v = getattr(p, "vel", Vec2(0.0, 0.0))
            if v.length_squared() <= 1e-6:
                continue
            toward = rel.dot(v.normalized())
            if toward >= 0.0:
                continue
            evade = _perp(v.normalized())
            side = 1.0 if rel.dot(evade) >= 0.0 else -1.0
            weight = 1.0 - (math.sqrt(d2) / danger_radius)
            steer += evade * (side * weight)
            count += 1
            if count >= 4:
                break
        if count == 0:
            return Vec2(0.0, 0.0)
        return (steer / count).normalized()
