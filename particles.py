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
    particle_type: str  # "spark", "smoke", "debris", "shockwave", "flash"
    drag: float = 0.0


class ParticleSystem:
    """Manages all particles in the game."""
    
    def __init__(self, batch):
        self.batch = batch
        self.particles: List[Particle] = []
    
    def add_muzzle_flash(self, pos: Vec2, direction: Vec2, color: Tuple[int, int, int] = (255, 200, 100)):
        """Create enhanced muzzle flash particles."""
        # 1. Bright core flash
        self.particles.append(Particle(
            pos=pos, vel=direction * 20, ttl=0.06, max_ttl=0.06,
            size=14, color=(255, 255, 255), particle_type="flash", drag=0
        ))
        
        # 2. Directional sparks (cone)
        base_angle = math.atan2(direction.y, direction.x)
        for _ in range(8):
            angle = base_angle + random.uniform(-0.4, 0.4)
            speed = random.uniform(150, 450)
            vel = Vec2(math.cos(angle) * speed, math.sin(angle) * speed)
            
            self.particles.append(Particle(
                pos=pos, vel=vel, ttl=random.uniform(0.1, 0.25), max_ttl=0.25,
                size=random.uniform(2, 4), color=color, particle_type="spark", drag=3.0
            ))
            
        # 3. Smoke puffs (drifting)
        for _ in range(4):
            angle = base_angle + random.uniform(-0.6, 0.6)
            speed = random.uniform(30, 100)
            vel = Vec2(math.cos(angle) * speed, math.sin(angle) * speed)
            
            self.particles.append(Particle(
                pos=pos, vel=vel, ttl=random.uniform(0.3, 0.6), max_ttl=0.6,
                size=random.uniform(4, 8), color=(200, 200, 200), particle_type="smoke", drag=1.0
            ))
    
    def add_hit_particles(self, pos: Vec2, color: Tuple[int, int, int] = (255, 100, 100)):
        """Create hit/impact particles."""
        # Flash
        self.particles.append(Particle(
            pos=pos, vel=Vec2(0,0), ttl=0.08, max_ttl=0.08,
            size=10, color=(255, 255, 255), particle_type="flash"
        ))
        
        # Sparks
        for _ in range(6):
            angle = random.uniform(0, math.tau)
            speed = random.uniform(80, 200)
            vel = Vec2(math.cos(angle) * speed, math.sin(angle) * speed)
            
            self.particles.append(Particle(
                pos=pos, vel=vel, ttl=0.2, max_ttl=0.2,
                size=random.uniform(1.5, 3.5), color=color, particle_type="spark", drag=2.0
            ))
    
    def add_death_explosion(self, pos: Vec2, color: Tuple[int, int, int], enemy_type: str = "chaser"):
        """Create explosion particles when enemy dies."""
        # Scale based on enemy type
        scale = 1.0
        count_mult = 1.0
        
        if enemy_type == "tank":
            scale = 1.8
            count_mult = 2.0
            # Tank explosions are fiery and dangerous looking
            self.particles.append(Particle(
                pos=pos, vel=Vec2(0,0), ttl=0.5, max_ttl=0.5,
                size=60, color=(255, 100, 50), particle_type="shockwave", drag=0
            ))
        elif enemy_type == "swarm":
            scale = 0.6
            count_mult = 0.5
        elif enemy_type == "boss":
            scale = 2.5
            count_mult = 3.0

        # 1. Shockwave
        self.particles.append(Particle(
            pos=pos, vel=Vec2(0,0), ttl=0.3, max_ttl=0.3,
            size=15 * scale, color=color, particle_type="shockwave", drag=0
        ))
        
        # 2. Core Flash
        self.particles.append(Particle(
            pos=pos, vel=Vec2(0,0), ttl=0.15, max_ttl=0.15,
            size=30 * scale, color=(255, 255, 255), particle_type="flash", drag=0
        ))
        
        # 3. Debris and Sparks
        count = int(16 * count_mult)
        for _ in range(count):
            angle = random.uniform(0, math.tau)
            speed = random.uniform(100, 350)
            vel = Vec2(math.cos(angle) * speed, math.sin(angle) * speed)
            
            # Mix of sparks (fast, short) and debris (slow, long)
            is_debris = random.random() < 0.4
            
            if is_debris:
                p_type = "debris"
                ttl = random.uniform(0.5, 0.9)
                size = random.uniform(3, 6) * scale
                drag = 1.5
            else:
                p_type = "spark"
                ttl = random.uniform(0.2, 0.5)
                size = random.uniform(2, 4) * scale
                drag = 2.5
                
            self.particles.append(Particle(
                pos=pos, vel=vel, ttl=ttl, max_ttl=ttl,
                size=size, color=color, particle_type=p_type, drag=drag
            ))
            
        # 4. Smoke for larger enemies
        if scale >= 1.0:
            for _ in range(int(5 * scale)):
                angle = random.uniform(0, math.tau)
                speed = random.uniform(20, 60)
                vel = Vec2(math.cos(angle) * speed, math.sin(angle) * speed)
                self.particles.append(Particle(
                    pos=pos, vel=vel, ttl=0.8, max_ttl=0.8,
                    size=random.uniform(8, 15) * scale, color=(100, 100, 100), particle_type="smoke", drag=0.5
                ))
    
    def add_powerup_collection(self, pos: Vec2, color: Tuple[int, int, int]):
        """Create particles when powerup is collected."""
        # Upward spiral or burst
        for _ in range(15):
            angle = random.uniform(0, math.tau)
            speed = random.uniform(150, 300)
            vel = Vec2(math.cos(angle) * speed, math.sin(angle) * speed)
            
            self.particles.append(Particle(
                pos=pos, vel=vel, ttl=0.4, max_ttl=0.4,
                size=random.uniform(2, 5), color=color, particle_type="spark", drag=1.0
            ))
            
        # Ring
        self.particles.append(Particle(
            pos=pos, vel=Vec2(0,0), ttl=0.3, max_ttl=0.3,
            size=5, color=color, particle_type="shockwave", drag=0
        ))
    
    def update(self, dt: float):
        """Update all particles."""
        for particle in list(self.particles):
            particle.ttl -= dt
            
            # Apply drag
            if particle.drag > 0:
                particle.vel = particle.vel * (1.0 - particle.drag * dt)
            
            # Apply gravity (downward) based on type
            if particle.particle_type == "debris":
                particle.vel.y -= 400 * dt
            elif particle.particle_type == "smoke":
                particle.vel.y += 50 * dt  # Smoke rises
            elif particle.particle_type == "spark":
                particle.vel.y -= 150 * dt
            
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
            
            if particle.particle_type == "shockwave":
                # Expanding ring effect
                radius = particle.size + (1.0 - alpha_ratio) * 80  # Expand
                alpha = int(200 * alpha_ratio)
                
                # Using Arc for ring if available, else Circle
                try:
                    arc = shapes.Arc(
                        sx, sy, radius, segments=32, thickness=3,
                        color=particle.color, batch=temp_batch
                    )
                    arc.opacity = alpha
                except AttributeError:
                    # Fallback for older pyglet
                    circle = shapes.Circle(
                        sx, sy, radius, color=particle.color, batch=temp_batch
                    )
                    circle.opacity = int(100 * alpha_ratio)
                    
            elif particle.particle_type == "flash":
                # Static bright flash
                alpha = int(255 * alpha_ratio)
                circle = shapes.Circle(
                    sx, sy, particle.size, color=particle.color, batch=temp_batch
                )
                circle.opacity = alpha
                
            elif particle.particle_type == "smoke":
                # Fading, growing smoke
                alpha = int(100 * alpha_ratio)
                size = particle.size * (1.0 + (1.0 - alpha_ratio)) # Grow
                circle = shapes.Circle(
                    sx, sy, size, color=particle.color, batch=temp_batch
                )
                circle.opacity = alpha
                
            else: # spark, debris
                alpha = int(255 * alpha_ratio)
                size = max(1.0, particle.size * alpha_ratio)
                
                if particle.particle_type == "debris":
                    # Square-ish for debris?
                    rect = shapes.Rectangle(
                        sx - size, sy - size, size*2, size*2,
                        color=particle.color, batch=temp_batch
                    )
                    rect.opacity = alpha
                    rect.rotation = particle.ttl * 360  # Spin
                else:
                    circle = shapes.Circle(
                        sx, sy, size, color=particle.color, batch=temp_batch
                    )
                    circle.opacity = alpha
        
        # Draw temporary batch
        temp_batch.draw()
