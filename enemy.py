"""Enemy entity and related functionality."""

from dataclasses import dataclass, field
import math
import random

from hazards import Trap, LaserBeam, ThunderLine
from projectile import Projectile
import config
from utils import Vec2
from enemy_behaviors.base import Behavior
try:
    from enemy_behaviors.chase import Chase
    from enemy_behaviors.ranged import Ranged
    from enemy_behaviors.swarm import Swarm
    from enemy_behaviors.charger import Charger
    from enemy_behaviors.tank import Tank
    from enemy_behaviors.spitter import Spitter
    from enemy_behaviors.flyer import Flyer
    from enemy_behaviors.engineer import Engineer
except Exception:
    Chase = Ranged = Swarm = Charger = Tank = Spitter = Flyer = Engineer = None

_BEHAVIOR_IMPLS = {
    "chaser": Chase() if Chase else None,
    "ranged": Ranged() if Ranged else None,
    "swarm": Swarm() if Swarm else None,
    "charger": Charger() if Charger else None,
    "tank": Tank() if Tank else None,
    "spitter": Spitter() if Spitter else None,
    "flyer": Flyer() if Flyer else None,
    "engineer": Engineer() if Engineer else None,
}


@dataclass
class Enemy:
    """Enemy entity."""
    pos: Vec2
    hp: int
    speed: float
    behavior: str | Behavior
    t: float = 0.0
    attack_cd: float = 0.0
    vel: Vec2 = field(default_factory=lambda: Vec2(0.0, 0.0))
    seed: float = 0.0
    ai: dict = field(default_factory=dict)


def _perp(v: Vec2) -> Vec2:
    return Vec2(-v.y, v.x)


def _clamp(x: float, a: float, b: float) -> float:
    return a if x < a else b if x > b else x


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


def _append_trap_capped(state, trap: Trap) -> bool:
    """Append trap only if construction cap has room."""
    if not hasattr(state, "traps"):
        state.traps = []
    cap = max(0, int(getattr(config, "MAX_ACTIVE_CONSTRUCTIONS", 14)))
    if len(state.traps) >= cap:
        return False
    state.traps.append(trap)
    return True


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


def _boss_init(enemy: Enemy):
    if "max_hp" not in enemy.ai:
        enemy.ai["max_hp"] = int(enemy.hp)
    if "persona" not in enemy.ai:
        personas = ["aggressive", "cautious", "trickster"]
        enemy.ai["persona"] = personas[int(enemy.seed * 1000) % len(personas)]
    if "phase" not in enemy.ai:
        enemy.ai["phase"] = 0
    if "gun_idx" not in enemy.ai:
        enemy.ai["gun_idx"] = 0


def _boss_phase(enemy: Enemy) -> int:
    max_hp = max(1, int(enemy.ai.get("max_hp", enemy.hp)))
    r = float(enemy.hp) / float(max_hp)
    if r > 0.66:
        return 0
    if r > 0.33:
        return 1
    return 2


def _cycle_gun(enemy: Enemy, guns: list[str]) -> str:
    """Cycle through a list of projectile types for variety."""
    if not guns:
        return "bullet"
    idx = int(enemy.ai.get("gun_idx", 0))
    enemy.ai["gun_idx"] = idx + 1
    return str(guns[idx % len(guns)])


def update_enemy(enemy: Enemy, player_pos: Vec2, state, dt: float, player_vel: Vec2 | None = None):
    """Update enemy AI behavior."""
    if player_vel is None:
        player_vel = Vec2(0.0, 0.0)

    enemy.t += dt
    if enemy.seed == 0.0:
        enemy.seed = random.uniform(0.0, math.tau)

    if isinstance(enemy.behavior, str):
        if not enemy.behavior.startswith("boss_"):
            behavior_impl = _BEHAVIOR_IMPLS.get(enemy.behavior)
            if behavior_impl is None:
                return
            behavior_impl.update(enemy, player_pos, state, dt, player_vel)
            return

    if isinstance(enemy.behavior, str) and enemy.behavior.startswith("boss_"):
        _boss_init(enemy)
        new_phase = _boss_phase(enemy)
        if int(enemy.ai.get("phase", 0)) != new_phase:
            enemy.ai["phase"] = new_phase
            # Phase change: bring the next attack forward a bit.
            enemy.attack_cd = min(enemy.attack_cd, 0.35)
        
        # Keep boss logic here for now
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
                        _fire_fan(state, enemy.pos, _perp(aim), count=5, spread_deg=46.0, speed=proj_speed * 0.95, damage=max(1, dmg), ttl=2.45, projectile_type="spread")

                # Henchmen: engineers join the fight.
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
                # Summon a few swarm enemies (capped to avoid runaway difficulty/perf).
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
                        _fire_fan(state, enemy.pos, _perp(dir_to), count=3, spread_deg=24.0, speed=proj_speed * 0.95, damage=max(1, dmg - 1), ttl=2.4, projectile_type="spread")
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
            return
    else:
        if hasattr(enemy.behavior, "update"):
            enemy.behavior.update(enemy, player_pos, state, dt, player_vel)
