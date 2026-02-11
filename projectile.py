"""Projectile entity and related functionality."""

from dataclasses import dataclass

from utils import Vec2


@dataclass
class Projectile:
    """Projectile entity."""
    pos: Vec2
    vel: Vec2
    damage: int
    ttl: float = 2.0
    owner: str = "player"  # "player" or "enemy"
    projectile_type: str = "bullet"  # "bullet", "spread", "missile", "plasma"
