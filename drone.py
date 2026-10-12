"""Drone companion power-up.

A rare pickup deploys one drone that orbits the player and fires at the nearest live enemy.
Its shots are ordinary player bullets built by projectile.spawn_projectiles, so they share the
player's damage, crit roll and hit loop in PlayingState.update, boss damage included.

The deploy timer lives on the player (player.drone_until), like the laser and vortex timers.
The orbit, aim and visual state lives on GameState.drone (a DroneCompanion).
"""

import math

from projectile import Projectile, spawn_projectiles
from utils import Vec2, dist_sq
from weapons import WEAPONS

DRONE_DURATION = 12.0       # seconds one pickup keeps the drone out; re-picking refreshes the timer, never stacks
DRONE_ORBIT_RADIUS = 40.0   # world units between the player and the drone
DRONE_ORBIT_SPEED = 2.4     # radians per second
DRONE_FIRE_INTERVAL = 0.6   # seconds between volleys
DRONE_RANGE = 300.0         # world units; enemies further away from the drone are not targeted
DRONE_TURN_RATE = 10.0      # how fast the hull turns toward its target (per second, exponential)
DRONE_MUZZLE_OFFSET = 12.0  # world units from the drone centre to the muzzle
DRONE_FLASH_TIME = 0.08     # seconds the muzzle flash stays lit after a volley
DRONE_DROP_SHARE = 0.03     # share of powerup drops from wave 3 on (rare tier)

# The drone fires the basic gun's bullet: one small shot, using the player's damage and crit stats.
DRONE_WEAPON = WEAPONS["basic"]


def nearest_live_enemy(origin: Vec2, enemies, max_range: float):
    """Closest enemy that is alive and within max_range of origin, or None. Ties keep list order."""
    limit2 = float(max_range) * float(max_range)
    best = None
    best_d2 = limit2
    for e in enemies:
        if e.hp <= 0 or getattr(e, "_is_dead", False):
            continue
        d2 = dist_sq(e.pos, origin)
        if d2 <= limit2 and (best is None or d2 < best_d2):
            best = e
            best_d2 = d2
    return best


def drone_bullets(muzzle: Vec2, aim: Vec2, now: float, base_damage: int, rng,
                  crit_chance_bonus: float = 0.0, crit_mult_bonus: float = 0.0) -> list[Projectile]:
    """Player bullets for one drone volley.

    This is the same spawn_projectiles that builds the player's shots, so the damage, the crit
    roll and the owner tag are identical. There is no second damage formula here.
    """
    return spawn_projectiles(
        muzzle, aim, DRONE_WEAPON, now, base_damage,
        rng=rng, crit_chance_bonus=crit_chance_bonus, crit_mult_bonus=crit_mult_bonus,
    )


class DroneCompanion:
    """Orbit, aim and visual state for the one deployed drone."""

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        """Clear all runtime state. Runs when the timer expires so no stale target or flash survives."""
        self.active = False
        self.angle = 0.0
        self.pos = Vec2(0.0, 0.0)
        self.heading = Vec2(1.0, 0.0)  # unit vector the hull faces (eases toward its target)
        self.target = None
        self.fire_cd = 0.0
        self.flash = 0.0

    def update(self, dt: float, now: float, until: float, owner_pos: Vec2, enemies):
        """Advance one simulation step.

        Returns (muzzle, aim) on the frame the drone fires, otherwise None. ``until`` is the
        player's drone_until timestamp; once ``now`` reaches it the drone is reset and stays idle.
        """
        if now >= until:
            self.reset()
            return None
        if not self.active:
            self.active = True
            self.fire_cd = 0.0  # a fresh deploy fires as soon as it has a target

        dt = max(0.0, float(dt))
        self.angle += DRONE_ORBIT_SPEED * dt
        self.pos = Vec2(
            owner_pos.x + math.cos(self.angle) * DRONE_ORBIT_RADIUS,
            owner_pos.y + math.sin(self.angle) * DRONE_ORBIT_RADIUS,
        )

        self.target = nearest_live_enemy(self.pos, enemies, DRONE_RANGE)
        if self.target is not None:
            want = (self.target.pos - self.pos).normalized()
            k = min(1.0, DRONE_TURN_RATE * dt)
            turned = self.heading + (want - self.heading) * k
            if turned.length() > 1e-9:
                self.heading = turned.normalized()

        self.flash = max(0.0, self.flash - dt)
        self.fire_cd = max(0.0, self.fire_cd - dt)
        if self.target is None or self.fire_cd > 0.0:
            return None

        aim = (self.target.pos - self.pos).normalized()
        if aim.length_squared() <= 1e-12:
            aim = Vec2(self.heading.x, self.heading.y)
        self.fire_cd = DRONE_FIRE_INTERVAL
        self.flash = DRONE_FLASH_TIME
        muzzle = self.pos + aim * DRONE_MUZZLE_OFFSET
        return muzzle, aim
