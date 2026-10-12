"""Base class for enemy behaviors."""
from abc import ABC, abstractmethod


def sustained_cd_scale(enemy) -> float:
    """Half-strength spawn attack multiplier for sustained (non-boss) attack cooldowns.

    level.py already shortens the first cooldown by the full clamped ``attack_mult``.
    Sustained resets divide by half of that deviation from 1.0, so a spitter (1.5)
    fires about 1.25x as often instead of 1.5x, and a tank (0.9) reloads about 5% slower.
    Returns 1.0 when the enemy carries no multiplier.
    """
    ai = getattr(enemy, "ai", None) or {}
    m = min(1.6, max(0.6, float(ai.get("attack_mult", 1.0))))
    return 1.0 + (m - 1.0) * 0.5


class Behavior(ABC):
    """Abstract base class for enemy behaviors."""

    @abstractmethod
    def update(self, enemy, player_pos, state, dt, player_vel, game=None):
        """Update the enemy's state based on its behavior."""
        pass
