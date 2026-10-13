"""Enemy entity and related functionality."""

from dataclasses import dataclass, field
import inspect
import math
import random

from hazards import Trap, LaserBeam, ThunderLine
from projectile import Projectile
import boss_rage
import config
from utils import Vec2, perp, cycle_gun
from enemy_behaviors.base import Behavior
from enemy_behaviors.chase import Chase
from enemy_behaviors.ranged import Ranged
from enemy_behaviors.swarm import Swarm
from enemy_behaviors.charger import Charger
from enemy_behaviors.tank import Tank
from enemy_behaviors.spitter import Spitter
from enemy_behaviors.flyer import Flyer
from enemy_behaviors.engineer import Engineer
from enemy_behaviors.bomber import Bomber
from enemy_steer import Snapshot, SteerBatch, coord_radius, safe_dir as _safe_dir, steer_velocity

_BEHAVIOR_IMPLS = {
    "chaser": Chase(),
    "ranged": Ranged(),
    "swarm": Swarm(),
    "charger": Charger(),
    "tank": Tank(),
    "spitter": Spitter(),
    "flyer": Flyer(),
    "engineer": Engineer(),
    "bomber": Bomber(),
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
    max_hp: int = 0
    is_elite: bool = False
    elite_affix: str = ""
    shield: int = 0
    hit_flash_timer: float = 0.0
    spawn_index: int = -1  # per-run index, set by _assign_run_keys; not in ai, so ai restores never touch it


def _lead_dir(shooter_pos: Vec2, target_pos: Vec2, target_vel: Vec2, proj_speed: float, mult: float = 0.75) -> Vec2:
    d = (target_pos - shooter_pos).length()
    t = (d / max(1.0, float(proj_speed))) * float(mult)
    aim_pos = Vec2(target_pos.x + target_vel.x * t, target_pos.y + target_vel.y * t)
    return _safe_dir(aim_pos - shooter_pos)

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


def _boss_damage(state, base: float, wave_scale: float = 0.22, cap: int = 32) -> int:
    from level import get_difficulty_mods
    d_mods = get_difficulty_mods(str(getattr(state, "difficulty", "normal")))
    mult = float(d_mods.get("hp", 1.0))
    dmg = (float(base) + float(getattr(state, "wave", 1)) * float(wave_scale)) * mult
    return max(1, min(int(round(dmg)), int(cap)))


def _boss_cd(state, base: float, phase: int, floor: float, persona: str = "aggressive") -> float:
    cd = float(base)
    if phase == 1:
        cd *= 0.96
    elif phase >= 2:
        cd *= 0.90
    if str(persona) == "aggressive":
        cd *= 0.97
    d = str(getattr(state, "difficulty", "normal")).lower()
    if d == "easy":
        cd *= 1.12
    elif d == "hard":
        cd *= 0.96
    return max(float(floor), cd)


def _boss_adds_cap(state, bonus: int) -> int:
    # Keep boss encounters tense without flooding the room.
    base = int(getattr(state, "max_enemies", 12))
    return max(base + 1, min(base + int(bonus), base + 4))


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
    """Order key in [0, 1) for a unit with no pinned bias.

    It comes from the unit's per-run spawn index, never from its address: id(enemy) differs between runs,
    so the batch and pool paths could not repeat for a seed. The 7919 step spreads consecutive spawns
    across the range, so flank sides and arc slots are not decided by spawn order alone.
    """
    if "formation_bias" not in enemy.ai:
        enemy.ai["formation_bias"] = ((int(enemy.spawn_index) * 7919) % 997) / 997.0
    return float(enemy.ai["formation_bias"])


_RUN_KEY_STEP = 7919          # spreads consecutive spawn indices over each key's range (prime, as the 997 bias)
_SWARM_SLOTS = 127            # swarm.py's slot_bias range, as in the id(enemy) % 127 key it used to take
_SWARM_RANKS = 97             # swarm.py's squad_rank range, as in the id(enemy) % 97 key it used to take


def _assign_run_keys(enemy: Enemy, state) -> None:
    """Give a unit its per-run spawn index, and the keys its behaviors derive from that index.

    The index counts the units this run has seen, in the order they first tick or first appear in the
    formation. The counter lives on the run's state, so each run starts again from 0, and a run with the
    same seed gives every unit the same index. swarm.py takes slot_bias and squad_rank from id(enemy) only
    when they are missing, so setting them here, from the index, keeps those keys off object addresses.
    """
    if enemy.spawn_index < 0:
        index = int(getattr(state, "enemy_spawn_count", 0))
        state.enemy_spawn_count = index + 1
        enemy.spawn_index = index
    ai = enemy.ai
    if "slot_bias" not in ai:
        ai["slot_bias"] = ((enemy.spawn_index * _RUN_KEY_STEP) % _SWARM_SLOTS) / float(_SWARM_SLOTS) * math.tau
    if "squad_rank" not in ai:
        ai["squad_rank"] = ((enemy.spawn_index * _RUN_KEY_STEP) % _SWARM_RANKS) / float(_SWARM_RANKS)


def _build_role_formation(state, player_pos: Vec2, player_vel: Vec2) -> dict:
    now = float(getattr(state, "time", 0.0))
    cached = getattr(state, "_role_formation", None)
    if cached and abs(float(cached.get("t", -999.0)) - now) <= 1e-8:
        return cached

    for e in getattr(state, "enemies", []):
        _assign_run_keys(e, state)  # a unit spawned since the last tick still gets its index before it is ordered
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


def _holding_telegraph(enemy: Enemy, key: str) -> bool:
    """True while a unit is in a windup or cooldown that its own behavior has to keep fully stopped."""
    ai = enemy.ai
    if key == "charger":
        return ai.get("state") in ("WINDUP", "COOLDOWN")
    if key == "flyer":
        return ai.get("state") == "WINDUP"
    if key == "chaser":
        return float(ai.get("lunge_windup", 0.0)) > 0.0 or float(ai.get("lunge_t", 0.0)) > 0.0
    return False


def _apply_type_coordination(enemy: Enemy, player_pos: Vec2, state, dt: float, player_vel: Vec2) -> None:
    """Apply role-based formation/cohesion pressure after per-type behavior update.

    The steering math is enemy_steer.steer_velocity, shared with the batch path in parallel.py.
    """
    if dt <= 0.0:
        return

    key = _behavior_key(enemy)
    if not key or key.startswith("boss_"):
        return

    if _holding_telegraph(enemy, key):
        # Behaviors own the velocity during windups and cooldowns, so the stop stays a real stop.
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
    coord_r = coord_radius(key)
    r2 = coord_r * coord_r
    nearby = []
    for o in enemies:
        if o is enemy:
            continue
        ok = _behavior_key(o)
        if ok.startswith("boss_"):
            continue
        if (o.pos - enemy.pos).length_squared() > r2:
            continue
        nearby.append((o.pos, ok == key))

    slot_target = slot_targets.get(id(enemy))
    if slot_target is None:
        to_player = _safe_dir(player_pos - enemy.pos)
        slot_target = player_pos + to_player * _slot_radius(key)

    new_vel, lock_t = steer_velocity(
        key,
        enemy.pos,
        enemy.vel,
        enemy.speed,
        float(enemy.ai.get("forward_lock_t", 0.0)),
        slot_target,
        role,
        player_pos,
        prof,
        dt,
        nearby,
    )
    enemy.vel = new_vel
    enemy.ai["forward_lock_t"] = lock_t


def steer_snapshot(state, player_pos: Vec2, player_vel: Vec2, dt: float, steered_ids) -> tuple:
    """Snapshot every non-boss enemy for enemy_steer.steer_chunk, taken after their behaviors ran.

    Returns ``(batch, owners)``; ``owners[i]`` is the Enemy behind ``batch.snaps[i]``. A unit is
    steered only when its ``id`` is in ``steered_ids``, it is eligible for coordination, and dt > 0.
    Formation targets come from the live ``_build_role_formation``, so both paths agree on them.
    """
    formation = _build_role_formation(state, player_pos, player_vel)
    slot_targets = formation["slot_targets"]
    role_map = formation["roles"]
    prof = formation["profile"]
    snaps = []
    owners = []
    for e in getattr(state, "enemies", []):
        key = _behavior_key(e)
        if key.startswith("boss_"):
            continue
        eligible = bool(key) and isinstance(e.behavior, str) and e.behavior in _BEHAVIOR_IMPLS
        if eligible and _holding_telegraph(e, key):
            eligible = False
        target = slot_targets.get(id(e))
        if target is None:
            to_player = _safe_dir(player_pos - e.pos)
            target = player_pos + to_player * _slot_radius(key)
        snaps.append(
            Snapshot(
                x=float(e.pos.x),
                y=float(e.pos.y),
                vx=float(e.vel.x),
                vy=float(e.vel.y),
                key=key,
                speed=float(e.speed),
                seed=float(e.seed),
                lock_t=float(e.ai.get("forward_lock_t", 0.0)),
                tx=float(target.x),
                ty=float(target.y),
                role=role_map.get(id(e), _role_for_behavior(key)),
                steer=bool(eligible and dt > 0.0 and id(e) in steered_ids),
            )
        )
        owners.append(e)
    batch = SteerBatch(
        snaps=tuple(snaps),
        px=float(player_pos.x),
        py=float(player_pos.y),
        dt=float(dt),
        pressure_mult=float(prof["pressure_mult"]),
        steer_mult=float(prof["steer_mult"]),
    )
    return batch, owners


def _update_boss_thunder(enemy: Enemy, player_pos: Vec2, state, dt: float, game, player_vel: Vec2) -> None:
    phase = int(enemy.ai.get("phase", 0))
    persona = str(enemy.ai.get("persona", "aggressive"))
    
    state_key = "thunder_state"
    state_timer = "thunder_timer"
    if state_key not in enemy.ai:
        enemy.ai[state_key] = "stalk"
        enemy.ai[state_timer] = 1.5

    st = enemy.ai[state_key]
    enemy.ai[state_timer] = max(0.0, float(enemy.ai.get(state_timer, 0.0)) - dt)
    timer = enemy.ai[state_timer]

    if st == "stalk":
        dvec = player_pos - enemy.pos
        dir_to = _safe_dir(dvec)
        drift = _rotate(dir_to, 90 if enemy.seed > 3.14 else -90)
        enemy.pos = enemy.pos + drift * enemy.speed * 0.4 * dt

        if timer <= 0:
            enemy.ai[state_key] = "teleport_out"
            enemy.ai[state_timer] = 0.4

    elif st == "teleport_out":
        if timer <= 0:
            angle = state.rng.uniform(0, math.tau)
            dist = state.rng.uniform(200, 350)
            offset = Vec2(math.cos(angle), math.sin(angle)) * dist
            target = player_pos + offset
            if target.length() > config.ROOM_RADIUS * 0.9:
                target = target.normalized() * (config.ROOM_RADIUS * 0.85)
            
            enemy.pos = target
            enemy.ai[state_key] = "teleport_in"
            enemy.ai[state_timer] = 0.25

    elif st == "teleport_in":
        if timer <= 0:
            enemy.ai[state_key] = "attack"
            enemy.ai[state_timer] = 0.1

    elif st == "attack":
        atk_roll = state.rng.random()
        proj_speed = 210.0 + state.wave * 2.0
        dmg = _boss_damage(state, base=5.0, wave_scale=0.14, cap=16)

        if atk_roll < 0.38 or (phase >= 1 and atk_roll < 0.7):
            if not hasattr(state, "thunders"):
                state.thunders = []
            
            line_count = 1 if phase == 0 else 2
            if persona == "aggressive" and phase >= 2:
                line_count += 1
            
            for _ in range(line_count):
                angle = state.rng.uniform(0, math.tau)
                dirv = Vec2(math.cos(angle), math.sin(angle))
                perp_v = Vec2(-dirv.y, dirv.x)
                offset = state.rng.uniform(-150, 150)
                anchor = player_pos + perp_v * offset
                span = config.ROOM_RADIUS * 2.2
                start = anchor - dirv * span
                end = anchor + dirv * span
                th_dmg = _boss_damage(state, base=12.0, wave_scale=0.22, cap=26)
                state.thunders.append(ThunderLine(start=start, end=end, damage=th_dmg, thickness=14.0, warn=1.0, ttl=0.16))

        if atk_roll > 0.3:
            ring_cnt = boss_rage.volley(enemy, 8 if phase == 0 else 10)
            gun = cycle_gun(enemy, ["plasma", "bullet"])
            _fire_ring(state, enemy.pos, ring_cnt, proj_speed * 0.9, dmg, projectile_type=gun)
            
            if phase >= 2 and state.rng.random() < 0.45:
                _fire_ring(state, enemy.pos, ring_cnt, proj_speed * 0.75, dmg, start_deg=15.0, projectile_type=gun)

        enemy.ai[state_key] = "stalk"
        cd_base = 2.5 - (state.wave * 0.035) - (phase * 0.2)
        if persona == "aggressive": cd_base *= 0.8
        enemy.ai[state_timer] = boss_rage.cooldown(enemy, max(1.1, cd_base))


def _update_boss_laser(enemy: Enemy, player_pos: Vec2, state, dt: float, game, player_vel: Vec2) -> None:
    phase = int(enemy.ai.get("phase", 0))
    persona = str(enemy.ai.get("persona", "aggressive"))
    
    l_state = enemy.ai.get("laser_state", "reposition")
    l_timer = max(0.0, float(enemy.ai.get("laser_timer", 0.0)) - dt)
    enemy.ai["laser_timer"] = l_timer
    
    if l_state == "reposition":
        if l_timer <= 0:
            corners = [Vec2(config.ROOM_RADIUS*0.8, config.ROOM_RADIUS*0.8),
                       Vec2(-config.ROOM_RADIUS*0.8, config.ROOM_RADIUS*0.8),
                       Vec2(config.ROOM_RADIUS*0.8, -config.ROOM_RADIUS*0.8),
                       Vec2(-config.ROOM_RADIUS*0.8, -config.ROOM_RADIUS*0.8)]
            dest = state.rng.choice(corners)
            enemy.ai["move_target_x"] = dest.x
            enemy.ai["move_target_y"] = dest.y
            enemy.ai["laser_state"] = "moving"
            enemy.ai["laser_timer"] = 3.0

    elif l_state == "moving":
        target = Vec2(float(enemy.ai["move_target_x"]), float(enemy.ai["move_target_y"]))
        dvec = target - enemy.pos
        if dvec.length() < 20 or l_timer <= 0:
            enemy.ai["laser_state"] = "charge"
            enemy.ai["laser_timer"] = 0.75
        else:
            enemy.pos = enemy.pos + _safe_dir(dvec) * enemy.speed * 1.5 * dt

    elif l_state == "charge":
        if l_timer <= 0:
            enemy.ai["laser_state"] = "attack"
            enemy.ai["laser_timer"] = 2.2
            enemy.ai["sweep_angle"] = 0.0
            enemy.ai["laser_tick"] = 0.0

    elif l_state == "attack":
        if not hasattr(state, "lasers"):
            state.lasers = []
        
        to_player = player_pos - enemy.pos
        base_angle = math.degrees(math.atan2(to_player.y, to_player.x))
        
        tick = float(enemy.ai.get("laser_tick", 0.0)) - dt
        if tick > 0.0:
            enemy.ai["laser_tick"] = tick
        else:
            sweep_offset = math.sin(enemy.t * 2.5) * (28.0 + phase * 8.0)
            beams = boss_rage.volley(enemy, 2 if (persona == "aggressive" and phase >= 2) else 1)
            offsets = [sweep_offset, -sweep_offset, 0.0][:beams]
            for off in offsets:
                angle = base_angle + off
                rad = math.radians(angle)
                beam_dir = Vec2(math.cos(rad), math.sin(rad))
                start = enemy.pos
                end = start + beam_dir * config.ROOM_RADIUS * 2.2
                dmg = _boss_damage(state, base=9.5, wave_scale=0.18, cap=20)
                state.lasers.append(
                    LaserBeam(
                        start,
                        end,
                        damage=dmg,
                        thickness=12.0,
                        warn=0.30,
                        ttl=0.13,
                        color=(255, 100, 255),
                        owner="enemy",
                    )
                )
            enemy.ai["laser_tick"] = boss_rage.cooldown(enemy, 0.22 if phase == 0 else 0.18 if phase == 1 else 0.15)
        
        if phase >= 2 and state.rng.random() < 0.01:
             _fire_ring(state, enemy.pos, count=6, speed=170.0, damage=8, projectile_type="plasma")

        if l_timer <= 0:
            enemy.ai["laser_state"] = "reposition"
            enemy.ai["laser_timer"] = boss_rage.cooldown(enemy, 0.7)


def _update_boss_trapmaster(enemy: Enemy, player_pos: Vec2, state, dt: float, game, player_vel: Vec2) -> None:
    dvec = player_pos - enemy.pos
    d = dvec.length()
    dir_to = _safe_dir(dvec)
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
        n = 3 if phase == 0 else 4
        r = 82 if phase < 2 else 92
        base_ang = state.rng.uniform(0, math.tau)
        for i in range(n):
            ang = base_ang + (i / n) * math.tau
            pos = player_pos + Vec2(math.cos(ang), math.sin(ang)) * r
            _append_trap_capped(
                state,
                Trap(
                    pos=pos,
                    radius=26.0,
                    damage=_boss_damage(state, base=12.5, wave_scale=0.2, cap=25),
                    ttl=7.6,
                    armed_delay=0.8,
                    kind="spike",
                ),
            )

        proj_speed = 195.0 + state.wave * 1.7
        dmg = _boss_damage(state, base=5.0, wave_scale=0.14, cap=16)
        aim = _lead_dir(enemy.pos, player_pos, player_vel, proj_speed, mult=0.85)
        if phase == 0:
            if persona != "cautious":
                _fire_fan(state, enemy.pos, aim, count=boss_rage.volley(enemy, 4), spread_deg=56.0, speed=proj_speed, damage=dmg, ttl=2.55, projectile_type="spread")
        elif phase == 1:
            _fire_fan(state, enemy.pos, aim, count=boss_rage.volley(enemy, 6), spread_deg=76.0, speed=proj_speed, damage=dmg + 1, ttl=2.65, projectile_type="spread")
        else:
            _fire_fan(state, enemy.pos, aim, count=boss_rage.volley(enemy, 7), spread_deg=88.0, speed=proj_speed, damage=dmg + 2, ttl=2.55, projectile_type="spread")
            if persona in ("aggressive", "trickster"):
                _fire_fan(state, enemy.pos, perp(aim), count=3, spread_deg=38.0, speed=proj_speed * 0.9, damage=max(1, dmg), ttl=2.3, projectile_type="spread")

        adds_cap = _boss_adds_cap(state, 2)
        if len(getattr(state, "enemies", [])) < adds_cap and state.rng.random() < 0.14:
            pos = enemy.pos + Vec2(state.rng.uniform(-70, 70), state.rng.uniform(-70, 70))
            state.enemies.append(Enemy(pos=pos, hp=22 + state.wave * 3, speed=52.0 + state.wave * 1.2, behavior="engineer"))
        base_cd = 2.35 - state.wave * 0.012
        enemy.attack_cd = boss_rage.cooldown(enemy, _boss_cd(state, base_cd, phase, floor=1.05, persona=persona))


def _update_boss_swarmqueen(enemy: Enemy, player_pos: Vec2, state, dt: float, game, player_vel: Vec2) -> None:
    phase = int(enemy.ai.get("phase", 0))
    persona = str(enemy.ai.get("persona", "aggressive"))
    
    dvec = player_pos - enemy.pos
    if dvec.length() < 300:
        enemy.pos = enemy.pos - _safe_dir(dvec) * enemy.speed * dt * 0.8
    else:
        drift = _rotate(_safe_dir(dvec), 90)
        enemy.pos = enemy.pos + drift * enemy.speed * 0.3 * dt

    enemy.attack_cd -= dt
    if enemy.attack_cd <= 0.0:
        roll = state.rng.random()
        
        adds_cap = _boss_adds_cap(state, 4)
        current_adds = len([e for e in getattr(state, "enemies", []) if not str(e.behavior).startswith("boss")])
        egg_sacs = len([e for e in getattr(state, "enemies", []) if str(e.behavior) == "egg_sac"])
        
        if roll < 0.5 and current_adds < adds_cap and egg_sacs < (2 if phase < 2 else 3):
            count = 1 + (1 if phase >= 1 else 0)
            for _ in range(count):
                ang = state.rng.uniform(0, math.tau)
                dist = state.rng.uniform(40, 80)
                pos = enemy.pos + Vec2(math.cos(ang), math.sin(ang)) * dist
                sac = Enemy(pos=pos, hp=25 + state.wave * 4, speed=0.0, behavior="egg_sac")
                sac.ai["hatch_timer"] = 4.0 if phase == 0 else 3.0
                state.enemies.append(sac)
        
        elif roll < 0.85 or current_adds + 2 > adds_cap:
            proj_speed = 190.0
            dmg = _boss_damage(state, base=6.0, wave_scale=0.15, cap=18)
            aim = _safe_dir(player_pos - enemy.pos)
            _fire_fan(state, enemy.pos, aim, count=boss_rage.volley(enemy, 5 + min(phase, 1)), spread_deg=56.0, speed=proj_speed, damage=dmg, projectile_type="plasma")

        else:
            for _ in range(2):
                 ang = state.rng.uniform(0, math.tau)
                 pos = enemy.pos + Vec2(math.cos(ang), math.sin(ang)) * 60
                 state.enemies.append(Enemy(pos=pos, hp=12, speed=100.0, behavior="swarm"))

        enemy.attack_cd = boss_rage.cooldown(enemy, _boss_cd(state, 2.5, phase, floor=1.2, persona=persona))


def _update_egg_sac(enemy: Enemy, player_pos: Vec2, state, dt: float, game, player_vel: Vec2) -> None:
    enemy.ai["hatch_timer"] = float(enemy.ai.get("hatch_timer", 4.0)) - dt
    if enemy.ai["hatch_timer"] <= 0:
        enemy.hp = -1
        for _ in range(3):
            ang = state.rng.uniform(0, math.tau)
            pos = enemy.pos + Vec2(math.cos(ang), math.sin(ang)) * 20
            state.enemies.append(Enemy(pos=pos, hp=12 + state.wave, speed=110.0, behavior="swarm"))


BRUTE_CHARGE_TIME = 1.2  # seconds the brute keeps charging before it recovers


def brute_charge_speed(speed: float, phase: int) -> float:
    """Charge speed of the brute boss. Shared by its AI and the telegraph lane drawn from it."""
    charge_speed = float(speed) * 2.8
    if int(phase) >= 1:
        charge_speed *= 1.08
    return charge_speed


def _ray_length_to_circle(origin: Vec2, direction: Vec2, radius: float) -> float:
    """Distance along a unit direction from an origin inside a circle to the circle's edge (0 when outside)."""
    b = origin.dot(direction)
    c = origin.length_squared() - radius * radius
    disc = b * b - c
    if disc < 0.0:
        return 0.0
    return max(0.0, -b + math.sqrt(disc))


def brute_charge_lane(enemy: Enemy) -> tuple[Vec2, float] | None:
    """Direction and drawn length of the brute's telegraphed charge, or None outside its telegraph."""
    if enemy.ai.get("brute_state") != "telegraph":
        return None
    direction = Vec2(float(enemy.ai.get("charge_dir_x", 1.0)), float(enemy.ai.get("charge_dir_y", 0.0))).normalized()
    if direction.length_squared() <= 1e-9:
        return None
    reach = brute_charge_speed(enemy.speed, int(enemy.ai.get("phase", 0))) * BRUTE_CHARGE_TIME
    wall = _ray_length_to_circle(enemy.pos, direction, config.ROOM_RADIUS * 0.95)
    return direction, max(0.0, min(reach, wall))


def _update_boss_brute(enemy: Enemy, player_pos: Vec2, state, dt: float, game, player_vel: Vec2) -> None:
    phase_boss = int(enemy.ai.get("phase", 0))
    persona = str(enemy.ai.get("persona", "aggressive"))
    
    b_state = enemy.ai.get("brute_state", "chase")
    b_timer = max(0.0, float(enemy.ai.get("brute_timer", 0.0)) - dt)
    enemy.ai["brute_timer"] = b_timer
    
    if b_state == "chase":
        dvec = player_pos - enemy.pos
        dir_to = _safe_dir(dvec)
        
        speed_mod = 0.75
        if persona == "aggressive": speed_mod = 0.85
        enemy.pos = enemy.pos + dir_to * enemy.speed * speed_mod * dt
        
        if b_timer <= 0:
            enemy.ai["brute_state"] = "telegraph"
            enemy.ai["brute_timer"] = 1.0
            enemy.ai["charge_dir_x"] = dir_to.x
            enemy.ai["charge_dir_y"] = dir_to.y

    elif b_state == "telegraph":
        if b_timer <= 0:
            # The charge keeps the lane drawn during the telegraph: no re-aim at the player here.
            enemy.ai["brute_state"] = "charge"
            enemy.ai["brute_timer"] = BRUTE_CHARGE_TIME

    elif b_state == "charge":
        cx = float(enemy.ai.get("charge_dir_x", 1.0))
        cy = float(enemy.ai.get("charge_dir_y", 0.0))
        charge_dir = Vec2(cx, cy)

        charge_speed = brute_charge_speed(enemy.speed, phase_boss)

        step = charge_dir * charge_speed * dt
        enemy.pos = enemy.pos + step
        
        if enemy.pos.length() > config.ROOM_RADIUS * 0.95:
            enemy.pos = enemy.pos.normalized() * (config.ROOM_RADIUS * 0.95)
            enemy.ai["brute_state"] = "stun"
            enemy.ai["brute_timer"] = 2.0
            
            sw_dmg = _boss_damage(state, base=7.0, wave_scale=0.13, cap=18)
            _spawn_shockwave(state, enemy.pos, count=boss_rage.volley(enemy, 12 + phase_boss * 3), speed=240.0, damage=sw_dmg)
            
        elif b_timer <= 0:
            enemy.ai["brute_state"] = "recover"
            enemy.ai["brute_timer"] = 0.8

    elif b_state == "stun":
        if b_timer <= 0:
            enemy.ai["brute_state"] = "chase"
            enemy.ai["brute_timer"] = boss_rage.cooldown(enemy, 3.0 if phase_boss == 0 else 2.2)

    elif b_state == "recover":
        if b_timer <= 0:
            enemy.ai["brute_state"] = "chase"
            enemy.ai["brute_timer"] = boss_rage.cooldown(enemy, 2.5)


def _update_boss_abyss_gaze(enemy: Enemy, player_pos: Vec2, state, dt: float, game, player_vel: Vec2) -> None:
    dvec = player_pos - enemy.pos
    d = dvec.length()
    dir_to = _safe_dir(dvec)
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

        proj_speed = 218.0 + state.wave * 1.6
        dmg = _boss_damage(state, base=6.0, wave_scale=0.13, cap=16)
        aim = _lead_dir(enemy.pos, player_pos, player_vel, proj_speed, mult=0.72)

        if phase == 0:
            _fire_fan(state, enemy.pos, aim, count=boss_rage.volley(enemy, 6), spread_deg=72.0, speed=proj_speed, damage=dmg, ttl=2.6, projectile_type="plasma")
        elif phase == 1:
            _fire_fan(state, enemy.pos, aim, count=boss_rage.volley(enemy, 7), spread_deg=82.0, speed=proj_speed, damage=dmg + 1, ttl=2.65, projectile_type="plasma")
            _fire_ring(state, enemy.pos, count=8, speed=proj_speed * 0.8, damage=max(1, dmg - 1), ttl=2.45, start_deg=enemy.t * 30.0, projectile_type="bullet")
        else:
            for off in (-14.0, 0.0, 14.0):
                a = _rotate(aim, off)
                # The one extra shot goes to the centre fan of the three.
                n_fan = boss_rage.volley(enemy, 3) if off == 0.0 else 3
                _fire_fan(state, enemy.pos, a, count=n_fan, spread_deg=24.0, speed=proj_speed, damage=dmg + 1, ttl=2.35, projectile_type="plasma")
            _fire_ring(state, enemy.pos, count=8, speed=proj_speed * 0.78, damage=max(1, dmg - 1), ttl=2.4, start_deg=enemy.t * 34.0, projectile_type="bullet")

        beam_len = config.ROOM_RADIUS * 2.0
        if phase >= 1:
            offsets = (-20.0, 20.0) if phase == 1 else (-24.0, 24.0)
            for off in offsets:
                d2 = _rotate(aim, off)
                state.lasers.append(
                    LaserBeam(
                        start=Vec2(enemy.pos.x, enemy.pos.y),
                        end=enemy.pos + d2 * beam_len,
                        damage=_boss_damage(state, base=10.0, wave_scale=0.2, cap=24),
                        thickness=7.2 if phase == 1 else 7.8,
                        warn=0.62 if phase == 1 else 0.58,
                        ttl=0.12,
                        color=(190, 210, 255),
                        owner="enemy",
                    )
                )

        adds_cap = _boss_adds_cap(state, 4)
        if len(getattr(state, "enemies", [])) < adds_cap and state.rng.random() < (0.09 if phase == 2 else 0.06):
            pos = enemy.pos + Vec2(state.rng.uniform(-85, 85), state.rng.uniform(-85, 85))
            add_behavior = "flyer" if state.rng.random() < 0.6 else "ranged"
            state.enemies.append(Enemy(pos=pos, hp=16 + state.wave * 2, speed=74.0 + state.wave * 1.8, behavior=add_behavior))

        base_cd = 1.8 - state.wave * 0.006
        enemy.attack_cd = boss_rage.cooldown(enemy, _boss_cd(state, base_cd, phase, floor=1.0, persona=persona))


def _update_boss_womb_core(enemy: Enemy, player_pos: Vec2, state, dt: float, game, player_vel: Vec2) -> None:
    dvec = player_pos - enemy.pos
    d = dvec.length()
    dir_to = _safe_dir(dvec)
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

        pulse_r = 86.0 if phase < 2 else 94.0
        pulse_dmg = _boss_damage(state, base=11.5, wave_scale=0.2, cap=24)
        _append_trap_capped(state, Trap(pos=Vec2(player_pos.x, player_pos.y), radius=pulse_r + 16.0, damage=0, ttl=1.0, armed_delay=0.52, kind="womb_warn"))
        # ttl must outlive armed_delay, otherwise the trap expires on the same step it would arm and never hurts.
        _append_trap_capped(state, Trap(pos=Vec2(player_pos.x, player_pos.y), radius=pulse_r, damage=pulse_dmg, ttl=0.72, armed_delay=0.52, kind="womb_pulse"))

        proj_speed = 212.0 + state.wave * 1.9
        dmg = _boss_damage(state, base=6.0, wave_scale=0.15, cap=18)
        aim = _lead_dir(enemy.pos, player_pos, player_vel, proj_speed, mult=0.78)
        gun = cycle_gun(enemy, ["spread", "bullet", "plasma"])

        if phase == 0:
            _fire_fan(state, enemy.pos, aim, count=boss_rage.volley(enemy, 5), spread_deg=68.0, speed=proj_speed, damage=dmg, ttl=2.6, projectile_type=gun)
        elif phase == 1:
            _fire_fan(state, enemy.pos, aim, count=boss_rage.volley(enemy, 7), spread_deg=82.0, speed=proj_speed, damage=dmg + 1, ttl=2.65, projectile_type=gun)
            _fire_ring(state, enemy.pos, count=7, speed=proj_speed * 0.8, damage=max(1, dmg - 1), ttl=2.5, start_deg=enemy.t * 24.0, projectile_type="bullet")
        else:
            _fire_fan(state, enemy.pos, aim, count=boss_rage.volley(enemy, 7), spread_deg=86.0, speed=proj_speed, damage=dmg + 1, ttl=2.5, projectile_type=gun)
            _fire_fan(state, enemy.pos, perp(aim), count=4, spread_deg=34.0, speed=proj_speed * 0.9, damage=dmg, ttl=2.35, projectile_type="spread")
            _fire_ring(state, enemy.pos, count=6, speed=proj_speed * 0.78, damage=max(1, dmg - 1), ttl=2.35, start_deg=enemy.t * 30.0, projectile_type="plasma")

        adds_cap = _boss_adds_cap(state, 3)
        if len(getattr(state, "enemies", [])) < adds_cap:
            summon_n = 1 if phase <= 1 else (2 if state.rng.random() < 0.5 else 1)
            for _ in range(summon_n):
                if len(getattr(state, "enemies", [])) >= adds_cap:
                    break
                pos = enemy.pos + Vec2(state.rng.uniform(-70, 70), state.rng.uniform(-70, 70))
                add_behavior = "swarm" if state.rng.random() < 0.7 else "charger"
                state.enemies.append(Enemy(pos=pos, hp=14 + state.wave * 2, speed=86.0 + state.wave * 1.6, behavior=add_behavior))

        base_cd = 2.25 - state.wave * 0.007
        enemy.attack_cd = boss_rage.cooldown(enemy, _boss_cd(state, base_cd, phase, floor=1.15, persona=persona))


def update_enemy(enemy: Enemy, player_pos: Vec2, state, dt: float, game, player_vel: Vec2 | None = None, coordinate: bool = True):
    """Update enemy AI behavior.

    ``coordinate=False`` skips the formation steering pass. The batch path in parallel.py runs
    every behavior first and then steers all units from one snapshot.
    """
    if player_vel is None:
        player_vel = Vec2(0.0, 0.0)

    enemy.t += dt
    if enemy.seed == 0.0:
        enemy.seed = state.rng.uniform(0.0, math.tau)
    _assign_run_keys(enemy, state)  # before the behavior runs, so swarm.py finds its keys already set

    if isinstance(enemy.behavior, str):
        if enemy.behavior == "egg_sac":
            _update_egg_sac(enemy, player_pos, state, dt, game, player_vel)
            return

        if not enemy.behavior.startswith("boss_"):
            behavior_impl = _BEHAVIOR_IMPLS.get(enemy.behavior)
            if behavior_impl is None:
                return
            _dispatch_behavior_update(behavior_impl, enemy, player_pos, state, dt, game, player_vel)
            if coordinate:
                _apply_type_coordination(enemy, player_pos, state, dt, player_vel)
            return

        _boss_init(enemy)
        new_phase = _boss_phase(enemy)
        if int(enemy.ai.get("phase", 0)) != new_phase:
            enemy.ai["phase"] = new_phase
            enemy.attack_cd = min(enemy.attack_cd, 0.35)
        boss_rage.update_rage(enemy, game)

        if enemy.behavior == "boss_thunder":
            _update_boss_thunder(enemy, player_pos, state, dt, game, player_vel)
            return
        if enemy.behavior == "boss_laser":
            _update_boss_laser(enemy, player_pos, state, dt, game, player_vel)
            return
        if enemy.behavior == "boss_trapmaster":
            _update_boss_trapmaster(enemy, player_pos, state, dt, game, player_vel)
            return
        if enemy.behavior == "boss_swarmqueen":
            _update_boss_swarmqueen(enemy, player_pos, state, dt, game, player_vel)
            return
        if enemy.behavior == "boss_brute":
            _update_boss_brute(enemy, player_pos, state, dt, game, player_vel)
            return
        if enemy.behavior == "boss_abyss_gaze":
            _update_boss_abyss_gaze(enemy, player_pos, state, dt, game, player_vel)
            return
        if enemy.behavior == "boss_womb_core":
            _update_boss_womb_core(enemy, player_pos, state, dt, game, player_vel)
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
    params = inspect.signature(updater).parameters

    if "game" in params:
        kwargs["game"] = game
    if "player_vel" in params:
        kwargs["player_vel"] = player_vel

    updater(enemy, player_pos, state, dt, **kwargs)
