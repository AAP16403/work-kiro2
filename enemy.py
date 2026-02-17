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
    from enemy_behaviors.bomber import Bomber
except Exception:
    Chase = Ranged = Swarm = Charger = Tank = Spitter = Flyer = Engineer = Bomber = None

_BEHAVIOR_IMPLS = {
    "chaser": Chase() if Chase else None,
    "ranged": Ranged() if Ranged else None,
    "swarm": Swarm() if Swarm else None,
    "charger": Charger() if Charger else None,
    "tank": Tank() if Tank else None,
    "spitter": Spitter() if Spitter else None,
    "flyer": Flyer() if Flyer else None,
    "engineer": Engineer() if Engineer else None,
    "bomber": Bomber() if Bomber else None,
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
) -> None:
    """Fire bullets in a full ring around the origin."""
    ptype = str(projectile_type or "bullet")
    n = max(3, int(count))
    base = float(start_deg)
    step = 360.0 / float(n)
    for i in range(n):
        a = base + i * step
        d = Vec2(math.cos(math.radians(a)), math.sin(math.radians(a)))
        state.projectiles.append(Projectile(origin, d * float(speed), int(damage), ttl=float(ttl), owner="enemy", projectile_type=ptype))


def _spawn_shockwave(state, origin: Vec2, count: int = 16, speed: float = 240.0, damage: int = 10):
    """Spawn a expanding ring of projectiles (shockwave)."""
    _fire_ring(state, origin, count, speed, damage, ttl=1.8, projectile_type="plasma")
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


def _difficulty_mult(state) -> float:
    d = str(getattr(state, "difficulty", "normal")).lower()
    if d == "easy":
        return 0.88
    if d == "hard":
        return 1.12
    return 1.0


def _boss_damage(state, base: float, wave_scale: float = 0.22, cap: int = 32) -> int:
    dmg = (float(base) + float(getattr(state, "wave", 1)) * float(wave_scale)) * _difficulty_mult(state)
    return max(1, min(int(round(dmg)), int(cap)))


def _boss_cd(state, base: float, phase: int, floor: float, persona: str = "aggressive") -> float:
    cd = float(base)
    if phase == 1:
        cd *= 0.92
    elif phase >= 2:
        cd *= 0.84
    if str(persona) == "aggressive":
        cd *= 0.95
    d = str(getattr(state, "difficulty", "normal")).lower()
    if d == "easy":
        cd *= 1.08
    elif d == "hard":
        cd *= 0.92
    return max(float(floor), cd)


def _boss_adds_cap(state, bonus: int) -> int:
    # Keep boss encounters tense without flooding the room.
    base = int(getattr(state, "max_enemies", 12))
    return max(base + 1, min(base + int(bonus), base + 6))


def _behavior_key(enemy: Enemy) -> str:
    b = getattr(enemy, "behavior", "")
    if isinstance(b, str):
        return b
    return b.__class__.__name__.lower()


def _formation_profile(state) -> dict:
    d = str(getattr(state, "difficulty", "normal")).lower()
    if d == "easy":
        return {
            "lead_time": 0.09,
            "front_arc_deg": 104.0,
            "back_arc_deg": 120.0,
            "steer_mult": 0.78,
            "pressure_mult": 0.86,
            "flank_offset_deg": 88.0,
        }
    if d == "hard":
        return {
            "lead_time": 0.18,
            "front_arc_deg": 84.0,
            "back_arc_deg": 98.0,
            "steer_mult": 1.08,
            "pressure_mult": 1.16,
            "flank_offset_deg": 78.0,
        }
    return {
        "lead_time": 0.13,
        "front_arc_deg": 94.0,
        "back_arc_deg": 108.0,
        "steer_mult": 0.95,
        "pressure_mult": 1.0,
        "flank_offset_deg": 82.0,
    }


def _role_for_behavior(key: str) -> str:
    return {
        "tank": "front_heavy",
        "charger": "front_dive",
        "chaser": "front",
        "swarm": "flank",
        "flyer": "flank",
        "bomber": "mid_lob",
        "ranged": "backline",
        "spitter": "backline",
        "engineer": "support",
    }.get(key, "front")


def _slot_radius(key: str) -> float:
    return {
        "tank": 110.0,
        "charger": 118.0,
        "chaser": 128.0,
        "swarm": 124.0,
        "flyer": 134.0,
        "bomber": 152.0,
        "ranged": 186.0,
        "spitter": 174.0,
        "engineer": 204.0,
    }.get(key, 140.0)


def _unit_order_bias(enemy: Enemy) -> float:
    if "formation_bias" not in enemy.ai:
        enemy.ai["formation_bias"] = (float((id(enemy) % 997)) / 997.0)
    return float(enemy.ai["formation_bias"])


def _build_role_formation(state, player_pos: Vec2, player_vel: Vec2) -> dict:
    now = float(getattr(state, "time", 0.0))
    cached = getattr(state, "_role_formation", None)
    if cached and abs(float(cached.get("t", -999.0)) - now) <= 1e-8:
        return cached

    enemies = [e for e in getattr(state, "enemies", []) if not _behavior_key(e).startswith("boss_")]
    prof = _formation_profile(state)
    slot_targets: dict[int, Vec2] = {}
    roles: dict[int, str] = {}
    keys: dict[int, str] = {}

    if not enemies:
        out = {"t": now, "slot_targets": slot_targets, "roles": roles, "keys": keys, "profile": prof}
        state._role_formation = out
        return out

    center = Vec2(0.0, 0.0)
    for e in enemies:
        center = center + e.pos
    center = center / float(len(enemies))
    to_player = player_pos - center
    front_dir = to_player.normalized() if to_player.length() > 1e-6 else Vec2(1.0, 0.0)
    base_ang = math.atan2(front_dir.y, front_dir.x)
    flank_offset = math.radians(float(prof["flank_offset_deg"]))
    anchor = player_pos + player_vel * float(prof["lead_time"])

    groups: dict[str, list[Enemy]] = {
        "front_heavy": [],
        "front_dive": [],
        "front": [],
        "flank_left": [],
        "flank_right": [],
        "mid_lob": [],
        "backline": [],
        "support": [],
    }

    for e in enemies:
        key = _behavior_key(e)
        role = _role_for_behavior(key)
        eid = id(e)
        roles[eid] = role
        keys[eid] = key
        if role == "flank":
            # Stable flank-side assignment keeps wings coherent.
            if _unit_order_bias(e) < 0.5:
                groups["flank_left"].append(e)
            else:
                groups["flank_right"].append(e)
        else:
            groups[role].append(e)

    def _assign_arc(units: list[Enemy], center_angle: float, arc_deg: float, base_radius: float, radius_step: float = 12.0):
        if not units:
            return
        ordered = sorted(units, key=lambda u: (_unit_order_bias(u), u.seed))
        n = len(ordered)
        arc = math.radians(arc_deg)
        for i, e in enumerate(ordered):
            if n == 1:
                frac = 0.0
            else:
                frac = (i / float(n - 1)) - 0.5
            ang = center_angle + frac * arc
            r = base_radius + (i % 2) * radius_step
            key = keys[id(e)]
            r = 0.6 * r + 0.4 * _slot_radius(key)
            slot_targets[id(e)] = anchor + Vec2(math.cos(ang), math.sin(ang)) * r

    _assign_arc(groups["front_heavy"], base_ang, arc_deg=48.0, base_radius=108.0, radius_step=8.0)
    _assign_arc(groups["front_dive"], base_ang, arc_deg=68.0, base_radius=120.0, radius_step=10.0)
    _assign_arc(groups["front"], base_ang, arc_deg=float(prof["front_arc_deg"]), base_radius=132.0, radius_step=12.0)
    _assign_arc(groups["flank_left"], base_ang + flank_offset, arc_deg=62.0, base_radius=138.0, radius_step=10.0)
    _assign_arc(groups["flank_right"], base_ang - flank_offset, arc_deg=62.0, base_radius=138.0, radius_step=10.0)
    _assign_arc(groups["mid_lob"], base_ang + math.radians(28.0), arc_deg=86.0, base_radius=152.0, radius_step=12.0)
    _assign_arc(groups["backline"], base_ang + math.pi, arc_deg=float(prof["back_arc_deg"]), base_radius=182.0, radius_step=14.0)
    _assign_arc(groups["support"], base_ang + math.pi, arc_deg=74.0, base_radius=212.0, radius_step=16.0)

    out = {"t": now, "slot_targets": slot_targets, "roles": roles, "keys": keys, "profile": prof}
    state._role_formation = out
    return out


def _apply_type_coordination(enemy: Enemy, player_pos: Vec2, state, dt: float, player_vel: Vec2) -> None:
    """Apply role-based formation/cohesion pressure after per-type behavior update."""
    if dt <= 0.0:
        return

    key = _behavior_key(enemy)
    if not key or key.startswith("boss_"):
        return

    enemies = getattr(state, "enemies", None)
    if not enemies:
        return

    formation = _build_role_formation(state, player_pos, player_vel)
    slot_targets = formation["slot_targets"]
    role_map = formation["roles"]
    prof = formation["profile"]
    role = role_map.get(id(enemy), _role_for_behavior(key))

    # Coordinate with nearby allies only; global coupling causes rubber-band jitter.
    coord_r = {
        "ranged": 260.0,
        "spitter": 230.0,
        "engineer": 260.0,
        "tank": 190.0,
        "charger": 170.0,
        "chaser": 170.0,
        "swarm": 180.0,
        "flyer": 210.0,
        "bomber": 220.0,
    }.get(key, 200.0)
    nearby_all = []
    nearby_same = []
    r2 = coord_r * coord_r
    for o in enemies:
        if o is enemy:
            continue
        ok = _behavior_key(o)
        if ok.startswith("boss_"):
            continue
        if (o.pos - enemy.pos).length_squared() > r2:
            continue
        nearby_all.append(o)
        if ok == key:
            nearby_same.append(o)

    to_player_vec = player_pos - enemy.pos
    to_player = to_player_vec.normalized() if to_player_vec.length() > 1e-6 else Vec2(1.0, 0.0)

    center = Vec2(enemy.pos.x, enemy.pos.y)
    for a in nearby_all:
        center = center + a.pos
    center = center / float(len(nearby_all) + 1)
    cohesion = (center - enemy.pos).normalized()

    # Local separation keeps allies from stacking (stronger for same-type).
    separation = Vec2(0.0, 0.0)
    sep_count = 0
    for a in nearby_all:
        dvec = enemy.pos - a.pos
        d = dvec.length()
        if d <= 1e-6:
            continue
        if d < coord_r * 0.45:
            wt = 1.0 if a in nearby_same else 0.55
            separation = separation + dvec.normalized() * (1.0 - d / (coord_r * 0.45)) * wt
            sep_count += 1
    if sep_count > 0:
        separation = (separation / float(sep_count)).normalized()

    slot_target = slot_targets.get(id(enemy))
    if slot_target is None:
        slot_target = player_pos + to_player * _slot_radius(key)
    to_slot = (slot_target - enemy.pos).normalized()

    vel_dir = enemy.vel.normalized() if enemy.vel.length() > 1e-6 else to_player

    # Keep role identity, but ensure forward combat pressure.
    min_forward = {
        "ranged": -0.05,
        "spitter": 0.04,
        "engineer": -0.08,
        "tank": 0.06,
        "charger": 0.2,
        "chaser": 0.24,
        "swarm": 0.22,
        "flyer": 0.13,
        "bomber": 0.08,
    }.get(key, 0.08)
    min_forward *= float(prof["pressure_mult"])

    role_slot_weight = {
        "front_heavy": 0.62,
        "front_dive": 0.66,
        "front": 0.63,
        "flank": 0.7,
        "mid_lob": 0.74,
        "backline": 0.84,
        "support": 0.86,
    }.get(role, 0.66)

    role_player_weight = {
        "front_heavy": 0.66,
        "front_dive": 0.7,
        "front": 0.62,
        "flank": 0.56,
        "mid_lob": 0.44,
        "backline": 0.36,
        "support": 0.24,
    }.get(role, 0.52)

    desired_dir = (
        vel_dir * 0.45
        + to_slot * role_slot_weight
        + cohesion * 0.36
        + separation * 0.72
        + to_player * role_player_weight
    ).normalized()

    # Forward-pressure hysteresis avoids frame-to-frame retreat jitter.
    fwd = desired_dir.dot(to_player)
    lock_t = float(enemy.ai.get("forward_lock_t", 0.0))
    if fwd < min_forward:
        lock_t = min(0.35, lock_t + dt * 2.6)
    else:
        lock_t = max(0.0, lock_t - dt * 2.0)
    enemy.ai["forward_lock_t"] = lock_t
    if lock_t > 0.0 and fwd < min_forward:
        desired_dir = (desired_dir + to_player * (0.28 + lock_t * 0.9)).normalized()

    desired_speed = enemy.speed * (1.02 if key in ("chaser", "swarm", "charger") else 0.98) * float(prof["pressure_mult"])
    desired_vel = desired_dir * desired_speed

    # Reynolds-style bounded steering: smooth and continuous velocity changes.
    steering = desired_vel - enemy.vel
    max_force = enemy.speed * 3.2 * float(prof["steer_mult"])
    max_step = max_force * dt
    sl = steering.length()
    if sl > max_step and sl > 1e-6:
        steering = steering * (max_step / sl)

    enemy.vel = enemy.vel + steering
    max_speed = enemy.speed * 1.28
    vl = enemy.vel.length()
    if vl > max_speed and vl > 1e-6:
        enemy.vel = enemy.vel * (max_speed / vl)


def update_enemy(enemy: Enemy, player_pos: Vec2, state, dt: float, game, player_vel: Vec2 | None = None):
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
            _dispatch_behavior_update(behavior_impl, enemy, player_pos, state, dt, game, player_vel)
            _apply_type_coordination(enemy, player_pos, state, dt, player_vel)
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
            # Overhaul: The Warp-Striker.
            # Teleports around the room instead of walking.
            # Cycles: [Stalk -> Teleport -> Attack -> Cooldown]
            
            phase = int(enemy.ai.get("phase", 0))
            persona = str(enemy.ai.get("persona", "aggressive"))
            
            # AI State Machine for Thunder Boss
            state_key = "thunder_state"
            state_timer = "thunder_timer"
            if state_key not in enemy.ai:
                enemy.ai[state_key] = "stalk"
                enemy.ai[state_timer] = 1.5

            st = enemy.ai[state_key]
            enemy.ai[state_timer] -= dt
            timer = enemy.ai[state_timer]

            # --- STALK: Drift slowly, prepare to warp ---
            if st == "stalk":
                # Mild movement to look alive
                dvec = player_pos - enemy.pos
                dist = dvec.length()
                dir_to = dvec.normalized() if dist > 1e-6 else Vec2(1, 0)
                
                # Orbit/drift
                drift = _rotate(dir_to, 90 if enemy.seed > 3.14 else -90)
                enemy.pos = enemy.pos + drift * enemy.speed * 0.4 * dt

                if timer <= 0:
                    enemy.ai[state_key] = "teleport_out"
                    enemy.ai[state_timer] = 0.4 # Vanish time

            # --- TELEPORT OUT: Vanish (shrink/fade) ---
            elif st == "teleport_out":
                # Visuals handled in renderer by checking state, here just logic
                if timer <= 0:
                    # Pick new spot
                    # Try to flank the player or get distance
                    angle = random.uniform(0, math.tau)
                    dist = random.uniform(200, 350)
                    offset = Vec2(math.cos(angle), math.sin(angle)) * dist
                    # Keep in bounds
                    target = player_pos + offset
                    if target.length() > config.ROOM_RADIUS * 0.9:
                        target = target.normalized() * (config.ROOM_RADIUS * 0.85)
                    
                    enemy.pos = target
                    enemy.ai[state_key] = "teleport_in"
                    enemy.ai[state_timer] = 0.25

            # --- TELEPORT IN: Reappear ---
            elif st == "teleport_in":
                if timer <= 0:
                    enemy.ai[state_key] = "attack"
                    enemy.ai[state_timer] = 0.1

            # --- ATTACK: Unleash patterns ---
            elif st == "attack":
                # Select attack based on phase and RNG
                # 1. Static Storm (Lines)
                # 2. Warp Burst (Ring)
                # 3. Targeted snipe
                
                atk_roll = random.random()
                proj_speed = 210.0 + state.wave * 2.0
                dmg = _boss_damage(state, base=5.0, wave_scale=0.14, cap=16)

                if atk_roll < 0.45 or phase >= 1:
                    # Static Storm: Call thunder lines
                    if not hasattr(state, "thunders"):
                        state.thunders = []
                    
                    line_count = 1 + phase
                    if persona == "aggressive": line_count += 1
                    
                    for _ in range(line_count):
                        # Random lines across the arena
                        angle = random.uniform(0, math.tau)
                        dirv = Vec2(math.cos(angle), math.sin(angle))
                        perp = Vec2(-dirv.y, dirv.x)
                        offset = random.uniform(-150, 150)
                        anchor = player_pos + perp * offset # Bias towards player center
                        span = config.ROOM_RADIUS * 2.2
                        start = anchor - dirv * span
                        end = anchor + dirv * span
                        th_dmg = _boss_damage(state, base=12.0, wave_scale=0.22, cap=26)
                        state.thunders.append(ThunderLine(start=start, end=end, damage=th_dmg, thickness=16.0, warn=0.75, ttl=0.2))

                if atk_roll > 0.3:
                    # Warp Burst: Ring of bullets
                    ring_cnt = 9
                    if phase >= 1: ring_cnt = 12
                    gun = _cycle_gun(enemy, ["plasma", "bullet"])
                    _fire_ring(state, enemy.pos, ring_cnt, proj_speed * 0.9, dmg, projectile_type=gun)
                    
                    if phase >= 2:
                        # Double burst
                        _fire_ring(state, enemy.pos, ring_cnt, proj_speed * 0.75, dmg, start_deg=15.0, projectile_type=gun)

                enemy.ai[state_key] = "stalk"
                cd_base = 2.2 - (state.wave * 0.05) - (phase * 0.3)
                if persona == "aggressive": cd_base *= 0.8
                enemy.ai[state_timer] = max(0.8, cd_base)

            return

        if enemy.behavior == "boss_laser":
            # Overhaul: The Prism.
            # Cycles: [Move Corner -> Sweep Attack -> Prism Cage -> Cooldown]
            
            phase = int(enemy.ai.get("phase", 0))
            persona = str(enemy.ai.get("persona", "aggressive"))
            
            l_state = enemy.ai.get("laser_state", "reposition")
            l_timer = float(enemy.ai.get("laser_timer", 0.0))
            l_timer -= dt
            
            # --- REPOSITION: Move to a corner or far edge ---
            if l_state == "reposition":
                if l_timer <= 0:
                    # Pick a corner
                    corners = [Vec2(config.ROOM_RADIUS*0.8, config.ROOM_RADIUS*0.8),
                               Vec2(-config.ROOM_RADIUS*0.8, config.ROOM_RADIUS*0.8),
                               Vec2(config.ROOM_RADIUS*0.8, -config.ROOM_RADIUS*0.8),
                               Vec2(-config.ROOM_RADIUS*0.8, -config.ROOM_RADIUS*0.8)]
                    dest = random.choice(corners)
                    enemy.ai["move_target_x"] = dest.x
                    enemy.ai["move_target_y"] = dest.y
                    enemy.ai["laser_state"] = "moving"
                    enemy.ai["laser_timer"] = 3.0 # Max move time

            # --- MOVING: Travel to target ---
            elif l_state == "moving":
                target = Vec2(float(enemy.ai["move_target_x"]), float(enemy.ai["move_target_y"]))
                dvec = target - enemy.pos
                if dvec.length() < 20 or l_timer <= 0:
                    enemy.ai["laser_state"] = "charge"
                    enemy.ai["laser_timer"] = 0.6
                else:
                    enemy.pos = enemy.pos + dvec.normalized() * enemy.speed * 1.5 * dt

            # --- CHARGE: Telegraph attack ---
            elif l_state == "charge":
                if l_timer <= 0:
                    enemy.ai["laser_state"] = "attack"
                    enemy.ai["laser_timer"] = 3.0 # Attack duration
                    enemy.ai["sweep_angle"] = 0.0

            # --- ATTACK: Sweep lasers or Prism Cage ---
            elif l_state == "attack":
                # Sweep Logic
                if not hasattr(state, "lasers"):
                    state.lasers = []
                
                # Calculate aim to player
                to_player = player_pos - enemy.pos
                base_angle = math.degrees(math.atan2(to_player.y, to_player.x))
                
                # Sweep offset based on timer (sweep back and forth)
                sweep_speed = 45.0 + (phase * 15.0)
                sweep_offset = math.sin(enemy.t * 3.0) * (35.0 + phase * 10.0)
                
                if persona == "aggressive" and phase >= 1:
                    # Dual sweep (V shape)
                    offsets = [sweep_offset, -sweep_offset]
                else:
                    offsets = [sweep_offset]
                
                for off in offsets:
                    angle = base_angle + off
                    rad = math.radians(angle)
                    beam_dir = Vec2(math.cos(rad), math.sin(rad))
                    
                    start = enemy.pos
                    end = start + beam_dir * config.ROOM_RADIUS * 2.2
                    
                    # Short-lived beams to simulate continuous sweep
                    dmg = _boss_damage(state, base=12.0, wave_scale=0.22, cap=24)
                    state.lasers.append(LaserBeam(start, end, damage=dmg, thickness=14.0, warn=0.0, ttl=0.15, color=(255, 100, 255), owner="enemy"))
                
                # Occasional Prism Cage (Phase 2+)
                if phase >= 2 and random.random() < 0.02:
                     _fire_ring(state, enemy.pos, count=8, speed=180.0, damage=10, projectile_type="plasma")

                if l_timer <= 0:
                    enemy.ai["laser_state"] = "reposition"
                    enemy.ai["laser_timer"] = 0.5
            
            enemy.ai["laser_timer"] = l_timer
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
                n = 3 if phase == 0 else 4 if phase == 1 else 5
                r = 82 if phase < 2 else 92
                base_ang = random.uniform(0, math.tau)
                for i in range(n):
                    ang = base_ang + (i / n) * math.tau
                    pos = player_pos + Vec2(math.cos(ang), math.sin(ang)) * r
                    _append_trap_capped(
                        state,
                        Trap(
                            pos=pos,
                            radius=29.0,
                            damage=_boss_damage(state, base=12.5, wave_scale=0.2, cap=25),
                            ttl=7.6,
                            armed_delay=0.6,
                            kind="spike",
                        ),
                    )

                # Phases: add shrapnel bursts after trap placement (no swirl/ring spam).
                proj_speed = 195.0 + state.wave * 1.7
                dmg = _boss_damage(state, base=5.0, wave_scale=0.14, cap=16)
                aim = _lead_dir(enemy.pos, player_pos, player_vel, proj_speed, mult=0.85)
                if phase == 0:
                    if persona != "cautious":
                        _fire_fan(state, enemy.pos, aim, count=4, spread_deg=56.0, speed=proj_speed, damage=dmg, ttl=2.55, projectile_type="spread")
                elif phase == 1:
                    _fire_fan(state, enemy.pos, aim, count=6, spread_deg=76.0, speed=proj_speed, damage=dmg + 1, ttl=2.65, projectile_type="spread")
                else:
                    _fire_fan(state, enemy.pos, aim, count=8, spread_deg=92.0, speed=proj_speed, damage=dmg + 2, ttl=2.65, projectile_type="spread")
                    if persona in ("aggressive", "trickster"):
                        _fire_fan(state, enemy.pos, _perp(aim), count=4, spread_deg=42.0, speed=proj_speed * 0.92, damage=max(1, dmg), ttl=2.4, projectile_type="spread")

                # Henchmen: engineers join the fight.
                adds_cap = _boss_adds_cap(state, 2)
                if len(getattr(state, "enemies", [])) < adds_cap and random.random() < 0.14:
                    pos = enemy.pos + Vec2(random.uniform(-70, 70), random.uniform(-70, 70))
                    state.enemies.append(Enemy(pos=pos, hp=22 + state.wave * 3, speed=52 + state.wave * 1.2, behavior="engineer"))
                base_cd = 2.35 - state.wave * 0.012
                enemy.attack_cd = _boss_cd(state, base_cd, phase, floor=1.05, persona=persona)
            return

        if enemy.behavior == "boss_swarmqueen":
            # Overhaul: The Hive.
            # Cycles: [Spawn Eggs -> Spit Acid -> Retreat]
            
            phase = int(enemy.ai.get("phase", 0))
            persona = str(enemy.ai.get("persona", "aggressive"))
            
            # Retreat logic: keep distance
            dvec = player_pos - enemy.pos
            if dvec.length() < 300:
                enemy.pos = enemy.pos - dvec.normalized() * enemy.speed * dt * 0.8
            else:
                 # Orbit slowly
                drift = _rotate(dvec.normalized(), 90)
                enemy.pos = enemy.pos + drift * enemy.speed * 0.3 * dt

            enemy.attack_cd -= dt
            if enemy.attack_cd <= 0.0:
                roll = random.random()
                
                # 1. Spawn Egg Sacs (Priority)
                adds_cap = _boss_adds_cap(state, 4)
                current_adds = len([e for e in getattr(state, "enemies", []) if not str(e.behavior).startswith("boss")])
                
                if roll < 0.5 and current_adds < adds_cap:
                    # Spawn 1-2 egg sacs
                    count = 1 + (1 if phase >= 1 else 0)
                    for _ in range(count):
                        ang = random.uniform(0, math.tau)
                        dist = random.uniform(40, 80)
                        pos = enemy.pos + Vec2(math.cos(ang), math.sin(ang)) * dist
                        # Egg Sac: Static enemy that spawns stuff on death
                        sac = Enemy(pos=pos, hp=25 + state.wave * 4, speed=0, behavior="egg_sac")
                        sac.ai["hatch_timer"] = 4.0 if phase == 0 else 3.0
                        state.enemies.append(sac)
                
                # 2. Acid Spit
                elif roll < 0.85:
                    proj_speed = 190.0
                    dmg = _boss_damage(state, base=6.0, wave_scale=0.15, cap=18)
                    aim = (player_pos - enemy.pos).normalized()
                    _fire_fan(state, enemy.pos, aim, count=5 + phase, spread_deg=60.0, speed=proj_speed, damage=dmg, projectile_type="plasma")
                
                # 3. Swarm Call (Direct spawn)
                else:
                    for _ in range(3):
                         ang = random.uniform(0, math.tau)
                         pos = enemy.pos + Vec2(math.cos(ang), math.sin(ang)) * 60
                         state.enemies.append(Enemy(pos=pos, hp=12, speed=100, behavior="swarm"))

                enemy.attack_cd = _boss_cd(state, 2.5, phase, floor=1.2, persona=persona)
            return

        if enemy.behavior == "egg_sac":
            # Just sit there and pulsate. logic handled in damage/death usually, 
            # but we need a hatch timer here.
            enemy.ai["hatch_timer"] = float(enemy.ai.get("hatch_timer", 4.0)) - dt
            if enemy.ai["hatch_timer"] <= 0:
                # Hatch!
                enemy.hp = -1 # Die
                # Spawn swarmlings
                for _ in range(3):
                    ang = random.uniform(0, math.tau)
                    pos = enemy.pos + Vec2(math.cos(ang), math.sin(ang)) * 20
                    state.enemies.append(Enemy(pos=pos, hp=12 + state.wave, speed=110, behavior="swarm"))
            return

        if enemy.behavior == "boss_brute":
            # Overhaul: The Juggernaut.
            # Cycles: [Chase -> Charge Telegraph -> Charge -> Recover]
            # If Charge hits wall -> Stunned.
            
            phase_boss = int(enemy.ai.get("phase", 0))
            persona = str(enemy.ai.get("persona", "aggressive"))
            
            b_state = enemy.ai.get("brute_state", "chase")
            b_timer = float(enemy.ai.get("brute_timer", 0.0))
            
            b_timer -= dt
            
            # --- CHASE: Move towards player, but heavy/slow ---
            if b_state == "chase":
                dvec = player_pos - enemy.pos
                dist = dvec.length()
                dir_to = dvec.normalized() if dist > 1e-6 else Vec2(1, 0)
                
                # Heavy movement
                speed_mod = 0.75
                if persona == "aggressive": speed_mod = 0.85
                enemy.pos = enemy.pos + dir_to * enemy.speed * speed_mod * dt
                
                # Transition to charge based on timer or proximity
                if b_timer <= 0:
                    enemy.ai["brute_state"] = "telegraph"
                    enemy.ai["brute_timer"] = 0.8 # Warning time
                    enemy.ai["charge_dir_x"] = dir_to.x
                    enemy.ai["charge_dir_y"] = dir_to.y

            # --- TELEGRAPH: Freeze and shake/warn ---
            elif b_state == "telegraph":
                # (Visuals should show charging up)
                if b_timer <= 0:
                    enemy.ai["brute_state"] = "charge"
                    enemy.ai["brute_timer"] = 1.2 # Max charge duration
                    # Lock direction
                    dvec = player_pos - enemy.pos
                    dir_to = dvec.normalized() if dvec.length() > 1e-6 else Vec2(1, 0)
                    enemy.ai["charge_dir_x"] = dir_to.x
                    enemy.ai["charge_dir_y"] = dir_to.y

            # --- CHARGE: High speed, no steering ---
            elif b_state == "charge":
                cx = float(enemy.ai.get("charge_dir_x", 1.0))
                cy = float(enemy.ai.get("charge_dir_y", 0.0))
                charge_dir = Vec2(cx, cy)
                
                charge_speed = enemy.speed * 3.2
                if phase_boss >= 1: charge_speed *= 1.15
                
                step = charge_dir * charge_speed * dt
                enemy.pos = enemy.pos + step
                
                # Check wall collision
                if enemy.pos.length() > config.ROOM_RADIUS * 0.95:
                    # WALL SLAM!
                    enemy.pos = enemy.pos.normalized() * (config.ROOM_RADIUS * 0.95)
                    enemy.ai["brute_state"] = "stun"
                    enemy.ai["brute_timer"] = 2.0 # Vulnerability window
                    
                    # Shockwave
                    sw_dmg = _boss_damage(state, base=8.0, wave_scale=0.15, cap=20)
                    _spawn_shockwave(state, enemy.pos, count=16 + phase_boss * 4, speed=260.0, damage=sw_dmg)
                    
                    # Screen shake (via trap placeholder or just effect)
                    # We can't access screen shake directly easily, but the shockwave is good enough.
                    
                elif b_timer <= 0:
                    # Ran out of breath
                    enemy.ai["brute_state"] = "recover"
                    enemy.ai["brute_timer"] = 0.8

            # --- STUN: Vulnerable after wall hit ---
            elif b_state == "stun":
                # Do nothing, just sit there
                if b_timer <= 0:
                    enemy.ai["brute_state"] = "chase"
                    enemy.ai["brute_timer"] = 3.0 if phase_boss == 0 else 2.2

            # --- RECOVER: Paused after missed charge ---
            elif b_state == "recover":
                if b_timer <= 0:
                    enemy.ai["brute_state"] = "chase"
                    enemy.ai["brute_timer"] = 2.5
            
            # Save state
            enemy.ai["brute_timer"] = b_timer
            return

        if enemy.behavior == "boss_abyss_gaze":
            # Inspired by Isaac's late bullet-hell fights: tracking curtains + beam checks.
            dvec = player_pos - enemy.pos
            d = dvec.length()
            dir_to = dvec.normalized() if d > 1e-6 else Vec2(1, 0)
            phase = int(enemy.ai.get("phase", 0))
            persona = str(enemy.ai.get("persona", "aggressive"))
            strafe = Vec2(-dir_to.y, dir_to.x)

            desired = 240.0 if phase == 0 else 220.0 if phase == 1 else 205.0
            if d > desired + 20.0:
                move = (dir_to * 0.88 + strafe * 0.36).normalized()
            elif d < desired - 20.0:
                move = ((dir_to * -1.0) * 0.7 + strafe * 0.62).normalized()
            else:
                move = (strafe * 0.92 + dir_to * 0.2).normalized()
            enemy.pos = enemy.pos + move * enemy.speed * dt * (0.9 + 0.12 * math.sin(enemy.t * 2.2))

            enemy.attack_cd -= dt
            if enemy.attack_cd <= 0.0:
                if not hasattr(state, "lasers"):
                    state.lasers = []

                proj_speed = 225.0 + state.wave * 1.8
                dmg = _boss_damage(state, base=6.5, wave_scale=0.15, cap=18)
                aim = _lead_dir(enemy.pos, player_pos, player_vel, proj_speed, mult=0.72)

                # Main curtain/fan pattern.
                if phase == 0:
                    _fire_fan(state, enemy.pos, aim, count=6, spread_deg=72.0, speed=proj_speed, damage=dmg, ttl=2.6, projectile_type="plasma")
                elif phase == 1:
                    _fire_fan(state, enemy.pos, aim, count=7, spread_deg=82.0, speed=proj_speed, damage=dmg + 1, ttl=2.65, projectile_type="plasma")
                    _fire_ring(state, enemy.pos, count=8, speed=proj_speed * 0.8, damage=max(1, dmg - 1), ttl=2.45, start_deg=enemy.t * 30.0, projectile_type="bullet")
                else:
                    # Dense forward curtain: multiple narrow fans to force lane changes.
                    for off in (-18.0, -6.0, 6.0, 18.0):
                        a = _rotate(aim, off)
                        _fire_fan(state, enemy.pos, a, count=4, spread_deg=28.0, speed=proj_speed, damage=dmg + 1, ttl=2.5, projectile_type="plasma")
                    _fire_ring(state, enemy.pos, count=10, speed=proj_speed * 0.82, damage=dmg, ttl=2.55, start_deg=enemy.t * 38.0, projectile_type="bullet")

                # Beam checks to punish straight-line movement.
                beam_len = config.ROOM_RADIUS * 2.0
                if phase >= 1:
                    offsets = (-22.0, 22.0) if phase == 1 else (-30.0, 0.0, 30.0)
                    for off in offsets:
                        d2 = _rotate(aim, off)
                        state.lasers.append(
                            LaserBeam(
                                start=Vec2(enemy.pos.x, enemy.pos.y),
                                end=enemy.pos + d2 * beam_len,
                                damage=_boss_damage(state, base=10.0, wave_scale=0.2, cap=24),
                                thickness=8.0 if phase == 1 else 8.8,
                                warn=0.56 if phase == 1 else 0.5,
                                ttl=0.12,
                                color=(190, 210, 255),
                                owner="enemy",
                            )
                        )

                # Minion support.
                adds_cap = _boss_adds_cap(state, 4)
                if len(getattr(state, "enemies", [])) < adds_cap and random.random() < (0.14 if phase == 2 else 0.09):
                    pos = enemy.pos + Vec2(random.uniform(-85, 85), random.uniform(-85, 85))
                    add_behavior = "flyer" if random.random() < 0.6 else "ranged"
                    state.enemies.append(Enemy(pos=pos, hp=16 + state.wave * 2, speed=74 + state.wave * 1.8, behavior=add_behavior))

                base_cd = 1.65 - state.wave * 0.008
                enemy.attack_cd = _boss_cd(state, base_cd, phase, floor=0.86, persona=persona)
            return

        if enemy.behavior == "boss_womb_core":
            # Inspired by Mom's Heart style: pulse slams + organic projectile bursts.
            dvec = player_pos - enemy.pos
            d = dvec.length()
            dir_to = dvec.normalized() if d > 1e-6 else Vec2(1, 0)
            phase = int(enemy.ai.get("phase", 0))
            persona = str(enemy.ai.get("persona", "aggressive"))

            desired = 235.0 if phase == 0 else 218.0 if phase == 1 else 200.0
            wobble = Vec2(math.sin(enemy.t * 1.5), math.cos(enemy.t * 1.9)) * 0.3
            if d > desired + 15.0:
                move = (dir_to * 0.82 + wobble).normalized()
            elif d < desired - 15.0:
                move = ((dir_to * -1.0) * 0.72 + wobble).normalized()
            else:
                move = (Vec2(-dir_to.y, dir_to.x) * 0.82 + wobble).normalized()
            enemy.pos = enemy.pos + move * enemy.speed * dt * 0.88

            enemy.attack_cd -= dt
            if enemy.attack_cd <= 0.0:
                if not hasattr(state, "traps"):
                    state.traps = []

                # Telegraph pulse around player then strike.
                pulse_r = 92.0 if phase < 2 else 104.0
                pulse_dmg = _boss_damage(state, base=13.0, wave_scale=0.24, cap=28)
                _append_trap_capped(state, Trap(pos=Vec2(player_pos.x, player_pos.y), radius=pulse_r + 18.0, damage=0, ttl=0.86, armed_delay=0.42, kind="womb_warn"))
                _append_trap_capped(state, Trap(pos=Vec2(player_pos.x, player_pos.y), radius=pulse_r, damage=pulse_dmg, ttl=0.58, armed_delay=0.42, kind="womb_pulse"))

                proj_speed = 212.0 + state.wave * 1.9
                dmg = _boss_damage(state, base=6.0, wave_scale=0.15, cap=18)
                aim = _lead_dir(enemy.pos, player_pos, player_vel, proj_speed, mult=0.78)
                gun = _cycle_gun(enemy, ["spread", "bullet", "plasma"])

                # Main blood-burst patterns.
                if phase == 0:
                    _fire_fan(state, enemy.pos, aim, count=5, spread_deg=68.0, speed=proj_speed, damage=dmg, ttl=2.6, projectile_type=gun)
                elif phase == 1:
                    _fire_fan(state, enemy.pos, aim, count=7, spread_deg=82.0, speed=proj_speed, damage=dmg + 1, ttl=2.65, projectile_type=gun)
                    _fire_ring(state, enemy.pos, count=7, speed=proj_speed * 0.8, damage=max(1, dmg - 1), ttl=2.5, start_deg=enemy.t * 24.0, projectile_type="bullet")
                else:
                    _fire_fan(state, enemy.pos, aim, count=8, spread_deg=92.0, speed=proj_speed, damage=dmg + 2, ttl=2.65, projectile_type=gun)
                    _fire_fan(state, enemy.pos, _perp(aim), count=5, spread_deg=40.0, speed=proj_speed * 0.94, damage=dmg + 1, ttl=2.5, projectile_type="spread")
                    _fire_ring(state, enemy.pos, count=8, speed=proj_speed * 0.84, damage=dmg, ttl=2.55, start_deg=enemy.t * 32.0, projectile_type="plasma")

                # Summon mixed rushers to keep pressure.
                adds_cap = _boss_adds_cap(state, 4)
                if len(getattr(state, "enemies", [])) < adds_cap:
                    summon_n = 1 if phase == 0 else 2
                    if phase == 2 and random.random() < 0.35:
                        summon_n = 1
                    for _ in range(summon_n):
                        if len(getattr(state, "enemies", [])) >= adds_cap:
                            break
                        pos = enemy.pos + Vec2(random.uniform(-70, 70), random.uniform(-70, 70))
                        add_behavior = "swarm" if random.random() < 0.7 else "charger"
                        state.enemies.append(Enemy(pos=pos, hp=14 + state.wave * 2, speed=86 + state.wave * 1.6, behavior=add_behavior))

                base_cd = 2.05 - state.wave * 0.009
                enemy.attack_cd = _boss_cd(state, base_cd, phase, floor=0.9, persona=persona)
            return
    else:
        if hasattr(enemy.behavior, "update"):
            _dispatch_behavior_update(enemy.behavior, enemy, player_pos, state, dt, game, player_vel)


def _dispatch_behavior_update(behavior_impl, enemy: Enemy, player_pos: Vec2, state, dt: float, game, player_vel: Vec2) -> None:
    """Call behavior.update with backward-compatible argument mapping."""
    updater = getattr(behavior_impl, "update", None)
    if not callable(updater):
        return

    kwargs = {}
    try:
        params = inspect.signature(updater).parameters
    except Exception:
        params = {}

    if "game" in params:
        kwargs["game"] = game
    if "player_vel" in params:
        kwargs["player_vel"] = player_vel

    try:
        updater(enemy, player_pos, state, dt, **kwargs)
        return
    except TypeError as exc:
        msg = str(exc)
        arg_mismatch = (
            "positional argument" in msg
            or "unexpected keyword argument" in msg
            or "required positional argument" in msg
        )
        if not arg_mismatch:
            raise

    # Legacy fallbacks for behavior modules with non-uniform signatures.
    for args in (
        (enemy, player_pos, state, dt, player_vel),
        (enemy, player_pos, state, dt, game, player_vel),
        (enemy, player_pos, state, dt),
    ):
        try:
            updater(*args)
            return
        except TypeError:
            continue

    # Let the original updater error surface if all compatibility calls failed.
    updater(enemy, player_pos, state, dt, **kwargs)
