"""Laser boss behavior."""
from enemy_behaviors.base import Behavior
from utils import Vec2
from hazards import LaserBeam
from projectile import Projectile
import math
import random
import config

def _lead_dir(shooter_pos: Vec2, target_pos: Vec2, target_vel: Vec2, proj_speed: float, mult: float = 0.75) -> Vec2:
    d = (target_pos - shooter_pos).length()
    t = (d / max(1.0, float(proj_speed))) * float(mult)
    aim_pos = Vec2(target_pos.x + target_vel.x * t, target_pos.y + target_vel.y * t)
    return (aim_pos - shooter_pos).normalized()

def _rotate(v: Vec2, deg: float) -> Vec2:
    a = math.radians(deg)
    cos_a = math.cos(a)
    sin_a = math.sin(a)
    return Vec2(v.x * cos_a - v.y * sin_a, v.x * sin_a + v.y * cos_a)

def _fire_fan(
    state,
    origin: Vec2,
    aim: Vec2,
    count: int,
    spread_deg: float,
    speed: float,
    damage: int,
    ttl: float = 2.6,
    projectile_type: str = "bullet",
):
    """Fire a spread/fan of enemy bullets around an aim direction."""
    ptype = str(projectile_type or "bullet")
    n = max(1, int(count))
    if n == 1:
        state.projectiles.append(Projectile(origin, aim * float(speed), int(damage), ttl=float(ttl), owner="enemy", projectile_type=ptype))
        return
    step = float(spread_deg) / float(n - 1) if n > 1 else 0.0
    start = -float(spread_deg) * 0.5
    for i in range(n):
        d = _rotate(aim, start + step * i)
        state.projectiles.append(Projectile(origin, d * float(speed), int(damage), ttl=float(ttl), owner="enemy", projectile_type=ptype))

class LaserBoss(Behavior):
    """A laser boss behavior."""

    def update(self, enemy, player_pos, state, dt, player_vel):
        """Update the enemy's state based on its behavior."""
        dvec = player_pos - enemy.pos
        d = dvec.length()
        dir_to = dvec.normalized() if d > 1e-6 else Vec2(1, 0)
        phase = int(enemy.ai.get("phase", 0))
        persona = str(enemy.ai.get("persona", "aggressive"))
        wobble = Vec2(math.sin(enemy.t * 2.7), math.cos(enemy.t * 3.1))
        move = (dir_to * 0.6 + Vec2(-dir_to.y, dir_to.x) * 0.55 + wobble * 0.35).normalized()
        move_mult = (0.85 + 0.35 * math.sin(enemy.t * 3.0))
        if persona == "trickster":
            move_mult *= 1.12
        enemy.pos = enemy.pos + move * enemy.speed * dt * move_mult

        enemy.attack_cd -= dt
        if enemy.attack_cd <= 0.0 and d < config.ROOM_RADIUS * 1.6:
            if not hasattr(state, "lasers"):
                state.lasers = []
            beam_len = config.ROOM_RADIUS * 2.0
            start = Vec2(enemy.pos.x, enemy.pos.y)
            end = start + dir_to * beam_len
            beam_dmg = 16 + state.wave // 3
            state.lasers.append(
                LaserBeam(
                    start=start,
                    end=end,
                    damage=beam_dmg,
                    thickness=12.0,
                    warn=0.42,
                    ttl=0.10,
                    color=(255, 120, 255),
                    owner="enemy",
                )
            )
            if phase >= 1:
                # Slightly offset follow-up beams for a "sweep" feel.
                offsets = (-24, 24) if phase == 1 else (-34, 34)
                for off in offsets:
                    d2 = _rotate(dir_to, off)
                    state.lasers.append(
                        LaserBeam(
                            start=start,
                            end=start + d2 * beam_len,
                            damage=12 + state.wave // 3,
                            thickness=9.0,
                            warn=0.46 if phase == 1 else 0.4,
                            ttl=0.09,
                            color=(255, 120, 255),
                            owner="enemy",
                        )
                    )

            # Mix-in: shotgun bursts later in the fight (or for tricksters).
            if (phase == 2 and random.random() < 0.45) or (persona == "trickster" and phase >= 1 and random.random() < 0.35):
                proj_speed = 235.0 + state.wave * 2.2
                dmg = 5 + state.wave // 5
                aim = _lead_dir(enemy.pos, player_pos, player_vel, proj_speed, mult=0.75)
                pellets = 4 if phase == 1 else 6
                spread = 66.0 if phase == 1 else 76.0
                _fire_fan(state, enemy.pos, aim, count=pellets, spread_deg=spread, speed=proj_speed, damage=dmg, ttl=2.5, projectile_type="plasma" if persona == "trickster" else "bullet")

            # Henchmen: occasional fast chasers.
            from enemy import Enemy
            adds_cap = getattr(state, "max_enemies", 12) + 2
            if len(getattr(state, "enemies", [])) < adds_cap and random.random() < 0.15:
                ang = random.uniform(0, math.tau)
                pos = enemy.pos + Vec2(math.cos(ang), math.sin(ang)) * random.uniform(50, 90)
                state.enemies.append(Enemy(pos=pos, hp=14 + state.wave * 2, speed=85 + state.wave * 2.0, behavior="chaser"))

            base_cd = 1.15 - state.wave * 0.015
            if phase == 2:
                base_cd *= 0.92
            if persona == "aggressive":
                base_cd *= 0.95
            enemy.attack_cd = max(0.5, base_cd)
