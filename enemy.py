"""Enemy entity and related functionality."""

from dataclasses import dataclass, field
import math
import random

from hazards import Trap, LaserBeam, ThunderLine
from projectile import Projectile
import config
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
    vel: Vec2 = field(default_factory=lambda: Vec2(0.0, 0.0))
    seed: float = 0.0
    ai: dict = field(default_factory=dict)


def _perp(v: Vec2) -> Vec2:
    return Vec2(-v.y, v.x)


def _clamp(x: float, a: float, b: float) -> float:
    return a if x < a else b if x > b else x


def _separation(enemy: Enemy, others, radius: float, weight: float = 1.0) -> Vec2:
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


def _fire_fan(state, origin: Vec2, aim: Vec2, count: int, spread_deg: float, speed: float, damage: int, ttl: float = 2.6):
    """Fire a spread/fan of enemy bullets around an aim direction."""
    n = max(1, int(count))
    if n == 1:
        state.projectiles.append(Projectile(origin, aim * float(speed), int(damage), ttl=float(ttl), owner="enemy"))
        return
    step = float(spread_deg) / float(n - 1) if n > 1 else 0.0
    start = -float(spread_deg) * 0.5
    for i in range(n):
        d = _rotate(aim, start + step * i)
        state.projectiles.append(Projectile(origin, d * float(speed), int(damage), ttl=float(ttl), owner="enemy"))


def _fire_ring(state, origin: Vec2, count: int, speed: float, damage: int, ttl: float = 2.8, start_deg: float = 0.0):
    """Fire bullets in a full ring around the origin."""
    n = max(3, int(count))
    base = float(start_deg)
    for i in range(n):
        a = base + (i / n) * 360.0
        d = Vec2(math.cos(math.radians(a)), math.sin(math.radians(a)))
        state.projectiles.append(Projectile(origin, d * float(speed), int(damage), ttl=float(ttl), owner="enemy"))


def _boss_init(enemy: Enemy):
    if "max_hp" not in enemy.ai:
        enemy.ai["max_hp"] = int(enemy.hp)
    if "persona" not in enemy.ai:
        personas = ["aggressive", "cautious", "trickster"]
        enemy.ai["persona"] = personas[int(enemy.seed * 1000) % len(personas)]
    if "phase" not in enemy.ai:
        enemy.ai["phase"] = 0


def _boss_phase(enemy: Enemy) -> int:
    max_hp = max(1, int(enemy.ai.get("max_hp", enemy.hp)))
    r = float(enemy.hp) / float(max_hp)
    if r > 0.66:
        return 0
    if r > 0.33:
        return 1
    return 2


def update_enemy(enemy: Enemy, player_pos: Vec2, state, dt: float, player_vel: Vec2 | None = None):
    """Update enemy AI behavior."""
    if player_vel is None:
        player_vel = Vec2(0.0, 0.0)

    enemy.t += dt
    if enemy.seed == 0.0:
        enemy.seed = random.uniform(0.0, math.tau)

    sep = _separation(enemy, getattr(state, "enemies", []), radius=44.0, weight=1.1)

    if enemy.behavior.startswith("boss_"):
        _boss_init(enemy)
        new_phase = _boss_phase(enemy)
        if int(enemy.ai.get("phase", 0)) != new_phase:
            enemy.ai["phase"] = new_phase
            # Phase change: bring the next attack forward a bit.
            enemy.attack_cd = min(enemy.attack_cd, 0.35)

    if enemy.behavior == "chaser":
        # Pursuit + slight zig-zag + separation.
        target = Vec2(player_pos.x + player_vel.x * 0.35, player_pos.y + player_vel.y * 0.35)
        dir_to = (target - enemy.pos).normalized()
        zig = _perp(dir_to) * (0.22 * math.sin(enemy.t * 2.6 + enemy.seed))
        move = (dir_to + zig + sep).normalized()
        enemy.vel = move * enemy.speed
        enemy.pos = enemy.pos + enemy.vel * dt
        return

    if enemy.behavior == "ranged":
        # Keep a ring distance and occasionally fire.
        dvec = player_pos - enemy.pos
        d = dvec.length()
        dir_to = dvec.normalized() if d > 1e-6 else Vec2(1.0, 0.0)
        sign = -1.0 if (id(enemy) % 2) else 1.0
        strafe = _perp(dir_to) * sign
        wobble = Vec2(math.sin(enemy.t * 1.4 + enemy.seed), math.cos(enemy.t * 1.7 + enemy.seed)) * 0.25

        desired_min = 140.0
        desired_max = 220.0
        if d > desired_max:
            move = (dir_to * 0.95 + sep * 0.8 + wobble).normalized()
            speed_mult = 0.95
        elif d < desired_min:
            move = ((dir_to * -1.0) * 0.95 + sep + wobble).normalized()
            speed_mult = 0.95
        else:
            move = (strafe * 0.85 + dir_to * 0.15 + sep * 0.9 + wobble).normalized()
            speed_mult = 0.75

        enemy.vel = move * (enemy.speed * speed_mult)
        enemy.pos = enemy.pos + enemy.vel * dt

        enemy.attack_cd -= dt
        if enemy.attack_cd <= 0.0 and d < 320:
            # Enemy shot
            proj_speed = 235.0 + state.wave * 3
            aim = _lead_dir(enemy.pos, player_pos, player_vel, proj_speed, mult=0.75)
            vel = aim * proj_speed
            state.projectiles.append(Projectile(enemy.pos, vel, 8 + state.wave // 2, ttl=2.6, owner="enemy"))
            enemy.attack_cd = 1.15 + random.uniform(0.0, 0.35)
        return

    if enemy.behavior == "charger":
        # Charge and retreat in cycles
        phase = (enemy.t % 1.2)
        target = Vec2(player_pos.x + player_vel.x * 0.22, player_pos.y + player_vel.y * 0.22)
        dir_to = (target - enemy.pos).normalized()
        if phase < 0.36:
            move = (dir_to + sep * 0.6).normalized()
            enemy.vel = move * (enemy.speed * 2.6)
            enemy.pos = enemy.pos + enemy.vel * dt
        else:
            jitter = _perp(dir_to) * (0.18 * math.sin(enemy.t * 5.5 + enemy.seed))
            move = (dir_to * 0.7 + jitter + sep).normalized()
            enemy.vel = move * (enemy.speed * 0.7)
            enemy.pos = enemy.pos + enemy.vel * dt
        return

    if enemy.behavior == "swarm":
        # Boids-like flocking around the player (separation + alignment + cohesion) with an orbit bias.
        dvec = player_pos - enemy.pos
        dist_to_player = dvec.length()
        to_player = dvec.normalized() if dist_to_player > 1e-6 else Vec2(1.0, 0.0)

        neigh = []
        for o in getattr(state, "enemies", []):
            if o is enemy or o.behavior != "swarm":
                continue
            if (o.pos - enemy.pos).length() < 90:
                neigh.append(o)

        sep2 = _separation(enemy, neigh, radius=55.0, weight=1.8)

        align = Vec2(0.0, 0.0)
        coh_center = Vec2(0.0, 0.0)
        if neigh:
            for o in neigh:
                v = o.vel
                if v.length() > 1e-6:
                    align = align + v.normalized()
                coh_center = coh_center + o.pos
            inv = 1.0 / len(neigh)
            align = (align * inv).normalized()
            coh_center = Vec2(coh_center.x * inv, coh_center.y * inv)
        coh = (coh_center - enemy.pos).normalized() if neigh else Vec2(0.0, 0.0)

        sign = -1.0 if int(enemy.seed * 1000) % 2 else 1.0
        orbit = _perp(to_player) * sign
        jitter = Vec2(math.sin(enemy.t * 6.2 + enemy.seed), math.cos(enemy.t * 5.8 + enemy.seed)) * 0.18

        pull = 0.65
        if dist_to_player < 70:
            pull = 0.25
        elif dist_to_player > 160:
            pull = 0.9

        move = (to_player * pull + orbit * 0.85 + sep2 + align * 0.45 + coh * 0.25 + jitter).normalized()
        enemy.vel = move * enemy.speed
        enemy.pos = enemy.pos + enemy.vel * dt
        return

    if enemy.behavior == "tank":
        # Slow but tough, stops to attack
        dvec = player_pos - enemy.pos
        d = dvec.length()
        dir_to = dvec.normalized() if d > 1e-6 else Vec2(1.0, 0.0)
        if d > 100:
            # Move slowly toward player
            move = (dir_to * 0.7 + sep * 0.6).normalized()
            enemy.vel = move * (enemy.speed * 0.65)
            enemy.pos = enemy.pos + enemy.vel * dt
        else:
            enemy.vel = Vec2(0.0, 0.0)
        # Stop and attack when close
        enemy.attack_cd -= dt
        if enemy.attack_cd <= 0.0 and d < 150:
            proj_speed = 185.0
            aim = _lead_dir(enemy.pos, player_pos, player_vel, proj_speed, mult=0.6)
            vel = aim * proj_speed
            state.projectiles.append(Projectile(enemy.pos, vel, 12, ttl=2.8, owner="enemy"))
            enemy.attack_cd = 1.9 + random.uniform(0.0, 0.3)
        return

    if enemy.behavior == "spitter":
        # Ranged spread fire, stays at distance
        dvec = player_pos - enemy.pos
        d = dvec.length()
        dir_to = dvec.normalized() if d > 1e-6 else Vec2(1.0, 0.0)
        sign = 1.0 if (id(enemy) % 2) else -1.0
        # Maintain distance by strafing
        if d > 200:
            move = (dir_to * 0.75 + sep * 0.8).normalized()
            enemy.vel = move * (enemy.speed * 0.8)
            enemy.pos = enemy.pos + enemy.vel * dt
        elif d < 120:
            move = ((dir_to * -1.0) * 0.75 + sep).normalized()
            enemy.vel = move * (enemy.speed * 0.95)
            enemy.pos = enemy.pos + enemy.vel * dt
        else:
            strafe = _perp(dir_to) * sign
            move = (strafe * 0.9 + sep * 0.8 + dir_to * 0.1).normalized()
            enemy.vel = move * (enemy.speed * 0.95)
            enemy.pos = enemy.pos + enemy.vel * dt
        # Fire in spread pattern
        enemy.attack_cd -= dt
        if enemy.attack_cd <= 0.0 and d < 320:
            aim = _lead_dir(enemy.pos, player_pos, player_vel, proj_speed=210.0, mult=0.85)
            for angle_offset in [-30, 0, 30]:
                angle_rad = math.radians(angle_offset)
                cos_a = math.cos(angle_rad)
                sin_a = math.sin(angle_rad)
                vel_x = aim.x * cos_a - aim.y * sin_a
                vel_y = aim.x * sin_a + aim.y * cos_a
                vel = Vec2(vel_x, vel_y) * 200.0
                state.projectiles.append(Projectile(enemy.pos, vel, 6, ttl=2.5, owner="enemy"))
            enemy.attack_cd = 1.55 + random.uniform(0.0, 0.35)
        return

    if enemy.behavior == "flyer":
        # Erratic flying pattern, unpredictable
        dvec = player_pos - enemy.pos
        d = dvec.length()
        dir_to = dvec.normalized() if d > 1e-6 else Vec2(1.0, 0.0)
        # Wander + swoop.
        wander = Vec2(math.sin(enemy.t * 1.9 + enemy.seed), math.cos(enemy.t * 2.3 + enemy.seed)) * 0.55
        swoop = dir_to * (0.55 + 0.45 * math.sin(enemy.t * 2.7))
        strafe = _perp(dir_to) * (0.65 * math.sin(enemy.t * 3.6 + enemy.seed))
        move_dir = (swoop + strafe + wander + sep * 0.6).normalized()
        enemy.vel = move_dir * enemy.speed
        enemy.pos = enemy.pos + enemy.vel * dt

        # Occasional rapid dash (cooldown-based to avoid "every frame" bursts).
        enemy.attack_cd -= dt
        if enemy.attack_cd <= 0.0 and d < config.ROOM_RADIUS * 1.6:
            enemy.pos = enemy.pos + dir_to * enemy.speed * dt * 18.0
            enemy.attack_cd = 1.2 + random.uniform(0.0, 0.9)
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
            strafe = _perp(dir_to) * (1.0 if (id(enemy) % 2) else -1.0)
            move = (strafe * 0.8 + sep + dir_to * 0.1).normalized()
            enemy.vel = move * (enemy.speed * 0.85)
            enemy.pos = enemy.pos + enemy.vel * dt

        enemy.attack_cd -= dt
        if enemy.attack_cd <= 0.0 and d < 420:
            if not hasattr(state, "traps"):
                state.traps = []
            predicted = Vec2(player_pos.x + player_vel.x * 0.65, player_pos.y + player_vel.y * 0.65)
            jitter = Vec2(random.uniform(-24, 24), random.uniform(-24, 24))
            p = Vec2(predicted.x + jitter.x, predicted.y + jitter.y)
            # Keep within room bounds.
            if p.length() > config.ROOM_RADIUS * 0.86:
                p = p.normalized() * (config.ROOM_RADIUS * 0.86)
            state.traps.append(Trap(pos=p, radius=28.0, damage=16, ttl=10.0))
            enemy.attack_cd = 2.2 + random.uniform(0.0, 0.4)
        return

    # -----------------
    # Boss behaviors
    # -----------------
    if enemy.behavior == "boss_thunder":
        # Slow orbit around player, then call down lightning lines across the room.
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
            state.thunders.append(ThunderLine(start=start, end=end, damage=20, thickness=18.0, warn=0.45, ttl=0.18))

            # Personality + phases: mix in spread/ring bullet patterns.
            proj_speed = 210.0 + state.wave * 2.0
            dmg = 7 + state.wave // 3
            aim = _lead_dir(enemy.pos, player_pos, player_vel, proj_speed, mult=0.8)
            if phase == 0:
                if persona != "cautious":
                    _fire_fan(state, enemy.pos, aim, count=5, spread_deg=55.0, speed=proj_speed, damage=dmg, ttl=2.5)
            elif phase == 1:
                _fire_fan(state, enemy.pos, aim, count=7, spread_deg=70.0, speed=proj_speed, damage=dmg + 1, ttl=2.6)
            else:
                _fire_ring(state, enemy.pos, count=12, speed=proj_speed * 0.92, damage=dmg + 2, ttl=2.7, start_deg=enemy.t * 35.0)

            # Henchmen: spawn a couple of ranged adds sometimes.
            if len(getattr(state, "enemies", [])) < getattr(state, "max_enemies", 12) + 4 and random.random() < 0.35:
                for _ in range(2):
                    ang = random.uniform(0, math.tau)
                    pos = enemy.pos + Vec2(math.cos(ang), math.sin(ang)) * random.uniform(40, 70)
                    state.enemies.append(Enemy(pos=pos, hp=18 + state.wave * 3, speed=55 + state.wave * 1.4, behavior="ranged"))
            base_cd = 1.6 - state.wave * 0.02
            if phase == 1:
                base_cd *= 0.92
            elif phase == 2:
                base_cd *= 0.84
            if persona == "aggressive":
                base_cd *= 0.9
            enemy.attack_cd = max(0.65, base_cd)
        return

    if enemy.behavior == "boss_laser":
        # Erratic movement, rapid laser beams.
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
            if phase >= 1:
                # Slightly offset follow-up beams for a "sweep" feel.
                for off in (-16, 16) if phase == 1 else (-24, -8, 8, 24):
                    d2 = _rotate(dir_to, off)
                    state.lasers.append(
                        LaserBeam(
                            start=start,
                            end=start + d2 * beam_len,
                            damage=18 + state.wave // 2,
                            thickness=11.0,
                            warn=0.38 if phase == 1 else 0.32,
                            ttl=0.10,
                            color=(255, 120, 255),
                            owner="enemy",
                        )
                    )

            # Mix-in: shotgun bursts at higher phases (or trickster persona).
            if phase >= 1 or persona == "trickster":
                proj_speed = 235.0 + state.wave * 2.2
                dmg = 7 + state.wave // 3
                aim = _lead_dir(enemy.pos, player_pos, player_vel, proj_speed, mult=0.75)
                pellets = 6 if phase == 1 else 8
                _fire_fan(state, enemy.pos, aim, count=pellets, spread_deg=78.0, speed=proj_speed, damage=dmg, ttl=2.5)

            # Henchmen: occasional fast chasers.
            if len(getattr(state, "enemies", [])) < getattr(state, "max_enemies", 12) + 5 and random.random() < 0.25:
                ang = random.uniform(0, math.tau)
                pos = enemy.pos + Vec2(math.cos(ang), math.sin(ang)) * random.uniform(50, 90)
                state.enemies.append(Enemy(pos=pos, hp=16 + state.wave * 3, speed=90 + state.wave * 2.2, behavior="chaser"))
            base_cd = 0.9 - state.wave * 0.02
            if phase == 2:
                base_cd *= 0.85
            if persona == "aggressive":
                base_cd *= 0.9
            enemy.attack_cd = max(0.22, base_cd)
        return

    if enemy.behavior == "boss_trapmaster":
        # Places trap patterns while staying mid-range.
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
            n = 5
            r = 85
            base_ang = random.uniform(0, math.tau)
            for i in range(n):
                ang = base_ang + (i / n) * math.tau
                pos = player_pos + Vec2(math.cos(ang), math.sin(ang)) * r
                state.traps.append(Trap(pos=pos, radius=30.0, damage=18, ttl=9.0, armed_delay=0.55, kind="spike"))

            # Phases: add shrapnel bursts (spread and ring) after trap placement.
            proj_speed = 200.0 + state.wave * 2.0
            dmg = 7 + state.wave // 4
            aim = _lead_dir(enemy.pos, player_pos, player_vel, proj_speed, mult=0.85)
            if phase == 0:
                if persona != "cautious":
                    _fire_fan(state, enemy.pos, aim, count=5, spread_deg=60.0, speed=proj_speed, damage=dmg, ttl=2.6)
            elif phase == 1:
                _fire_fan(state, enemy.pos, aim, count=7, spread_deg=85.0, speed=proj_speed, damage=dmg + 1, ttl=2.7)
            else:
                _fire_ring(state, enemy.pos, count=14, speed=proj_speed * 0.9, damage=dmg + 2, ttl=2.8, start_deg=enemy.t * 40.0)

            # Henchmen: engineers join the fight.
            if len(getattr(state, "enemies", [])) < getattr(state, "max_enemies", 12) + 4 and random.random() < 0.4:
                pos = enemy.pos + Vec2(random.uniform(-70, 70), random.uniform(-70, 70))
                state.enemies.append(Enemy(pos=pos, hp=26 + state.wave * 4, speed=55 + state.wave * 1.3, behavior="engineer"))
            base_cd = 2.2 - state.wave * 0.03
            if phase >= 1:
                base_cd *= 0.9
            if persona == "aggressive":
                base_cd *= 0.92
            enemy.attack_cd = max(1.0, base_cd)
        return

    if enemy.behavior == "boss_swarmqueen":
        # Summons swarms and spits projectiles.
        dvec = player_pos - enemy.pos
        d = dvec.length()
        dir_to = dvec.normalized() if d > 1e-6 else Vec2(1, 0)
        phase = int(enemy.ai.get("phase", 0))
        persona = str(enemy.ai.get("persona", "aggressive"))
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
            proj_speed = 210.0 + state.wave * 2.5
            dmg = 8 + state.wave // 3
            if phase == 0:
                for off in (-24, -8, 8, 24):
                    vel = _rotate(dir_to, off) * proj_speed
                    state.projectiles.append(Projectile(enemy.pos, vel, dmg, ttl=2.6, owner="enemy"))
            elif phase == 1:
                _fire_fan(state, enemy.pos, dir_to, count=7, spread_deg=95.0, speed=proj_speed, damage=dmg + 1, ttl=2.6)
                if persona == "trickster":
                    # Extra side-shot.
                    _fire_fan(state, enemy.pos, _perp(dir_to), count=3, spread_deg=24.0, speed=proj_speed * 0.95, damage=max(1, dmg - 1), ttl=2.4)
            else:
                # Spiral burst: advance a stored angle for consistent "personality".
                ang = float(enemy.ai.get("spiral_deg", 0.0))
                enemy.ai["spiral_deg"] = ang + (72.0 if persona == "aggressive" else 58.0)
                base_dir = Vec2(math.cos(math.radians(ang)), math.sin(math.radians(ang)))
                _fire_ring(state, enemy.pos, count=10, speed=proj_speed * 0.92, damage=dmg + 2, ttl=2.7, start_deg=ang)
                _fire_fan(state, enemy.pos, base_dir, count=5, spread_deg=45.0, speed=proj_speed, damage=dmg + 1, ttl=2.6)

            base_cd = 2.0 - state.wave * 0.02
            if phase == 2:
                base_cd *= 0.82
            if persona == "aggressive":
                base_cd *= 0.9
            enemy.attack_cd = max(0.85, base_cd)
        return

    if enemy.behavior == "boss_brute":
        # Big charges and slam zones.
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
            state.traps.append(Trap(pos=Vec2(enemy.pos.x, enemy.pos.y), radius=80.0, damage=0, ttl=0.8, armed_delay=0.35, kind="slam_warn"))
            state.traps.append(Trap(pos=Vec2(enemy.pos.x, enemy.pos.y), radius=70.0, damage=26, ttl=0.55, armed_delay=0.35, kind="slam"))
            if phase_boss >= 1:
                # Shockwave bullets on slam.
                proj_speed = 200.0 + state.wave * 1.8
                dmg = 7 + state.wave // 4
                ring_n = 12 if phase_boss == 1 else 16
                _fire_ring(state, Vec2(enemy.pos.x, enemy.pos.y), count=ring_n, speed=proj_speed, damage=dmg + (1 if persona == "aggressive" else 0), ttl=2.7, start_deg=enemy.t * 30.0)

            base_cd = 2.0 - state.wave * 0.02
            if phase_boss == 2:
                base_cd *= 0.85
            if persona == "aggressive":
                base_cd *= 0.92
            enemy.attack_cd = max(0.95, base_cd)
        return
