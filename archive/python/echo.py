"""Echo: the frame a dash ends, the pod drops one homing echo at the dash end point.

states.py calls on_dash_end once per dash, on the frame player.is_dashing turns False after the dash timer runs
out, after the end point has been clamped to the arena. A dash makes exactly one such transition, so it drops one
echo, and a dash cannot be chained into echo spam.

The echo is an ordinary player-owned Projectile with projectile_type "echo". The bullet loops in states.py handle
its hits, its ttl and its removal, and it hits as a player shot for ECHO_DAMAGE_PERCENT of the effective player
damage. This module adds the homing and the ring pulse:

    - steer() turns the echo toward the nearest live enemy within ECHO_HOMING_RANGE, for the first
      ECHO_HOMING_SECONDS of its life. It turns by at most ECHO_HOMING_TURN_RATE radians per second and keeps its
      speed, the same way shot_mods.steer_homing steers a bullet. Its own timer governs it, so the Homing pickup
      does not add to it.
    - the drop puts one ring on the particle system's shockwave at the drop point. With reduced motion the ring
      holds its full size and only fades.

Nothing here draws from the run RNG, so replays stay deterministic. steer() runs every frame for each live echo
and keeps no objects alive: it reads the enemy list and writes the echo's velocity in place. A drop creates one
Projectile and one ring particle, once per dash, not per frame.

Every number comes from config.py. The switch is ENABLE_ECHO.
"""

import math

import config
import motion
from projectile import Projectile
from utils import Vec2

ECHO_TYPE = "echo"
# The run-clock time the echo was dropped. Set on the Projectile, read by steer().
_BORN_ATTR = "_echo_born"
# The set of enemy ids a projectile has already hit. Set by the bullet loop in states.py.
_HIT_ATTR = "_hit_entities"


def echo_damage(player_damage) -> int:
    """Echo damage for a player damage value: ECHO_DAMAGE_PERCENT of it, rounded half up, and at least 1.

    Integer arithmetic: (d * p + 50) // 100 is d * p / 100 rounded half up, for whole damage and a whole percent.
    """
    d = int(player_damage)
    p = int(config.ECHO_DAMAGE_PERCENT)
    return max(1, (d * p + 50) // 100)


def is_echo(p) -> bool:
    """True for a player-owned echo projectile. Every other projectile is left alone."""
    return getattr(p, "projectile_type", "") == ECHO_TYPE and getattr(p, "owner", "") == "player"


def drop_echo(player, projectiles: list, damage: int, now: float, particles=None) -> Projectile:
    """Drop one echo at the player's position, flying along the dash direction. Returns the new projectile.

    ``projectiles`` is the run's projectile list, appended to in place. ``particles`` is the ParticleSystem for the
    ring pulse, or None to skip the ring. With no usable dash direction the echo flies along +x.
    """
    d = player.dash_direction
    length = d.length()
    if length > 1e-9:
        dx = d.x / length
        dy = d.y / length
    else:
        dx = 1.0
        dy = 0.0
    speed = float(config.ECHO_SPEED)
    drop = Vec2(float(player.pos.x), float(player.pos.y))
    p = Projectile(
        pos=drop,
        vel=Vec2(dx * speed, dy * speed),
        damage=int(damage),
        ttl=float(config.ECHO_TTL),
        owner="player",
        projectile_type=ECHO_TYPE,
    )
    setattr(p, _BORN_ATTR, float(now))
    projectiles.append(p)
    if particles is not None:
        particles.add_shockwave(
            drop, config.ECHO_COLOR,
            max_radius=float(config.ECHO_RING_RADIUS), ttl=float(config.ECHO_RING_SECONDS),
            grow=not motion.reduced(),
        )
    return p


def on_dash_end(game, s):
    """Called by states.py once, when a dash ends. Drops the dash's one echo unless ENABLE_ECHO is off.

    Returns the new echo projectile, or None when the switch is off or there is no player.
    """
    if not config.ENABLE_ECHO:
        return None
    player = getattr(game, "player", None)
    if player is None:
        return None
    damage = echo_damage(game._effective_player_damage())
    return drop_echo(player, s.projectiles, damage, s.time, getattr(game, "particle_system", None))


def nearest_echo_target(pos: Vec2, enemies, skip_ids=()):
    """Nearest live enemy within ECHO_HOMING_RANGE of ``pos``, ignoring ids in ``skip_ids``. None when there is none."""
    range_sq = float(config.ECHO_HOMING_RANGE) ** 2
    px = float(pos.x)
    py = float(pos.y)
    best = None
    best_d2 = range_sq
    for e in enemies:
        if e.hp <= 0 or getattr(e, "_is_dead", False) or id(e) in skip_ids:
            continue
        dx = e.pos.x - px
        dy = e.pos.y - py
        d2 = dx * dx + dy * dy
        if d2 <= range_sq and (best is None or d2 < best_d2):
            best = e
            best_d2 = d2
    return best


def steer(p, enemies, now: float, dt: float):
    """Turn a live echo toward the nearest live enemy during its homing window. Call before p.update.

    Returns the enemy the echo is steering toward, or None when nothing is steered this call. Past
    ECHO_HOMING_SECONDS the echo flies straight. Other projectiles pass through untouched.
    """
    if not is_echo(p):
        return None
    born = getattr(p, _BORN_ATTR, None)
    if born is None or float(now) - float(born) >= float(config.ECHO_HOMING_SECONDS):
        return None
    target = nearest_echo_target(p.pos, enemies, getattr(p, _HIT_ATTR, None) or ())
    if target is None:
        return None
    dx = float(target.pos.x) - float(p.pos.x)
    dy = float(target.pos.y) - float(p.pos.y)
    if dx * dx + dy * dy <= 1e-18:
        return target
    vx = float(p.vel.x)
    vy = float(p.vel.y)
    speed_sq = vx * vx + vy * vy
    if speed_sq <= 1e-18:
        return target
    speed = math.sqrt(speed_sq)
    cur = math.atan2(vy, vx)
    want = math.atan2(dy, dx)
    diff = (want - cur + math.pi) % math.tau - math.pi
    max_turn = float(config.ECHO_HOMING_TURN_RATE) * float(dt)
    turn = max(-max_turn, min(max_turn, diff))
    ang = cur + turn
    # Write the velocity in place: the echo owns this Vec2, and steering each frame should not allocate.
    p.vel.x = math.cos(ang) * speed
    p.vel.y = math.sin(ang) * speed
    return target
