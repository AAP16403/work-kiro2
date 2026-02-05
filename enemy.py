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
    import random
    import config
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

    if enemy.behavior == "engineer":
        # Maintains distance and deploys traps.
        dvec = player_pos - enemy.pos
        d = dvec.length()
        dir_to = dvec.normalized() if d > 1e-6 else Vec2(0, 0)

        if d > 260:
            enemy.pos = enemy.pos + dir_to * enemy.speed * dt * 0.85
        elif d < 180:
            enemy.pos = enemy.pos - dir_to * enemy.speed * dt * 0.95
        else:
            strafe = Vec2(-dir_to.y, dir_to.x)
            enemy.pos = enemy.pos + strafe * enemy.speed * dt * 0.75

        enemy.attack_cd -= dt
        if enemy.attack_cd <= 0.0 and d < 420:
            try:
                from hazards import Trap

                if not hasattr(state, "traps"):
                    state.traps = []
                state.traps.append(Trap(pos=Vec2(enemy.pos.x, enemy.pos.y), radius=28.0, damage=16, ttl=10.0))
            except Exception:
                pass
            enemy.attack_cd = 2.4
        return

    # -----------------
    # Boss behaviors
    # -----------------
    if enemy.behavior == "boss_thunder":
        # Slow orbit around player, then call down lightning lines across the room.
        dvec = player_pos - enemy.pos
        d = dvec.length()
        dir_to = dvec.normalized() if d > 1e-6 else Vec2(1, 0)

        desired = 230.0
        if d > desired:
            enemy.pos = enemy.pos + dir_to * enemy.speed * dt * 0.9
        else:
            strafe = Vec2(-dir_to.y, dir_to.x)
            enemy.pos = enemy.pos + strafe * enemy.speed * dt * 0.9

        enemy.attack_cd -= dt
        if enemy.attack_cd <= 0.0:
            try:
                from hazards import ThunderLine

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
                state.thunders.append(ThunderLine(start=start, end=end, damage=20, thickness=18.0, warn=0.45, ttl=0.18))
            except Exception:
                pass

            # Henchmen: spawn a couple of ranged adds sometimes.
            if len(getattr(state, "enemies", [])) < getattr(state, "max_enemies", 12) + 4 and random.random() < 0.35:
                for _ in range(2):
                    ang = random.uniform(0, math.tau)
                    pos = enemy.pos + Vec2(math.cos(ang), math.sin(ang)) * random.uniform(40, 70)
                    state.enemies.append(Enemy(pos=pos, hp=18 + state.wave * 3, speed=55 + state.wave * 1.4, behavior="ranged"))
            enemy.attack_cd = max(0.8, 1.6 - state.wave * 0.02)
        return

    if enemy.behavior == "boss_laser":
        # Erratic movement, rapid laser beams.
        dvec = player_pos - enemy.pos
        d = dvec.length()
        dir_to = dvec.normalized() if d > 1e-6 else Vec2(1, 0)
        wobble = Vec2(math.sin(enemy.t * 2.7), math.cos(enemy.t * 3.1))
        move = (dir_to * 0.6 + Vec2(-dir_to.y, dir_to.x) * 0.55 + wobble * 0.35).normalized()
        enemy.pos = enemy.pos + move * enemy.speed * dt * (0.85 + 0.35 * math.sin(enemy.t * 3.0))

        enemy.attack_cd -= dt
        if enemy.attack_cd <= 0.0 and d < config.ROOM_RADIUS * 1.6:
            try:
                from hazards import LaserBeam

                if not hasattr(state, "lasers"):
                    state.lasers = []
                beam_len = config.ROOM_RADIUS * 2.0
                start = Vec2(enemy.pos.x, enemy.pos.y)
                end = start + dir_to * beam_len
                state.lasers.append(
                    LaserBeam(
                        start=start,
                        end=end,
                        damage=22 + state.wave // 2,
                        thickness=14.0,
                        warn=0.35,
                        ttl=0.12,
                        color=(255, 120, 255),
                        owner="enemy",
                    )
                )
            except Exception:
                pass

            # Henchmen: occasional fast chasers.
            if len(getattr(state, "enemies", [])) < getattr(state, "max_enemies", 12) + 5 and random.random() < 0.25:
                ang = random.uniform(0, math.tau)
                pos = enemy.pos + Vec2(math.cos(ang), math.sin(ang)) * random.uniform(50, 90)
                state.enemies.append(Enemy(pos=pos, hp=16 + state.wave * 3, speed=90 + state.wave * 2.2, behavior="chaser"))
            enemy.attack_cd = max(0.25, 0.9 - state.wave * 0.02)
        return

    if enemy.behavior == "boss_trapmaster":
        # Places trap patterns while staying mid-range.
        dvec = player_pos - enemy.pos
        d = dvec.length()
        dir_to = dvec.normalized() if d > 1e-6 else Vec2(1, 0)
        if d > 320:
            enemy.pos = enemy.pos + dir_to * enemy.speed * dt * 0.85
        elif d < 200:
            enemy.pos = enemy.pos - dir_to * enemy.speed * dt * 0.95
        else:
            strafe = Vec2(-dir_to.y, dir_to.x)
            enemy.pos = enemy.pos + strafe * enemy.speed * dt

        enemy.attack_cd -= dt
        if enemy.attack_cd <= 0.0:
            try:
                from hazards import Trap

                if not hasattr(state, "traps"):
                    state.traps = []
                # Ring of traps around the player.
                n = 5
                r = 85
                base_ang = random.uniform(0, math.tau)
                for i in range(n):
                    ang = base_ang + (i / n) * math.tau
                    pos = player_pos + Vec2(math.cos(ang), math.sin(ang)) * r
                    state.traps.append(Trap(pos=pos, radius=30.0, damage=18, ttl=9.0, armed_delay=0.55, kind="spike"))
            except Exception:
                pass

            # Henchmen: engineers join the fight.
            if len(getattr(state, "enemies", [])) < getattr(state, "max_enemies", 12) + 4 and random.random() < 0.4:
                pos = enemy.pos + Vec2(random.uniform(-70, 70), random.uniform(-70, 70))
                state.enemies.append(Enemy(pos=pos, hp=26 + state.wave * 4, speed=55 + state.wave * 1.3, behavior="engineer"))
            enemy.attack_cd = max(1.2, 2.2 - state.wave * 0.03)
        return

    if enemy.behavior == "boss_swarmqueen":
        # Summons swarms and spits projectiles.
        dvec = player_pos - enemy.pos
        d = dvec.length()
        dir_to = dvec.normalized() if d > 1e-6 else Vec2(1, 0)
        strafe = Vec2(-dir_to.y, dir_to.x)
        enemy.pos = enemy.pos + (strafe * 0.9 + dir_to * 0.3).normalized() * enemy.speed * dt * 0.75

        enemy.attack_cd -= dt
        if enemy.attack_cd <= 0.0:
            # Summon a few swarm enemies.
            for _ in range(3):
                ang = random.uniform(0, math.tau)
                pos = enemy.pos + Vec2(math.cos(ang), math.sin(ang)) * random.uniform(30, 60)
                state.enemies.append(Enemy(pos=pos, hp=14 + state.wave * 2, speed=95 + state.wave * 1.5, behavior="swarm"))

            # Spit a fan of shots.
            for off in (-24, -8, 8, 24):
                a = math.radians(off)
                cos_a = math.cos(a)
                sin_a = math.sin(a)
                vx = dir_to.x * cos_a - dir_to.y * sin_a
                vy = dir_to.x * sin_a + dir_to.y * cos_a
                vel = Vec2(vx, vy) * (210.0 + state.wave * 2.5)
                state.projectiles.append(Projectile(enemy.pos, vel, 8 + state.wave // 3, ttl=2.6, owner="enemy"))

            enemy.attack_cd = max(1.0, 2.0 - state.wave * 0.02)
        return

    if enemy.behavior == "boss_brute":
        # Big charges and slam zones.
        dvec = player_pos - enemy.pos
        d = dvec.length()
        dir_to = dvec.normalized() if d > 1e-6 else Vec2(1, 0)
        phase = enemy.t % 2.0
        if phase < 0.55:
            enemy.pos = enemy.pos + dir_to * enemy.speed * dt * 2.6
        else:
            enemy.pos = enemy.pos + dir_to * enemy.speed * dt * 0.6

        enemy.attack_cd -= dt
        if enemy.attack_cd <= 0.0:
            # Slam: immediate damage if close and a temporary hazard ring.
            try:
                from hazards import Trap

                if not hasattr(state, "traps"):
                    state.traps = []
                # Telegraph then strike.
                state.traps.append(Trap(pos=Vec2(enemy.pos.x, enemy.pos.y), radius=80.0, damage=0, ttl=0.8, armed_delay=0.35, kind="slam_warn"))
                state.traps.append(Trap(pos=Vec2(enemy.pos.x, enemy.pos.y), radius=70.0, damage=26, ttl=0.55, armed_delay=0.35, kind="slam"))
            except Exception:
                pass
            enemy.attack_cd = max(1.1, 2.0 - state.wave * 0.02)
        return
