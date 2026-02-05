"""Hazards and transient combat effects (traps, laser beams)."""

from dataclasses import dataclass

from utils import Vec2


@dataclass
class Trap:
    """Stationary hazard placed by enemies."""

    pos: Vec2
    radius: float = 26.0
    damage: int = 14
    ttl: float = 10.0
    armed_delay: float = 0.4
    kind: str = "spike"
    t: float = 0.0


@dataclass
class LaserBeam:
    """Instant beam effect (drawn briefly) and its endpoints in world space."""

    start: Vec2
    end: Vec2
    damage: int
    thickness: float = 10.0
    ttl: float = 0.08
