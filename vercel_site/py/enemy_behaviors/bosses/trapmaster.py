"""Trapmaster boss behavior."""
from enemy_behaviors.base import Behavior
from utils import Vec2
from hazards import Trap
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

def _append_trap_capped(state, trap: Trap) -> bool:
    """Append trap only if construction cap has room."""
    if not hasattr(state, "traps"):
        state.traps = []
    cap = max(0, int(getattr(config, "MAX_ACTIVE_CONSTRUCTIONS", 14)))
    if len(state.traps) >= cap:
        return False
    state.traps.append(trap)
    return True

class TrapmasterBoss(Behavior):
    """A trapmaster boss behavior."""

    def update(self, enemy, player_pos, state, dt, player_vel):
        """Update the enemy's state based on its behavior."""
        dvec = player_pos - enemy.pos
        d = dvec.length()
        dir_to = dvec.normalized() if d > 1e-6 else Vec2(1, 0)
        phase = int(enemy.ai.get("phase", 0))
        persona = str(enemy.ai.get("persona", "aggressive"))
        if d > 320:
            enemy.pos = enemy.pos + dir_to * enemy.speed * dt * 0.85
        elif d < 200:
            enemy.pos = enemy.pos - dir_to * enemy.speed * dt * 0.95
        else:
            strafe = Vec2(-dir_to.y, dir_to.x)
            enemy.pos = enemy.pos + strafe * enemy.speed * dt

        enemy.attack_cd -= dt
        if enemy.attack_cd <= 0.0:
            if not hasattr(state, "traps"):
                state.traps = []
            # Ring of traps around the player.
            n = 4
            r = 85
            base_ang = random.uniform(0, math.tau)
            for i in range(n):
                ang = base_ang + (i / n) * math.tau
                pos = player_pos + Vec2(math.cos(ang), math.sin(ang)) * r
                _append_trap_capped(state, Trap(pos=pos, radius=30.0, damage=18, ttl=9.0, armed_delay=0.55, kind="spike"))

            # Phases: add shrapnel bursts after trap placement (no swirl/ring spam).
            proj_speed = 200.0 + state.wave * 2.0
            dmg = 7 + state.wave // 4
            aim = _lead_dir(enemy.pos, player_pos, player_vel, proj_speed, mult=0.85)
            if phase == 0:
                if persona != "cautious":
                    _fire_fan(state, enemy.pos, aim, count=5, spread_deg=60.0, speed=proj_speed, damage=dmg, ttl=2.6, projectile_type="spread")
            elif phase == 1:
                _fire_fan(state, enemy.pos, aim, count=7, spread_deg=85.0, speed=proj_speed, damage=dmg + 1, ttl=2.7, projectile_type="spread")
            else:
                _fire_fan(state, enemy.pos, aim, count=9, spread_deg=98.0, speed=proj_speed, damage=dmg + 2, ttl=2.65, projectile_type="spread")
                if persona in ("aggressive", "trickster"):
                    _fire_fan(state, enemy.pos, Vec2(-aim.y, aim.x), count=5, spread_deg=46.0, speed=proj_speed * 0.95, damage=max(1, dmg), ttl=2.45, projectile_type="spread")

            # Henchmen: engineers join the fight.
            from enemy import Enemy
            adds_cap = getattr(state, "max_enemies", 12) + 2
            if len(getattr(state, "enemies", [])) < adds_cap and random.random() < 0.2:
                pos = enemy.pos + Vec2(random.uniform(-70, 70), random.uniform(-70, 70))
                state.enemies.append(Enemy(pos=pos, hp=22 + state.wave * 3, speed=52 + state.wave * 1.2, behavior="engineer"))
            base_cd = 2.2 - state.wave * 0.03
            if phase >= 1:
                base_cd *= 0.9
            if persona == "aggressive":
                base_cd *= 0.92
            enemy.attack_cd = max(1.0, base_cd)
