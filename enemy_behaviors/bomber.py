"""Bomber behavior for enemies."""

import random

from enemy_behaviors.base import Behavior
from projectile import Projectile
from utils import Vec2


def _lead_dir(shooter_pos: Vec2, target_pos: Vec2, target_vel: Vec2, proj_speed: float, mult: float = 0.85) -> Vec2:
    d = (target_pos - shooter_pos).length()
    t = (d / max(1.0, float(proj_speed))) * float(mult)
    aim_pos = Vec2(target_pos.x + target_vel.x * t, target_pos.y + target_vel.y * t)
    return (aim_pos - shooter_pos).normalized()


class Bomber(Behavior):
    """Mid-range kiter that throws timed bomb projectiles."""

    def update(self, enemy, player_pos, state, dt, player_vel, game=None):
        dvec = player_pos - enemy.pos
        dist_to_player = dvec.length()
        dir_to = dvec.normalized() if dist_to_player > 1e-6 else Vec2(1.0, 0.0)

        # Keep a medium distance so bomb throws are readable and dodgeable.
        sep = self._separation(enemy, state.enemies, radius=44.0, weight=1.2)
        if dist_to_player < 130.0:
            move = ((dir_to * -1.0) + sep).normalized()
            speed_mult = 1.05
        elif dist_to_player > 250.0:
            move = (dir_to + sep * 0.8).normalized()
            speed_mult = 0.9
        else:
            move = (sep + Vec2(-dir_to.y, dir_to.x) * (1.0 if (id(enemy) % 2) else -1.0) * 0.65).normalized()
            speed_mult = 0.75

        enemy.vel = move * enemy.speed * speed_mult
        enemy.pos = enemy.pos + enemy.vel * dt

        # Throw bombs at a cadence; bombs explode in gameplay update logic.
        enemy.attack_cd -= dt
        if enemy.attack_cd <= 0.0 and dist_to_player < 360.0:
            bomb_speed = 115.0 + state.wave * 1.8
            aim = _lead_dir(enemy.pos, player_pos, player_vel, bomb_speed, mult=0.95)
            jitter = random.uniform(-10.0, 10.0)
            c = random.random()
            if c < 0.5:
                aim = Vec2(aim.x * (1.0 + jitter * 0.005), aim.y * (1.0 - jitter * 0.005)).normalized()
            bomb_damage = 14 + state.wave // 3
            fuse = 1.1 + random.uniform(0.0, 0.35)
            state.projectiles.append(
                Projectile(
                    pos=Vec2(enemy.pos.x, enemy.pos.y),
                    vel=aim * bomb_speed,
                    damage=bomb_damage,
                    ttl=fuse,
                    owner="enemy",
                    projectile_type="bomb",
                )
            )
            enemy.attack_cd = 2.0 + random.uniform(0.2, 0.7)

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
