"""PowerUp entity and related functionality."""

from dataclasses import dataclass
from typing import TYPE_CHECKING

from config import PLAYER_HP, ULTRA_MAX_CHARGES
from utils import Vec2
from weapons import WEAPONS

if TYPE_CHECKING:
    from player import Player


@dataclass
class PowerUp:
    """PowerUp entity."""
    pos: Vec2
    kind: str  # "heal", "damage", "speed", "firerate", "shield", "laser", "vortex", "weapon", "ultra"
    data: str | None = None


def apply_powerup(player: "Player", p: PowerUp, now: float):
    """Apply a powerup effect to the player."""
    if p.kind == "heal":
        cap = int(getattr(player, "max_hp", PLAYER_HP))
        player.hp = min(cap, player.hp + 25)
    elif p.kind == "damage":
        player.damage += 4
    elif p.kind == "speed":
        player.speed += 18
    elif p.kind == "firerate":
        player.fire_rate = max(0.16, player.fire_rate - 0.03)
    elif p.kind == "shield":
        player.shield = min(120, player.shield + 45)
    elif p.kind == "laser":
        player.laser_until = max(player.laser_until, now + 8.0)
    elif p.kind == "vortex":
        # A damaging aura that swirls around the player.
        player.vortex_until = max(player.vortex_until, now + 10.0)
    elif p.kind == "weapon":
        key = str(p.data or "basic").lower()
        if key in WEAPONS:
            player.current_weapon = WEAPONS[key]
    elif p.kind == "ultra":
        player.ultra_charges = min(ULTRA_MAX_CHARGES, int(getattr(player, "ultra_charges", 0)) + 1)
