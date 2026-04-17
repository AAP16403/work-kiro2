"""Thunder boss behavior."""
from enemy_behaviors.base import Behavior
from utils import Vec2
from hazards import ThunderLine
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

class ThunderBoss(Behavior):
    """A thunder boss behavior."""

    def update(self, enemy, player_pos, state, dt, player_vel):
        """Update the enemy's state based on its behavior."""
        dvec = player_pos - enemy.pos
        d = dvec.length()
        dir_to = dvec.normalized() if d > 1e-6 else Vec2(1, 0)
        phase = int(enemy.ai.get("phase", 0))
        persona = str(enemy.ai.get("persona", "aggressive"))

        desired = 230.0
        if persona == "aggressive":
            desired = 205.0
        elif persona == "cautious":
            desired = 265.0
        if d > desired:
            enemy.pos = enemy.pos + dir_to * enemy.speed * dt * 0.9
        else:
            strafe = Vec2(-dir_to.y, dir_to.x)
            enemy.pos = enemy.pos + strafe * enemy.speed * dt * 0.9

        enemy.attack_cd -= dt
        if enemy.attack_cd <= 0.0:
            if not hasattr(state, "thunders"):
                state.thunders = []

            angle = random.uniform(0, math.tau)
            dirv = Vec2(math.cos(angle), math.sin(angle))
            perp = Vec2(-dirv.y, dirv.x)
            offset = random.uniform(-110, 110)
            anchor = player_pos + perp * offset
            span = config.ROOM_RADIUS * 2.2
            start = anchor - dirv * span
            end = anchor + dirv * span
            th_dmg = 14 + state.wave // 5
            state.thunders.append(ThunderLine(start=start, end=end, damage=th_dmg, thickness=14.0, warn=0.55, ttl=0.16))

            # Personality + phases: mix in bullet patterns. Swirl/rings are rare to keep difficulty fair.
            proj_speed = 195.0 + state.wave * 1.8
            dmg = 5 + state.wave // 4
            aim = _lead_dir(enemy.pos, player_pos, player_vel, proj_speed, mult=0.8)
            gun = _cycle_gun(enemy, ["plasma", "bullet", "spread"])
            if phase == 0:
                if persona != "cautious":
                    _fire_fan(state, enemy.pos, aim, count=4, spread_deg=50.0, speed=proj_speed, damage=dmg, ttl=2.5, projectile_type=gun)
            elif phase == 1:
                _fire_fan(state, enemy.pos, aim, count=5, spread_deg=62.0, speed=proj_speed, damage=dmg + 1, ttl=2.6, projectile_type=gun)
            else:
                swirl_chance = 0.12
                if persona == "trickster":
                    swirl_chance = 0.25
                if random.random() < swirl_chance:
                    ring_gun = _cycle_gun(enemy, ["plasma", "bullet"])
                    _fire_ring(
                        state,
                        enemy.pos,
                        count=8,
                        speed=proj_speed * 0.88,
                        damage=dmg + 1,
                        ttl=2.55,
                        start_deg=enemy.t * 35.0,
                        projectile_type=ring_gun,
                    )
                else:
                    _fire_fan(state, enemy.pos, aim, count=7, spread_deg=76.0, speed=proj_speed, damage=dmg + 2, ttl=2.6, projectile_type=gun)

            # Henchmen: spawn a couple of ranged adds sometimes.
            adds_cap = getattr(state, "max_enemies", 12) + 2
            from enemy import Enemy
            if len(getattr(state, "enemies", [])) < adds_cap and random.random() < 0.22:
                ang = random.uniform(0, math.tau)
                pos = enemy.pos + Vec2(math.cos(ang), math.sin(ang)) * random.uniform(45, 80)
                state.enemies.append(Enemy(pos=pos, hp=14 + state.wave * 2, speed=50 + state.wave * 1.25, behavior="ranged"))

            base_cd = 1.95 - state.wave * 0.015
            if phase == 1:
                base_cd *= 0.95
            elif phase == 2:
                base_cd *= 0.9
            if persona == "aggressive":
                base_cd *= 0.95
            enemy.attack_cd = max(0.9, base_cd)
