"""PowerUp entity and related functionality."""

from dataclasses import dataclass
from typing import TYPE_CHECKING

from config import PLAYER_HP
from utils import Vec2

if TYPE_CHECKING:
    from player import Player


@dataclass
class PowerUp:
    """PowerUp entity."""
    pos: Vec2
    kind: str  # "heal", "damage", "speed", "firerate", "shield", "laser", "vortex"


def apply_powerup(player: "Player", p: PowerUp, now: float):
    """Apply a powerup effect to the player."""
    if p.kind == "heal":
        player.hp = min(PLAYER_HP, player.hp + 25)
    elif p.kind == "damage":
        player.damage += 5
    elif p.kind == "speed":
        player.speed += 18
    elif p.kind == "firerate":
        player.fire_rate = max(0.12, player.fire_rate - 0.04)
    elif p.kind == "shield":
        player.shield = min(120, player.shield + 45)
    elif p.kind == "laser":
        player.laser_until = max(player.laser_until, now + 8.0)
    elif p.kind == "vortex":
        # A damaging aura that swirls around the player.
        player.vortex_until = max(player.vortex_until, now + 10.0)
