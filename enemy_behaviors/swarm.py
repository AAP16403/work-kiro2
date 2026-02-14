"""Swarm behavior for enemies, using Boids-like principles."""
from enemy_behaviors.base import Behavior
from utils import Vec2
import math
import random

class Swarm(Behavior):
    """
    A Boids-like swarm behavior. Swarm members will try to stick together
    while moving towards the player in a cohesive group.
    """

    def __init__(self, perception_radius=80.0, separation_weight=2.0, align_weight=0.5, cohesion_weight=0.3):
        self.perception_radius = perception_radius
        self.separation_weight = separation_weight
        self.align_weight = align_weight
        self.cohesion_weight = cohesion_weight

    def update(self, enemy, player_pos, state, dt, player_vel):
        """Update the enemy's state based on its behavior."""
        
        # For performance, we might not need to check all enemies, especially in later waves.
        # A full Boids implementation would use a spatial hash grid. Here we simplify.
        neighbors = self._get_neighbors(enemy, state.enemies)

        # --- Boids Rules ---
        # 1. Separation: Steer to avoid crowding local flockmates.
        sep = self._separation(enemy, neighbors)
        
        # 2. Alignment: Steer towards the average heading of local flockmates.
        align = self._alignment(enemy, neighbors)
        
        # 3. Cohesion: Steer to move toward the average position of local flockmates.
        coh = self._cohesion(enemy, neighbors)

        # --- Goal Seeking ---
        # The primary goal is to move towards the player.
        dvec = player_pos - enemy.pos
        dist_to_player = dvec.length()
        to_player = dvec.normalized() if dist_to_player > 1e-6 else Vec2(1.0, 0.0)

        # Add some slight random jitter to prevent perfect stacking and make movement organic
        # The seed ensures each enemy has a different (but consistent) jitter pattern.
        jitter = Vec2(math.sin(enemy.t * 5.5 + enemy.seed), math.cos(enemy.t * 4.9 + enemy.seed)) * 0.25

        # --- Combine Forces ---
        # The final movement is a weighted sum of all forces.
        # The swarm rules keep the group together, while the 'to_player' vector
        # gives them a unified direction.
        move_dir = (to_player * 1.0 + 
                    sep * self.separation_weight + 
                    align * self.align_weight + 
                    coh * self.cohesion_weight +
                    jitter
                   ).normalized()
        
        enemy.vel = move_dir * enemy.speed
        enemy.pos += enemy.vel * dt

    def _get_neighbors(self, enemy, all_enemies):
        """Get all swarm-type enemies within the perception radius."""
        neighbors = []
        for other in all_enemies:
            # Only consider other swarm enemies, not the enemy itself
            if other is enemy:
                continue
            behavior = getattr(other, "behavior", "")
            is_swarm = behavior == "swarm" or behavior.__class__.__name__.lower() == "swarm"
            if is_swarm:
                dist_sq = (other.pos - enemy.pos).length_squared()
                if dist_sq < self.perception_radius * self.perception_radius:
                    neighbors.append(other)
        return neighbors

    def _separation(self, enemy, neighbors) -> Vec2:
        """Rule 1: Steer to avoid crowding local flockmates."""
        steer = Vec2(0.0, 0.0)
        count = 0
        for other in neighbors:
            dvec = enemy.pos - other.pos
            d = dvec.length()
            if d > 0:
                # Force is inversely proportional to distance
                steer += dvec.normalized() / d
                count += 1
        if count > 0:
            steer /= count
        return steer

    def _alignment(self, enemy, neighbors) -> Vec2:
        """Rule 2: Steer towards the average heading of local flockmates."""
        avg_vel = Vec2(0.0, 0.0)
        count = 0
        for other in neighbors:
            if other.vel.length_squared() > 1e-6:
                avg_vel += other.vel.normalized()
                count += 1
        
        if count > 0:
            avg_vel /= count
            # Steering is the difference between desired velocity and current velocity
            return (avg_vel - enemy.vel.normalized()).normalized() if avg_vel.length_squared() > 1e-6 else Vec2(0,0)
        return Vec2(0,0)

    def _cohesion(self, enemy, neighbors) -> Vec2:
        """Rule 3: Steer to move toward the average position of local flockmates."""
        center_of_mass = Vec2(0.0, 0.0)
        count = 0
        for other in neighbors:
            center_of_mass += other.pos
            count += 1

        if count > 0:
            center_of_mass /= count
            # Return a vector pointing from the enemy's position to the center of mass
            return (center_of_mass - enemy.pos).normalized()
        return Vec2(0,0)
