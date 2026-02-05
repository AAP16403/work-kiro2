"""Player entity and related functionality."""

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from config import PLAYER_HP, PLAYER_SPEED, PLAYER_DAMAGE, PLAYER_FIRE_RATE
from utils import Vec2

if TYPE_CHECKING:
    from weapons import Weapon


@dataclass
class Player:
    """Player entity."""
    pos: Vec2
    hp: int = PLAYER_HP
    shield: int = 0
    speed: float = PLAYER_SPEED
    damage: int = PLAYER_DAMAGE
    fire_rate: float = PLAYER_FIRE_RATE
    last_shot: float = 0.0
    laser_until: float = 0.0
    vortex_until: float = 0.0
    vortex_radius: float = 70.0
    vortex_dps: float = 38.0
    current_weapon: "Weapon" = field(default=None)  # Will be set in Game.__init__
