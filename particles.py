"""Particle system for visual effects."""

from dataclasses import dataclass
import random
import math

import pyglet
from pyglet import shapes

from utils import to_iso, Vec2

@dataclass
class Particle:
    pos: Vec2
    vel: Vec2
    life: float
    max_life: float
    color: tuple[int, int, int]
    size: float
    decay: bool = True

class ParticleSystem:
    """Manages transient visual particles."""

    def __init__(self, batch=None):
        self.batch = batch or pyglet.graphics.Batch()
        self.particles: list[Particle] = []
        self._shapes: list[shapes.Circle] = []
        
    def emit(
        self,
        pos: Vec2,
        color: tuple[int, int, int],
        count: int = 5,
        speed: float = 100.0,
        life: float = 0.6,
        size: float = 3.0,
        spread: float = 6.28,
        direction: Vec2 = None,
        spread_angle: float = None,
        decay: bool = True,
    ):
        base_angle = 0.0
        if direction:
            base_angle = math.atan2(direction.y, direction.x)
        
        limit_angle = spread_angle if spread_angle is not None else spread

        for _ in range(count):
            angle = base_angle + random.uniform(-limit_angle * 0.5, limit_angle * 0.5) if direction else random.uniform(0, limit_angle)
            sp = random.uniform(speed * 0.5, speed * 1.5)
            vel = Vec2(math.cos(angle) * sp, math.sin(angle) * sp)
            p = Particle(
                pos=Vec2(pos.x, pos.y),
                vel=vel,
                life=random.uniform(life * 0.7, life * 1.3),
                max_life=life,
                color=color,
                size=random.uniform(size * 0.7, size * 1.3),
                decay=decay,
            )
            self.particles.append(p)

    def add_death_explosion(self, pos: Vec2, color: tuple[int, int, int], behavior_name: str = ""):
        count = 12
        if behavior_name.startswith("boss"):
            count = 40
        elif behavior_name == "tank":
            count = 20
        self.emit(pos, color, count=count, speed=150.0, life=0.8, size=4.0)

    def add_hit_particles(self, pos: Vec2, color: tuple[int, int, int]):
        self.emit(pos, color, count=4, speed=80.0, life=0.4, size=2.5)

    def add_muzzle_flash(self, pos: Vec2, direction: Vec2):
        self.emit(pos, (255, 255, 200), count=6, speed=120.0, life=0.15, size=2.0, direction=direction, spread_angle=0.5)

    def add_step_dust(self, pos: Vec2, move_dir: Vec2):
        # Dust kicks up opposite to movement
        self.emit(pos, (200, 200, 200), count=2, speed=30.0, life=0.3, size=2.0, direction=-move_dir, spread_angle=1.0)

    def add_powerup_collection(self, pos: Vec2, color: tuple[int, int, int]):
         self.emit(pos, color, count=16, speed=120.0, life=0.8, size=3.5)

    def add_laser_beam(self, start: Vec2, end: Vec2, color: tuple[int, int, int]):
        # Emit particles along the line
        d = dist(start, end)
        steps = max(3, int(d / 15.0))
        delta = (end - start) / float(steps)
        curr = start
        for _ in range(steps):
            self.emit(curr, color, count=2, speed=40.0, life=0.3, size=2.0)
            curr += delta

    def add_vortex_swirl(self, center: Vec2, time: float, radius: float):
        # Spiral particles
        angle = time * 4.0
        offset = Vec2(math.cos(angle) * radius, math.sin(angle) * radius)
        p = Particle(
            pos=center + offset,
            vel=-offset.normalized() * 50.0, # Suck in
            life=0.4,
            max_life=0.4,
            color=(180, 140, 255),
            size=3.0,
            decay=False
        )
        self.particles.append(p)
    
    def dist(self, a, b):
         return math.sqrt((a.x-b.x)**2 + (a.y-b.y)**2)

    def update(self, dt: float):
        keep = []
        for p in self.particles:
            p.life -= dt
            if p.life > 0:
                p.pos = p.pos + p.vel * dt
                if p.decay:
                    p.vel = p.vel * (1.0 - 2.0 * dt)
                keep.append(p)
        self.particles = keep

    def render(self, shake: Vec2):
        # Rebuild shapes pool if needed
        needed = len(self.particles)
        if len(self._shapes) < needed:
            diff = needed - len(self._shapes)
            for _ in range(diff):
                self._shapes.append(shapes.Circle(0, 0, 1, color=(255, 255, 255), batch=self.batch))
        
        # Hide unused
        for i in range(needed, len(self._shapes)):
            self._shapes[i].opacity = 0

        # Update active
        for i, p in enumerate(self.particles):
            sh = self._shapes[i]
            sx, sy = to_iso(p.pos, shake)
            sh.x, sh.y = sx, sy
            sh.radius = p.size * (p.life / p.max_life)
            sh.color = p.color
            sh.opacity = int(255 * (p.life / p.max_life))

def dist(a: Vec2, b: Vec2) -> float:
    return (a - b).length()
