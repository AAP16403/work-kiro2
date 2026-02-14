"""Base class for enemy behaviors."""
from abc import ABC, abstractmethod

class Behavior(ABC):
    """Abstract base class for enemy behaviors."""

    @abstractmethod
    def update(self, enemy, player_pos, state, dt, player_vel):
        """Update the enemy's state based on its behavior."""
        pass
