"""PowerUp entity and related functionality."""

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

import config
from config import PLAYER_HP, SHIELD_MAX
from utils import Vec2
from weapons import WEAPONS, is_weapon_upgrade

if TYPE_CHECKING:
    from player import Player


@dataclass
class PowerUp:
    """PowerUp entity."""
    pos: Vec2
    kind: str  # "heal", "damage", "speed", "firerate", "shield", "laser", "vortex", "weapon", "ultra", "boost", "ricochet", "homing", "time_slow", "magnet"
    data: str | None = None


# Kinds whose pickup plays the rare sound and the pickup ring.
RARE_POWERUP_KINDS = frozenset({"ultra", "weapon", "vortex", "laser", "homing", "time_slow"})

# Popup names for kinds whose name is not just the upper-cased kind.
POWERUP_NAMES = {
    "ricochet": "RICOCHET",
    "homing": "HOMING",
    "time_slow": "TIME SLOW",
    "magnet": "MAGNET",
}

# Timed powerups: kind -> (Player field holding the expiry time on the run clock, config name of its duration).
TIMED_POWERUPS = {
    "ricochet": ("ricochet_until", "RICOCHET_DURATION"),
    "homing": ("homing_until", "HOMING_DURATION"),
    "time_slow": ("time_slow_until", "TIME_SLOW_DURATION"),
    "magnet": ("magnet_until", "MAGNET_DURATION"),
}


def is_rare_powerup(kind: str) -> bool:
    """True for the rare tier: rare pickups play pickup_rare and spawn the pickup ring."""
    return str(kind) in RARE_POWERUP_KINDS


def powerup_popup_name(kind: str) -> str:
    """Name shown in the pickup popup."""
    k = str(kind)
    return POWERUP_NAMES.get(k, k.upper())


def timed_active(player: "Player", field: str, now: float) -> bool:
    """True while the timed powerup stored in ``field`` is still running at run time ``now``."""
    return float(now) < float(getattr(player, field, 0.0))


def expire_timed_effects(player: "Player", now: float) -> None:
    """Clear every timed powerup whose expiry has passed, so its state reads as inactive again."""
    for field, _duration_name in TIMED_POWERUPS.values():
        until = float(getattr(player, field, 0.0))
        if until > 0.0 and float(now) >= until:
            setattr(player, field, 0.0)


def enemy_time_scale(player: "Player", now: float) -> float:
    """The one scalar for enemy time. Enemies, their attacks and enemy projectiles advance by frame dt times this."""
    if timed_active(player, "time_slow_until", now):
        return float(config.TIME_SLOW_SCALE)
    return 1.0


def pickup_magnet_mods(player: "Player", now: float) -> tuple[float, float]:
    """(radius multiplier, pull speed multiplier) for pickups. (1.0, 1.0) while Magnet is not running."""
    if timed_active(player, "magnet_until", now):
        return float(config.MAGNET_RADIUS_MULT), float(config.MAGNET_PULL_MULT)
    return 1.0, 1.0


def format_timed_powerups_hud(player: "Player", now: float) -> str:
    """Status-line text for the timed powerups still running, e.g. 'Ricochet 5s  Magnet 9s'. Empty when none run."""
    labels = (
        ("ricochet_until", "Ricochet"),
        ("homing_until", "Homing"),
        ("time_slow_until", "Time Slow"),
        ("magnet_until", "Magnet"),
    )
    parts = []
    for field, label in labels:
        left = float(getattr(player, field, 0.0)) - float(now)
        if left > 0.0:
            parts.append(f"{label} {math.ceil(left)}s")
    return "  ".join(parts)


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
            player.shield = min(120, int(getattr(player, "shield", 0)) + 20)
    elif p.kind == "ultra":
        cap = int(getattr(player, "ultra_max_charges", 2))
        player.ultra_charges = min(cap, int(getattr(player, "ultra_charges", 0)) + 1)
    elif p.kind == "boost":
        max_energy = float(getattr(player, "boost_max_energy", 100.0))
        player.boost_energy = max_energy
        player.infinite_boost_until = max(getattr(player, "infinite_boost_until", 0.0), now + 6.0)
        player.shield = min(SHIELD_MAX, int(getattr(player, "shield", 0)) + 20)
    elif p.kind in TIMED_POWERUPS:
        # Refresh, never stack: picking one up again restarts its full duration.
        field, duration_name = TIMED_POWERUPS[p.kind]
        until = now + float(getattr(config, duration_name))
        setattr(player, field, max(float(getattr(player, field, 0.0)), until))
