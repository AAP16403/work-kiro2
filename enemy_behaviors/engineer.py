"""Engineer behavior for enemies."""
from enemy_behaviors.base import Behavior
from utils import Vec2
from hazards import Trap
import random
import config

def _perp(v: Vec2) -> Vec2:
    return Vec2(-v.y, v.x)

def _append_trap_capped(state, trap: Trap) -> bool:
    """Append trap only if construction cap has room."""
    if not hasattr(state, "traps"):
        state.traps = []
    cap = max(0, int(getattr(config, "MAX_ACTIVE_CONSTRUCTIONS", 14)))
    if len(state.traps) >= cap:
        return False
    state.traps.append(trap)
    return True

class Engineer(Behavior):
    """An engineer behavior."""

    def update(self, enemy, player_pos, state, dt, player_vel):
        """Update the enemy's state based on its behavior."""
        dvec = player_pos - enemy.pos
        d = dvec.length()
        dir_to = dvec.normalized() if d > 1e-6 else Vec2(0, 0)

        sep = self._separation(enemy, state.enemies, radius=44.0, weight=1.1)

        if d > 260:
            enemy.pos = enemy.pos + dir_to * enemy.speed * dt * 0.85
        elif d < 180:
            enemy.pos = enemy.pos - dir_to * enemy.speed * dt * 0.95
        else:
            strafe = _perp(dir_to) * (1.0 if (id(enemy) % 2) else -1.0)
            move = (strafe * 0.8 + sep + dir_to * 0.1).normalized()
            enemy.vel = move * (enemy.speed * 0.85)
            enemy.pos = enemy.pos + enemy.vel * dt

        enemy.attack_cd -= dt
        if enemy.attack_cd <= 0.0 and d < 420:
            if not hasattr(state, "traps"):
                state.traps = []
            predicted = Vec2(player_pos.x + player_vel.x * 0.65, player_pos.y + player_vel.y * 0.65)
            jitter = Vec2(random.uniform(-24, 24), random.uniform(-24, 24))
            p = Vec2(predicted.x + jitter.x, predicted.y + jitter.y)
            # Keep within room bounds.
            if p.length() > config.ROOM_RADIUS * 0.86:
                p = p.normalized() * (config.ROOM_RADIUS * 0.86)
            _append_trap_capped(state, Trap(pos=p, radius=28.0, damage=16, ttl=10.0))
            enemy.attack_cd = 2.9 + random.uniform(0.0, 0.6)

    def _separation(self, enemy, others, radius: float = 44.0, weight: float = 1.1) -> Vec2:
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
