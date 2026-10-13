"""Base class for enemy behaviors."""
import math
from abc import ABC, abstractmethod

import config
from hazards import LaserBeam
from utils import Vec2

# Windup aim lines are LaserBeams with zero damage. States only hurts the player for
# owner == "enemy", so this owner keeps the line purely visual and it is removed when the windup ends.
TELEGRAPH_OWNER = "telegraph"
TELEGRAPH_COLOR = (235, 235, 230)
TELEGRAPH_THICKNESS = 5.0


def sustained_cd_scale(enemy) -> float:
    """Half-strength spawn attack multiplier for sustained (non-boss) attack cooldowns.

    level.py already shortens the first cooldown by the full clamped ``attack_mult``.
    Sustained resets divide by half of that deviation from 1.0, so a spitter (1.5)
    fires about 1.25x as often instead of 1.5x, and a tank (0.9) reloads about 5% slower.
    Returns 1.0 when the enemy carries no multiplier.
    """
    ai = getattr(enemy, "ai", None) or {}
    m = min(1.6, max(0.6, float(ai.get("attack_mult", 1.0))))
    return 1.0 + (m - 1.0) * 0.5


def separation_reference(enemy, others, radius: float, weight: float = 1.0) -> Vec2:
    """Inverse-square repulsion, written with Vec2 arithmetic. The reference for ``separation_steer``.

    This is the ``_separation`` that bomber, chase, engineer, ranged, spitter and tank each carried before
    the wave 8 frame work. It runs when ``config.ENABLE_MULTICORE_FRAME`` is off.
    """
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


def separation_steer(enemy, others, radius: float, weight: float = 1.0) -> Vec2:
    """Inverse-square repulsion from ``others`` within ``radius``, scaled to ``weight``.

    Same result as ``separation_reference``, bit for bit. It does the same float operations in the same
    order (``dvec = enemy.pos - o.pos``, ``d = hypot``, ``acc += dvec * (1 / d*d)``, then normalise and
    scale), but it reads the coordinates as floats and makes one Vec2 for the answer, not one per
    neighbour pair. Every behaviour runs this for every unit each step, so the per-pair allocation was
    the cost. With ``config.ENABLE_MULTICORE_FRAME`` off it defers to ``separation_reference``.
    """
    if not config.ENABLE_MULTICORE_FRAME:
        return separation_reference(enemy, others, radius, weight)
    r = float(radius)
    ex = enemy.pos.x
    ey = enemy.pos.y
    acc_x = 0.0
    acc_y = 0.0
    count = 0
    for o in others:
        if o is enemy:
            continue
        op = o.pos
        dx = ex - op.x
        dy = ey - op.y
        d = math.hypot(dx, dy)
        if d <= 1e-6 or d > r:
            continue
        s = 1.0 / (d * d)
        acc_x = acc_x + dx * s
        acc_y = acc_y + dy * s
        count += 1
    if count == 0:
        return Vec2(0.0, 0.0)
    length = math.hypot(acc_x, acc_y)
    if length <= 1e-9:
        return Vec2(0.0, 0.0) * weight
    return Vec2(acc_x / length, acc_y / length) * weight


class Behavior(ABC):
    """Abstract base class for enemy behaviors."""

    @abstractmethod
    def update(self, enemy, player_pos, state, dt, player_vel, game=None):
        """Update the enemy's state based on its behavior."""
        pass


def add_windup_telegraph(state, start: Vec2, end: Vec2, duration: float) -> LaserBeam:
    """Draw an aim line from start to end for the next `duration` seconds of a windup."""
    beam = LaserBeam(
        start=Vec2(start.x, start.y),
        end=Vec2(end.x, end.y),
        damage=0,
        thickness=TELEGRAPH_THICKNESS,
        ttl=0.0,
        warn=max(0.01, float(duration)),
        color=TELEGRAPH_COLOR,
        owner=TELEGRAPH_OWNER,
    )
    if not hasattr(state, "lasers"):
        state.lasers = []
    state.lasers.append(beam)
    return beam


def set_windup_telegraph(beam, start: Vec2, end: Vec2) -> None:
    """Re-aim an aim line returned by add_windup_telegraph while its windup is still running."""
    if beam is None:
        return
    beam.start = Vec2(start.x, start.y)
    beam.end = Vec2(end.x, end.y)
