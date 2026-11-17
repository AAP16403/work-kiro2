"""Physics and collision detection logic."""

from dataclasses import dataclass
from typing import Protocol,runtime_checkable

from utils import Vec2

@runtime_checkable
class PhysicalEntity(Protocol):
    pos: Vec2
    radius: float

def resolve_circle_obstacles(pos: Vec2, radius: float, obstacles: list[PhysicalEntity], iterations: int = 4) -> Vec2:
    """Push a circle out of overlapping circular obstacles.

    `obstacles` is expected to have `pos` and `radius` attributes.
    """
    p = Vec2(pos.x, pos.y)
    for _ in range(max(1, iterations)):
        moved = False
        for o in obstacles:
            op = o.pos
            r = radius + float(o.radius)
            d = p - op
            l = d.length()
            if l >= r:
                continue
            if l <= 1e-6:
                # Nudge in a stable direction.
                d = Vec2(1.0, 0.0)
                l = 1.0
            push = (r - l) / l
            p = Vec2(p.x + d.x * push, p.y + d.y * push)
            moved = True
        if not moved:
            break
    return p

def check_circle_collision(pos1: Vec2, r1: float, pos2: Vec2, r2: float) -> bool:
    """Check if two circles overlap."""
    d_sq = (pos1 - pos2).length_squared()
    r_sum = r1 + r2
    return d_sq < (r_sum * r_sum)

