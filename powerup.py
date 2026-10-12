"""PowerUp entity and related functionality."""

from dataclasses import dataclass
from typing import TYPE_CHECKING

from config import BOOST_OVERDRIVE_SECONDS, PLAYER_HP, SHIELD_MAX
from drone import DRONE_DURATION
from utils import Vec2
from weapons import WEAPONS, is_weapon_upgrade

if TYPE_CHECKING:
    from player import Player


@dataclass
class PowerUp:
    """PowerUp entity."""
    pos: Vec2
    kind: str  # "heal", "damage", "speed", "firerate", "shield", "laser", "vortex", "weapon", "ultra", "boost", "drone"
    data: str | None = None


def apply_powerup(player: "Player", p: PowerUp, now: float):
    """Apply a powerup effect to the player."""
    if p.kind == "heal":
        cap = int(getattr(player, "max_hp", PLAYER_HP))
        player.hp = min(cap, player.hp + 25)
    elif p.kind == "damage":
        # +1 base is about +10% on every shot once the base scales the whole projectile (see spawn_projectiles).
        player.damage += 1
    elif p.kind == "speed":
        player.speed += 18
    elif p.kind == "firerate":
        # Never raise the fire-rate interval: permanent rewards can already push it below the 0.16 floor.
        player.fire_rate = min(player.fire_rate, max(0.16, player.fire_rate - 0.03))
    elif p.kind == "shield":
        player.shield = min(SHIELD_MAX, player.shield + 45)
    elif p.kind == "laser":
        player.laser_until = max(player.laser_until, now + 8.0)
    elif p.kind == "vortex":
        # A damaging aura that swirls around the player.
        player.vortex_until = max(player.vortex_until, now + 10.0)
    elif p.kind == "weapon":
        # Upgrade-only: equip the pickup only if it outranks the current weapon, otherwise it still pays off as a shield top-up.
        key = str(p.data or "basic").lower()
        candidate = WEAPONS.get(key)
        if candidate is not None and is_weapon_upgrade(getattr(player, "current_weapon", None), candidate):
            player.current_weapon = candidate
        else:
            player.shield = min(SHIELD_MAX, int(getattr(player, "shield", 0)) + 20)
    elif p.kind == "ultra":
        cap = int(getattr(player, "ultra_max_charges", 2))
        player.ultra_charges = min(cap, int(getattr(player, "ultra_charges", 0)) + 1)
    elif p.kind == "boost":
        max_energy = float(getattr(player, "boost_max_energy", 100.0))
        player.boost_energy = max_energy
        player.infinite_boost_until = max(getattr(player, "infinite_boost_until", 0.0), now + BOOST_OVERDRIVE_SECONDS)
        player.shield = min(SHIELD_MAX, int(getattr(player, "shield", 0)) + 20)
    elif p.kind == "drone":
        # Rare companion: one drone orbits for DRONE_DURATION. Re-picking only refreshes the timer; drones never stack.
        player.drone_until = max(float(getattr(player, "drone_until", 0.0)), now + DRONE_DURATION)
