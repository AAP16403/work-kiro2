"""Flyer behavior for enemies."""
from enemy_behaviors.base import Behavior
from utils import Vec2
import math
import random

def _perp(v: Vec2) -> Vec2:
    return Vec2(-v.y, v.x)

class Flyer(Behavior):
    """
    A flyer behavior that circles the player and performs dashing attacks.
    It uses a simple state machine to switch between CIRCLING and DASHING.
    """

    def __init__(self, circling_duration=2.5, dash_speed_mult=4.0, circling_dist=150.0):
        """
        Initialize the Flyer behavior.
        
        Args:
            circling_duration (float): Time in seconds to circle before a dash.
            dash_speed_mult (float): Multiplier for speed during a dash.
            circling_dist (float): Preferred distance to keep from the player while circling.
        """
        self.circling_duration = circling_duration
        self.dash_speed_mult = dash_speed_mult
        self.circling_dist = circling_dist

    def update(self, enemy, player_pos, state, dt, player_vel):
        """Update the enemy's state based on its behavior."""
        
        # -- Initialize AI state if it's not there --
        if "state" not in enemy.ai or "state_timer" not in enemy.ai:
            enemy.ai["state"] = "CIRCLING"
            enemy.ai["state_timer"] = self.circling_duration + random.uniform(-0.5, 0.5)

        # -- Common calculations --
        dvec = player_pos - enemy.pos
        d = dvec.length()
        dir_to_player = dvec.normalized() if d > 1e-6 else Vec2(1.0, 0.0)
        
        # -- State Machine --
        current_state = enemy.ai.get("state")

        if current_state == "CIRCLING":
            # --- Circling Behavior ---
            # Timer to decide when to dash
            enemy.ai["state_timer"] -= dt
            if enemy.ai["state_timer"] <= 0:
                enemy.ai["state"] = "DASHING"
                enemy.ai["dash_target"] = player_pos  # Lock on to the player's position at the start of the dash
                return

            # Separation from other enemies
            sep = self._separation(enemy, state.enemies, radius=50.0, weight=1.2)

            # Movement logic: try to maintain distance and circle
            dir_to_circle_pos = Vec2(0, 0)
            if d > self.circling_dist + 20:
                dir_to_circle_pos = dir_to_player # Move towards player
            elif d < self.circling_dist - 20:
                dir_to_circle_pos = -dir_to_player # Move away from player

            # Circling motion (strafe)
            strafe_dir = _perp(dir_to_player)
            
            # Combine movement vectors
            move_dir = (dir_to_circle_pos * 0.6 + strafe_dir * 0.4 + sep * 0.5).normalized()
            enemy.vel = move_dir * enemy.speed
            enemy.pos += enemy.vel * dt

        elif current_state == "DASHING":
            # --- Dashing Behavior ---
            # Move fast towards the locked-on dash target
            dash_dvec = enemy.ai["dash_target"] - enemy.pos
            dist_to_target = dash_dvec.length()

            # End dash if we've reached the target or overshot it
            if dist_to_target < 20.0:
                enemy.ai["state"] = "CIRCLING"
                enemy.ai["state_timer"] = self.circling_duration + random.uniform(-0.5, 0.5)
                return

            dash_dir = dash_dvec.normalized()
            enemy.vel = dash_dir * enemy.speed * self.dash_speed_mult
            enemy.pos += enemy.vel * dt

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
            # Weight force by inverse square of distance
            acc += dvec.normalized() * (1.0 - (d / r))
            count += 1
            
        if count == 0:
            return Vec2(0.0, 0.0)
            
        return (acc / count).normalized() * weight
