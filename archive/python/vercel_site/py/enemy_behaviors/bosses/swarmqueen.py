"""Swarmqueen boss behavior."""
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

def _fire_ring(
    state,
    origin: Vec2,
    count: int,
    speed: float,
    damage: int,
    ttl: float = 2.8,
    start_deg: float = 0.0,
    projectile_type: str = "bullet",
):
    """Fire bullets in a full ring around the origin."""
    ptype = str(projectile_type or "bullet")
    n = max(3, int(count))
    base = float(start_deg)
    for i in range(n):
        a = base + (i / n) * 360.0
        d = Vec2(math.cos(math.radians(a)), math.sin(math.radians(a)))
        state.projectiles.append(Projectile(origin, d * float(speed), int(damage), ttl=float(ttl), owner="enemy", projectile_type=ptype))

def _cycle_gun(enemy, guns: list[str]) -> str:
    """Cycle through a list of projectile types for variety."""
    if not guns:
        return "bullet"
    idx = int(enemy.ai.get("gun_idx", 0))
    enemy.ai["gun_idx"] = idx + 1
    return str(guns[idx % len(guns)])

class SwarmQueenBoss(Behavior):
    """A swarmqueen boss behavior."""

    def update(self, enemy, player_pos, state, dt, player_vel):
        """Update the enemy's state based on its behavior."""
        dvec = player_pos - enemy.pos
        d = dvec.length()
        dir_to = dvec.normalized() if d > 1e-6 else Vec2(1, 0)
        phase = int(enemy.ai.get("phase", 0))
        persona = str(enemy.ai.get("persona", "aggressive"))
        strafe = Vec2(-dir_to.y, dir_to.x)
        enemy.pos = enemy.pos + (strafe * 0.9 + dir_to * 0.3).normalized() * enemy.speed * dt * 0.75

        enemy.attack_cd -= dt
        if enemy.attack_cd <= 0.0:
            # Summon a few swarm enemies (capped to avoid runaway difficulty/perf).
            from enemy import Enemy
            adds_cap = getattr(state, "max_enemies", 12) + 6
            slots = max(0, int(adds_cap) - len(getattr(state, "enemies", [])))
            for _ in range(min(2, slots)):
                ang = random.uniform(0, math.tau)
                pos = enemy.pos + Vec2(math.cos(ang), math.sin(ang)) * random.uniform(30, 60)
                state.enemies.append(Enemy(pos=pos, hp=12 + state.wave * 2, speed=92 + state.wave * 1.4, behavior="swarm"))

            # Spit a fan of shots.
            proj_speed = 210.0 + state.wave * 2.5
            dmg = 8 + state.wave // 3
            if phase == 0:
                for off in (-24, -8, 8, 24):
                    vel = _rotate(dir_to, off) * proj_speed
                    state.projectiles.append(Projectile(enemy.pos, vel, dmg, ttl=2.6, owner="enemy", projectile_type="bullet"))
            elif phase == 1:
                _fire_fan(state, enemy.pos, dir_to, count=7, spread_deg=95.0, speed=proj_speed, damage=dmg + 1, ttl=2.6, projectile_type="spread")
                if persona == "trickster":
                    # Extra side-shot.
                    _fire_fan(state, enemy.pos, Vec2(-dir_to.y, dir_to.x), count=3, spread_deg=24.0, speed=proj_speed * 0.95, damage=max(1, dmg - 1), ttl=2.4, projectile_type="spread")
            else:
                # Spiral burst: advance a stored angle for consistent "personality".
                ang = float(enemy.ai.get("spiral_deg", 0.0))
                enemy.ai["spiral_deg"] = ang + (72.0 if persona == "aggressive" else 58.0)
                base_dir = Vec2(math.cos(math.radians(ang)), math.sin(math.radians(ang)))

                gun = _cycle_gun(enemy, ["bullet", "spread", "plasma"])
                ring_n = 10
                ring_speed = proj_speed * 0.92
                ring_dmg = dmg + 2
                if gun == "plasma":
                    ring_n = 8
                    ring_speed = proj_speed * 0.86
                    ring_dmg = dmg + 3
                elif gun == "spread":
                    ring_n = 12
                    ring_speed = proj_speed * 0.98
                    ring_dmg = dmg + 1

                _fire_ring(state, enemy.pos, count=ring_n, speed=ring_speed, damage=ring_dmg, ttl=2.7, start_deg=ang, projectile_type=gun)
                _fire_fan(state, enemy.pos, base_dir, count=5, spread_deg=45.0, speed=proj_speed, damage=dmg + 1, ttl=2.6, projectile_type=gun)

            base_cd = 2.0 - state.wave * 0.02
            if phase == 2:
                base_cd *= 0.82
            if persona == "aggressive":
                base_cd *= 0.9
            enemy.attack_cd = max(0.85, base_cd)
