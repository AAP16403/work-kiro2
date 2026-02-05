"""Enemy entity and related functionality."""

from dataclasses import dataclass, field

from projectile import Projectile
from utils import Vec2


@dataclass
class Enemy:
    """Enemy entity."""
    pos: Vec2
    hp: int
    speed: float
    behavior: str  # "chaser", "ranged", "charger"
    t: float = 0.0
    attack_cd: float = 0.0


def update_enemy(enemy: Enemy, player_pos: Vec2, state, dt: float):
    """Update enemy AI behavior."""
    import math
    enemy.t += dt

    if enemy.behavior == "chaser":
        d = (player_pos - enemy.pos).normalized()
        enemy.pos = enemy.pos + d * enemy.speed * dt
        return

    if enemy.behavior == "ranged":
        # Keep a ring distance and occasionally fire.
        dvec = player_pos - enemy.pos
        d = dvec.length()
        dir_to = dvec.normalized()
        if d > 170:
            enemy.pos = enemy.pos + dir_to * enemy.speed * dt * 0.9
        elif d < 110:
            enemy.pos = enemy.pos - dir_to * enemy.speed * dt * 0.8
        else:
            strafe = Vec2(-dir_to.y, dir_to.x)
            enemy.pos = enemy.pos + strafe * enemy.speed * dt * 0.55

        enemy.attack_cd -= dt
        if enemy.attack_cd <= 0.0 and d < 240:
            # Enemy shot
            vel = dir_to * (220.0 + state.wave * 3)
            state.projectiles.append(Projectile(enemy.pos, vel, 8 + state.wave // 2, ttl=2.6, owner="enemy"))
            enemy.attack_cd = 1.3
        return

    if enemy.behavior == "charger":
        # Charge and retreat in cycles
        phase = (enemy.t % 1.2)
        dir_to = (player_pos - enemy.pos).normalized()
        if phase < 0.36:
            enemy.pos = enemy.pos + dir_to * enemy.speed * dt * 2.5
        else:
            enemy.pos = enemy.pos + dir_to * enemy.speed * dt * 0.55
        return

    if enemy.behavior == "swarm":
        # Weak but numerous, swarm around player
        dvec = player_pos - enemy.pos
        d = dvec.length()
        dir_to = dvec.normalized() if d > 1e-6 else Vec2(0, 0)
        # Orbit slightly before rushing
        if d > 80:
            enemy.pos = enemy.pos + dir_to * enemy.speed * dt
        else:
            # Swarm behavior: circle and attack
            angle_offset = enemy.t * 2
            circle_x = math.cos(angle_offset) * 40
            circle_y = math.sin(angle_offset) * 40
            target = Vec2(player_pos.x + circle_x, player_pos.y + circle_y)
            target_dir = (target - enemy.pos).normalized()
            enemy.pos = enemy.pos + target_dir * enemy.speed * dt * 0.8
        return

    if enemy.behavior == "tank":
        # Slow but tough, stops to attack
        dvec = player_pos - enemy.pos
        d = dvec.length()
        dir_to = dvec.normalized()
        if d > 100:
            # Move slowly toward player
            enemy.pos = enemy.pos + dir_to * enemy.speed * dt * 0.6
        # Stop and attack when close
        enemy.attack_cd -= dt
        if enemy.attack_cd <= 0.0 and d < 150:
            vel = dir_to * 180.0
            state.projectiles.append(Projectile(enemy.pos, vel, 12, ttl=2.8, owner="enemy"))
            enemy.attack_cd = 2.0
        return

    if enemy.behavior == "spitter":
        # Ranged spread fire, stays at distance
        dvec = player_pos - enemy.pos
        d = dvec.length()
        dir_to = dvec.normalized()
        # Maintain distance by strafing
        if d > 200:
            enemy.pos = enemy.pos + dir_to * enemy.speed * dt * 0.7
        elif d < 120:
            enemy.pos = enemy.pos - dir_to * enemy.speed * dt * 0.8
        else:
            strafe = Vec2(-dir_to.y, dir_to.x)
            enemy.pos = enemy.pos + strafe * enemy.speed * dt
        # Fire in spread pattern
        enemy.attack_cd -= dt
        if enemy.attack_cd <= 0.0 and d < 280:
            for angle_offset in [-30, 0, 30]:
                angle_rad = math.radians(angle_offset)
                cos_a = math.cos(angle_rad)
                sin_a = math.sin(angle_rad)
                vel_x = dir_to.x * cos_a - dir_to.y * sin_a
                vel_y = dir_to.x * sin_a + dir_to.y * cos_a
                vel = Vec2(vel_x, vel_y) * 200.0
                state.projectiles.append(Projectile(enemy.pos, vel, 6, ttl=2.5, owner="enemy"))
            enemy.attack_cd = 1.8
        return

    if enemy.behavior == "flyer":
        # Erratic flying pattern, unpredictable
        dvec = player_pos - enemy.pos
        d = dvec.length()
        dir_to = dvec.normalized() if d > 1e-6 else Vec2(0, 0)
        # Fly in sine wave pattern
        wave = math.sin(enemy.t * 3) * 0.5 + 0.5
        perpendicular = Vec2(-dir_to.y, dir_to.x)
        move_dir = dir_to * (1 - wave * 0.6) + perpendicular * wave * 0.8
        enemy.pos = enemy.pos + move_dir * enemy.speed * dt
        # Occasional rapid dashes
        if int(enemy.t * 2) % 4 == 0:
            enemy.pos = enemy.pos + dir_to * enemy.speed * dt * 1.5
        return
