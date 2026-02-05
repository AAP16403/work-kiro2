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
    warn: float = 0.0
    t: float = 0.0
    color: tuple[int, int, int] = (255, 120, 255)
    owner: str = "player"  # "player" or "enemy"
    hit_done: bool = False


@dataclass
class ThunderLine:
    """A lightning strike line across the room."""

    start: Vec2
    end: Vec2
    damage: int = 18
    thickness: float = 16.0
    ttl: float = 0.18
    warn: float = 0.45
    t: float = 0.0
    color: tuple[int, int, int] = (170, 200, 255)
    owner: str = "enemy"
    hit_done: bool = False
