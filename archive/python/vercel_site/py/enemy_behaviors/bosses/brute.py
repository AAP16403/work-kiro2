"""Brute boss behavior."""
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

class BruteBoss(Behavior):
    """A brute boss behavior."""

    def update(self, enemy, player_pos, state, dt, player_vel):
        """Update the enemy's state based on its behavior."""
        dvec = player_pos - enemy.pos
        d = dvec.length()
        dir_to = dvec.normalized() if d > 1e-6 else Vec2(1, 0)
        phase_boss = int(enemy.ai.get("phase", 0))
        persona = str(enemy.ai.get("persona", "aggressive"))
        phase = enemy.t % 2.0
        if phase < 0.55:
            enemy.pos = enemy.pos + dir_to * enemy.speed * dt * 2.6
            if phase_boss >= 1 and random.random() < 0.06:
                proj_speed = 230.0 + state.wave * 2.0
                dmg = 8 + state.wave // 3
                aim = _lead_dir(enemy.pos, player_pos, player_vel, proj_speed, mult=0.7)
                _fire_fan(state, enemy.pos, aim, count=3 if phase_boss == 1 else 5, spread_deg=38.0, speed=proj_speed, damage=dmg, ttl=2.4)
        else:
            enemy.pos = enemy.pos + dir_to * enemy.speed * dt * 0.6

        enemy.attack_cd -= dt
        if enemy.attack_cd <= 0.0:
            # Slam: immediate damage if close and a temporary hazard ring.
            if not hasattr(state, "traps"):
                state.traps = []
            # Telegraph then strike.
            _append_trap_capped(state, Trap(pos=Vec2(enemy.pos.x, enemy.pos.y), radius=80.0, damage=0, ttl=0.8, armed_delay=0.35, kind="slam_warn"))
            _append_trap_capped(state, Trap(pos=Vec2(enemy.pos.x, enemy.pos.y), radius=70.0, damage=26, ttl=0.55, armed_delay=0.35, kind="slam"))
            if phase_boss >= 1:
                # Slam follow-up: heavy cone, not a full swirl ring.
                proj_speed = 200.0 + state.wave * 1.8
                dmg = 7 + state.wave // 4
                aim = _lead_dir(enemy.pos, player_pos, player_vel, proj_speed, mult=0.6)
                pellets = 7 if phase_boss == 1 else 9
                _fire_fan(
                    state,
                    Vec2(enemy.pos.x, enemy.pos.y),
                    aim,
                    count=pellets,
                    spread_deg=74.0,
                    speed=proj_speed,
                    damage=dmg + (1 if persona == "aggressive" else 0),
                    ttl=2.65,
                    projectile_type="spread",
                )

            base_cd = 2.0 - state.wave * 0.02
            if phase_boss == 2:
                base_cd *= 0.85
            if persona == "aggressive":
                base_cd *= 0.92
            enemy.attack_cd = max(0.95, base_cd)
