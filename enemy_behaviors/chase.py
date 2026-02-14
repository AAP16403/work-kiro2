"""Chase behavior for enemies."""
from enemy_behaviors.base import Behavior
from utils import Vec2
import math

def _perp(v: Vec2) -> Vec2:
    return Vec2(-v.y, v.x)

class Chase(Behavior):
    """A simple chase behavior."""

    def update(self, enemy, player_pos, state, dt, player_vel):
        """Update the enemy's state based on its behavior."""
        # Pursuit + slight zig-zag + separation.
        
        # Improved pursuit logic: predict player's future position
        dist_to_player = (player_pos - enemy.pos).length()
        look_ahead_time = dist_to_player / enemy.speed if enemy.speed > 0 else 0
        predicted_player_pos = player_pos + player_vel * look_ahead_time

        dir_to = (predicted_player_pos - enemy.pos).normalized()
        
        # Add some zig-zag to make movement less predictable
        zig = _perp(dir_to) * (0.22 * math.sin(enemy.t * 2.6 + enemy.seed))
        
        # Simple separation from other enemies
        sep = self._separation(enemy, state.enemies, radius=44.0, weight=1.1)
        
        move = (dir_to + zig + sep).normalized()
        enemy.vel = move * enemy.speed
        enemy.pos = enemy.pos + enemy.vel * dt

    def _separation(self, enemy, others, radius: float, weight: float = 1.0) -> Vec2:
        """Repel from nearby enemies to reduce stacking."""
        r = float(radius)
        acc = Vec2(0.0, 0.0)
        count = 0
        for o in others:
            if o is enemy:
                continue
            dvec = enemy.pos - o.pos
            d = dvec.length()
            if d <= 1e-6 or d > r:
                continue
            acc = acc + dvec * (1.0 / (d * d))
            count += 1
        if count == 0:
            return Vec2(0.0, 0.0)
        return acc.normalized() * weight
