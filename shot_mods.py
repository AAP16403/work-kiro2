"""Player shot modifiers for the timed powerups: Homing steering and Ricochet bounces.

Both helpers run once per player bullet per tick from PlayingState. They read the run clock and the
expiry fields on the player (see powerup.py), so a bullet only stores its own bounce count. Enemy
projectiles and every other bullet pass through untouched.
"""

import math

import config
from powerup import timed_active
from utils import Vec2

# Normal estimation for the arena edge: probes this far outside the edge, in this many directions.
_NORMAL_PROBES = 64
_NORMAL_PROBE_DIST = 2.0


def arena_inside(p: Vec2, map_type: str, radius: float) -> bool:
    """True when ``p`` is inside the visible arena rim.

    The shapes match the floor drawn in map.py: a circle, a donut (the hole counts as outside),
    a diamond whose tips reach 1.1 * radius, and a cross with arms 0.35 * radius wide.
    """
    x, y = float(p.x), float(p.y)
    r = float(radius)
    if map_type == config.MAP_DIAMOND:
        return abs(x) + abs(y) <= r * 1.1
    if map_type == config.MAP_CROSS:
        w = r * 0.35
        return (abs(x) < w and abs(y) < r) or (abs(x) < r and abs(y) < w)
    dist = math.hypot(x, y)
    if map_type == config.MAP_DONUT:
        return r * 0.4 <= dist <= r
    return dist <= r


def _edge_point(inside_pt: Vec2, outside_pt: Vec2, map_type: str, radius: float) -> Vec2:
    """Bisect the segment from an inside point to an outside point. Returns the inside-side point on the edge."""
    d = outside_pt - inside_pt
    lo, hi = 0.0, 1.0
    for _ in range(12):
        mid = 0.5 * (lo + hi)
        if arena_inside(inside_pt + d * mid, map_type, radius):
            lo = mid
        else:
            hi = mid
    return inside_pt + d * lo


def _outward_normal(b: Vec2, map_type: str, radius: float) -> Vec2:
    """Unit normal pointing out of the arena at edge point ``b``.

    Circles and donuts use the exact radial normal (the donut's inner wall faces the hole). Other
    shapes probe a ring of points just around ``b`` and sum the directions that land outside the
    arena. Their walls run at multiples of 45 degrees, which the 64 probe directions hit exactly,
    so the sum is the wall normal. Only a concave corner gets the bisector.
    """
    if map_type in (config.MAP_CIRCLE, config.MAP_DONUT):
        length = b.length()
        if length > 1e-9:
            radial = b * (1.0 / length)
            if map_type == config.MAP_DONUT and length < float(radius) * 0.7:
                return -radial
            return radial

    nx = 0.0
    ny = 0.0
    for i in range(_NORMAL_PROBES):
        ang = math.tau * i / _NORMAL_PROBES
        dx = math.cos(ang)
        dy = math.sin(ang)
        q = Vec2(b.x + dx * _NORMAL_PROBE_DIST, b.y + dy * _NORMAL_PROBE_DIST)
        if not arena_inside(q, map_type, radius):
            nx += dx
            ny += dy
    n = Vec2(nx, ny).normalized()
    if n.length_squared() <= 1e-12:
        n = b.normalized()
    return n


def ricochet_step(p, player, now: float, map_type: str, radius: float) -> str:
    """Bounce a player bullet once off the arena edge while Ricochet runs.

    Returns "bounced" when the bullet reflected this tick, "spent" when a bullet that has already
    bounced has left the arena again (the caller removes it), and "" otherwise. Bullets fired
    without Ricochet keep their old behaviour: they are never bounced and never removed here.
    """
    if getattr(p, "owner", "player") != "player":
        return ""
    pos = p.pos
    if arena_inside(pos, map_type, radius):
        return ""
    if int(getattr(p, "bounces", 0)) >= int(config.RICOCHET_BOUNCES):
        return "spent"
    if not timed_active(player, "ricochet_until", now):
        return ""
    prev = p.prev_pos if p.prev_pos is not None else pos
    if not arena_inside(prev, map_type, radius):
        return ""

    b = _edge_point(prev, pos, map_type, radius)
    n = _outward_normal(b, map_type, radius)
    vn = p.vel.dot(n)
    if vn <= 0.0:
        return ""

    # Reflect the velocity, and the part of this tick's motion that went past the edge.
    p.vel = p.vel - n * (2.0 * vn)
    overshoot = pos - b
    reflected = overshoot - n * (2.0 * overshoot.dot(n))
    new_pos = b + reflected
    if not arena_inside(new_pos, map_type, radius):
        new_pos = b  # grazing hits can reflect a hair outside; park on the inside edge point
    p.prev_pos = b
    p.pos = new_pos
    p.bounces = int(getattr(p, "bounces", 0)) + 1
    return "bounced"


def steer_velocity(vel: Vec2, desired_dir: Vec2, max_turn: float) -> Vec2:
    """Turn ``vel`` toward ``desired_dir`` by at most ``max_turn`` radians. Speed is kept."""
    speed = vel.length()
    if speed <= 1e-9 or max_turn <= 0.0:
        return vel
    cur = math.atan2(vel.y, vel.x)
    want = math.atan2(desired_dir.y, desired_dir.x)
    diff = (want - cur + math.pi) % math.tau - math.pi
    turn = max(-max_turn, min(max_turn, diff))
    ang = cur + turn
    return Vec2(math.cos(ang), math.sin(ang)) * speed


def nearest_homing_target(pos: Vec2, enemies, skip_ids=()):
    """Nearest live enemy within HOMING_RANGE of ``pos``, ignoring ids in ``skip_ids``. None when there is none."""
    range_sq = float(config.HOMING_RANGE) ** 2
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


def steer_homing(p, enemies, player, now: float, dt: float):
    """Gently steer a player bullet toward the nearest live enemy while Homing runs. Call before p.update.

    Returns the enemy the bullet is steering toward, or None when nothing is steered this call.
    """
    if getattr(p, "owner", "player") != "player" or not timed_active(player, "homing_until", now):
        return None
    target = nearest_homing_target(p.pos, enemies, skip_ids=getattr(p, "_hit_entities", None) or ())
    if target is None:
        return None
    desired = (target.pos - p.pos).normalized()
    if desired.length_squared() <= 1e-12:
        return None
    p.vel = steer_velocity(p.vel, desired, float(config.HOMING_TURN_RATE) * float(dt))
    return target
