"""Base class for enemy behaviors."""
from abc import ABC, abstractmethod

from hazards import LaserBeam
from utils import Vec2

# Windup aim lines are LaserBeams with zero damage. States only hurts the player for
# owner == "enemy", so this owner keeps the line purely visual and it is removed when the windup ends.
TELEGRAPH_OWNER = "telegraph"
TELEGRAPH_COLOR = (235, 235, 230)
TELEGRAPH_THICKNESS = 5.0


class Behavior(ABC):
    """Abstract base class for enemy behaviors."""

    @abstractmethod
    def update(self, enemy, player_pos, state, dt, player_vel, game=None):
        """Update the enemy's state based on its behavior."""
        pass


def add_windup_telegraph(state, start: Vec2, end: Vec2, duration: float) -> LaserBeam:
    """Draw an aim line from start to end for the next `duration` seconds of a windup."""
    beam = LaserBeam(
        start=Vec2(start.x, start.y),
        end=Vec2(end.x, end.y),
        damage=0,
        thickness=TELEGRAPH_THICKNESS,
        ttl=0.0,
        warn=max(0.01, float(duration)),
        color=TELEGRAPH_COLOR,
        owner=TELEGRAPH_OWNER,
    )
    if not hasattr(state, "lasers"):
        state.lasers = []
    state.lasers.append(beam)
    return beam


def set_windup_telegraph(beam, start: Vec2, end: Vec2) -> None:
    """Re-aim an aim line returned by add_windup_telegraph while its windup is still running."""
    if beam is None:
        return
    beam.start = Vec2(start.x, start.y)
    beam.end = Vec2(end.x, end.y)
