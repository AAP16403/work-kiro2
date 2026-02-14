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
        if "slot_bias" not in enemy.ai:
            enemy.ai["slot_bias"] = ((id(enemy) % 17) / 17.0) * math.tau
        
        neighbors = self._get_neighbors(enemy, state.enemies)

        sep = self._separation(enemy, neighbors)
        align = self._alignment(enemy, neighbors)
        coh = self._cohesion(enemy, neighbors)

        dvec = player_pos - enemy.pos
        dist_to_player = dvec.length()
        to_player = dvec.normalized() if dist_to_player > 1e-6 else Vec2(1.0, 0.0)

        slot_ang = enemy.t * 0.55 + enemy.ai["slot_bias"]
        pressure = max(0.0, min(1.0, (220.0 - dist_to_player) / 220.0))
        ring_base = 135.0 + 25.0 * math.sin(enemy.t * 0.9 + enemy.seed)
        ring_r = max(46.0, ring_base * (1.0 - pressure * 0.55))
        ring_target = player_pos + Vec2(math.cos(slot_ang), math.sin(slot_ang)) * ring_r
        to_ring = (ring_target - enemy.pos).normalized()

        dodge = self._dodge_player_projectiles(enemy, getattr(state, "projectiles", []))
        jitter = Vec2(math.sin(enemy.t * 5.5 + enemy.seed), math.cos(enemy.t * 4.9 + enemy.seed)) * 0.25

        ring_weight = max(0.08, 0.42 - pressure * 0.28)
        chase_weight = 0.92 + pressure * 0.42
        move_dir = (
            to_player * chase_weight
            + to_ring * ring_weight
            + sep * self.separation_weight
            + align * self.align_weight
            + coh * self.cohesion_weight
            + dodge * 0.95
            + jitter
        ).normalized()
        
        enemy.vel = move_dir * enemy.speed * (1.0 + pressure * 0.15)
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
            return (center_of_mass - enemy.pos).normalized()
        return Vec2(0,0)

    def _dodge_player_projectiles(self, enemy, projectiles, danger_radius: float = 85.0) -> Vec2:
        steer = Vec2(0.0, 0.0)
        count = 0
        for p in projectiles:
            if getattr(p, "owner", "") != "player":
                continue
            rel = enemy.pos - p.pos
            d2 = rel.length_squared()
            if d2 > danger_radius * danger_radius:
                continue
            v = getattr(p, "vel", Vec2(0.0, 0.0))
            if v.length_squared() <= 1e-6:
                continue
            toward = rel.dot(v.normalized())
            if toward >= 0.0:
                continue
            ev = Vec2(-v.y, v.x).normalized()
            sign = 1.0 if rel.dot(ev) >= 0.0 else -1.0
            steer += ev * sign * (1.0 - (math.sqrt(d2) / danger_radius))
            count += 1
            if count >= 3:
                break
        if count == 0:
            return Vec2(0.0, 0.0)
        return (steer / count).normalized()
