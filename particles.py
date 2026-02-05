"""Particle system for visual effects and animations."""

from dataclasses import dataclass
from typing import List, Tuple
import random
import math
import pyglet
from pyglet import shapes
from utils import Vec2, to_iso


@dataclass
class Particle:
    """Individual particle with physics."""
    pos: Vec2
    vel: Vec2
    ttl: float
    max_ttl: float
    size: float
    color: Tuple[int, int, int]
    particle_type: str  # "spark", "smoke"


class ParticleSystem:
    """Manages all particles in the game."""
    
    def __init__(self, batch):
        self.batch = batch
        self.particles: List[Particle] = []
    
    def add_muzzle_flash(self, pos: Vec2, direction: Vec2):
        """Create muzzle flash particles when firing."""
        for _ in range(6):
            angle = random.uniform(-0.3, 0.3) + math.atan2(direction.y, direction.x)
            speed = random.uniform(100, 300)
            vel = Vec2(math.cos(angle) * speed, math.sin(angle) * speed)
            
            particle = Particle(
                pos=pos,
                vel=vel,
                ttl=0.1,
                max_ttl=0.1,
                size=random.uniform(2, 4),
                color=(255, 200, 100),  # Orange/yellow
                particle_type="spark"
            )
            self.particles.append(particle)
    
    def add_hit_particles(self, pos: Vec2, color: Tuple[int, int, int] = (255, 100, 100)):
        """Create hit/impact particles."""
        for _ in range(5):
            angle = random.uniform(0, math.tau)
            speed = random.uniform(80, 200)
            vel = Vec2(math.cos(angle) * speed, math.sin(angle) * speed)
            
            particle = Particle(
                pos=pos,
                vel=vel,
                ttl=0.15,
                max_ttl=0.15,
                size=random.uniform(1, 3),
                color=color,
                particle_type="spark"
            )
            self.particles.append(particle)
    
    def add_death_explosion(self, pos: Vec2, color: Tuple[int, int, int]):
        """Create explosion particles when enemy dies."""
        # Sparks
        for _ in range(10):
            angle = random.uniform(0, math.tau)
            speed = random.uniform(100, 250)
            vel = Vec2(math.cos(angle) * speed, math.sin(angle) * speed)
            
            particle = Particle(
                pos=pos,
                vel=vel,
                ttl=0.3,
                max_ttl=0.3,
                size=random.uniform(2, 5),
                color=color,
                particle_type="spark"
            )
            self.particles.append(particle)
    
    def add_powerup_collection(self, pos: Vec2, color: Tuple[int, int, int]):
        """Create particles when powerup is collected."""
        for _ in range(12):
            angle = random.uniform(0, math.tau)
            speed = random.uniform(120, 280)
            vel = Vec2(math.cos(angle) * speed, math.sin(angle) * speed)
            
            particle = Particle(
                pos=pos,
                vel=vel,
                ttl=0.25,
                max_ttl=0.25,
                size=random.uniform(2, 4),
                color=color,
                particle_type="spark"
            )
            self.particles.append(particle)
    
    def update(self, dt: float):
        """Update all particles."""
        for particle in list(self.particles):
            particle.ttl -= dt
            
            # Apply gravity (downward)
            particle.vel.y -= 80 * dt  # Gravity
            
            # Update position
            particle.pos = particle.pos + particle.vel * dt
            
            # Remove dead particles
            if particle.ttl <= 0:
                self.particles.remove(particle)
    
    def render(self, shake: Vec2):
        """Render all particles directly without adding to batch."""
        if not self.particles:
            return
        
        # Create temporary batch for this frame's particles only
        temp_batch = pyglet.graphics.Batch()
        
        for particle in self.particles:
            # Calculate visibility based on TTL
            alpha_ratio = particle.ttl / particle.max_ttl
            alpha = int(255 * alpha_ratio)
            
            # Scale for fade-out effect
            size = max(0.5, particle.size * alpha_ratio)
            
            sx, sy = to_iso(particle.pos, shake)
            
            if particle.particle_type == "spark":
                # Render circle to temporary batch
                circle = shapes.Circle(
                    sx, sy, size,
                    color=particle.color,
                    batch=temp_batch
                )
                circle.opacity = alpha
        
        # Draw temporary batch
        temp_batch.draw()

