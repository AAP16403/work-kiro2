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
    kind: str  # "heal", "damage", "speed", "firerate"


def apply_powerup(player: "Player", p: PowerUp):
    """Apply a powerup effect to the player."""
    if p.kind == "heal":
        player.hp = min(PLAYER_HP, player.hp + 25)
    elif p.kind == "damage":
        player.damage += 5
    elif p.kind == "speed":
        player.speed += 18
    elif p.kind == "firerate":
        player.fire_rate = max(0.12, player.fire_rate - 0.04)
