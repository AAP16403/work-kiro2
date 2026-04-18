"""Particle system for visual effects (Browser Canvas version)."""

from dataclasses import dataclass
import random
import math

import config
from utils import Vec2

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
    """Manages transient visual particles for canvas rendering."""

    def __init__(self):
        self.particles: list[Particle] = []
        
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
        if count <= 0:
            return
        soft_cap = int(getattr(config, "PARTICLE_SOFT_CAP", 200))
        hard_cap = int(getattr(config, "PARTICLE_HARD_CAP", 300))
        current = len(self.particles)
        if current >= hard_cap:
            return
        if current > soft_cap:
            headroom = max(1, hard_cap - soft_cap)
            overload = min(headroom, current - soft_cap)
            scale = max(0.15, 1.0 - (overload / float(headroom)))
            count = int(count * scale)
            if count <= 0:
                return
        if current + count > hard_cap:
            count = max(0, hard_cap - current)
            if count <= 0:
                return
        base_angle = 0.0
        if direction:
            base_angle = math.atan2(direction.y, direction.x)
        
        limit_angle = spread_angle if spread_angle is not None else spread

        for _ in range(count):
            angle = base_angle + random.uniform(-limit_angle * 0.5, limit_angle * 0.5) if direction else random.uniform(0, limit_angle)
            sp = random.uniform(speed * 0.5, speed * 1.5)
            vel = Vec2(math.cos(angle) * sp, math.sin(angle) * sp)
            life_val = random.uniform(life * 0.7, life * 1.3)
            p = Particle(
                pos=Vec2(pos.x, pos.y),
                vel=vel,
                life=life_val,
                max_life=life_val,
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
        self.emit(pos, (200, 200, 200), count=2, speed=30.0, life=0.3, size=2.0, direction=-move_dir, spread_angle=1.0)

    def add_powerup_collection(self, pos: Vec2, color: tuple[int, int, int]):
        self.emit(pos, color, count=16, speed=120.0, life=0.8, size=3.5)

    def add_shield_hit(self, pos: Vec2, amount: int):
        strength = max(4, min(18, int(amount) // 4))
        self.emit(pos, (120, 210, 255), count=strength, speed=90.0, life=0.35, size=2.6)

    def add_dash_effect(self, pos: Vec2, dash_dir: Vec2):
        back = -dash_dir
        self.emit(pos, (160, 220, 255), count=8, speed=140.0, life=0.25, size=2.4, direction=back, spread_angle=0.4)

    def add_laser_beam(self, start: Vec2, end: Vec2, color: tuple[int, int, int]):
        d = (start - end).length()
        steps = max(3, int(d / 15.0))
        delta = (end - start) / float(steps)
        curr = start
        for _ in range(steps):
            self.emit(curr, color, count=2, speed=40.0, life=0.3, size=2.0)
            curr += delta

    def add_vortex_swirl(self, center: Vec2, time: float, radius: float):
        angle = time * 4.0
        offset = Vec2(math.cos(angle) * radius, math.sin(angle) * radius)
        p = Particle(
            pos=center + offset,
            vel=-offset.normalized() * 50.0,
            life=0.4,
            max_life=0.4,
            color=(180, 140, 255),
            size=3.0,
            decay=False
        )
        self.particles.append(p)
    
    def update(self, dt: float):
        if not self.particles:
            return
        keep = []
        for p in self.particles:
            p.life -= dt
            if p.life > 0:
                p.pos = p.pos + p.vel * dt
                if p.decay:
                    p.vel = p.vel * max(0.0, 1.0 - 2.0 * dt)
                keep.append(p)
        self.particles = keep

    def render(self, ctx, shake, to_iso):
        if not self.particles:
            return

        TAU = math.tau
        # Group particles by color key for batching
        buckets: dict[tuple, list] = {}
        for p in self.particles:
            ratio = max(0.0, p.life / p.max_life)
"""Particle system for visual effects (Browser Canvas version)."""

from dataclasses import dataclass
import random
import math

import config
from utils import Vec2

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
    """Manages transient visual particles for canvas rendering."""

    def __init__(self):
        self.particles: list[Particle] = []
        
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
        if count <= 0:
            return
        soft_cap = int(getattr(config, "PARTICLE_SOFT_CAP", 200))
        hard_cap = int(getattr(config, "PARTICLE_HARD_CAP", 300))
        current = len(self.particles)
        if current >= hard_cap:
            return
        if current > soft_cap:
            headroom = max(1, hard_cap - soft_cap)
            overload = min(headroom, current - soft_cap)
            scale = max(0.15, 1.0 - (overload / float(headroom)))
            count = int(count * scale)
            if count <= 0:
                return
        if current + count > hard_cap:
            count = max(0, hard_cap - current)
            if count <= 0:
                return
        base_angle = 0.0
        if direction:
            base_angle = math.atan2(direction.y, direction.x)
        
        limit_angle = spread_angle if spread_angle is not None else spread

        for _ in range(count):
            angle = base_angle + random.uniform(-limit_angle * 0.5, limit_angle * 0.5) if direction else random.uniform(0, limit_angle)
            sp = random.uniform(speed * 0.5, speed * 1.5)
            vel = Vec2(math.cos(angle) * sp, math.sin(angle) * sp)
            life_val = random.uniform(life * 0.7, life * 1.3)
            p = Particle(
                pos=Vec2(pos.x, pos.y),
                vel=vel,
                life=life_val,
                max_life=life_val,
                color=color,
                size=random.uniform(size * 0.7, size * 1.3),
                decay=decay,
            )
            self.particles.append(p)

    def add_death_explosion(self, pos: Vec2, color: tuple[int, int, int], behavior_name: str = ""):
        count = 60
        if behavior_name.startswith("boss"):
            count = 150
        elif behavior_name == "tank":
            count = 90
            
        self.emit(pos, color, count=int(count * 0.7), speed=250.0, life=0.6, size=2.5)
        self.emit(pos, (255, 255, 255), count=int(count * 0.3), speed=350.0, life=0.3, size=1.5)

    def add_hit_particles(self, pos: Vec2, color: tuple[int, int, int]):
        self.emit(pos, color, count=4, speed=80.0, life=0.4, size=2.5)

    def add_muzzle_flash(self, pos: Vec2, direction: Vec2):
        self.emit(pos, (255, 255, 200), count=6, speed=120.0, life=0.15, size=2.0, direction=direction, spread_angle=0.5)

    def add_step_dust(self, pos: Vec2, move_dir: Vec2):
        self.emit(pos, (200, 200, 200), count=2, speed=30.0, life=0.3, size=2.0, direction=-move_dir, spread_angle=1.0)

    def add_powerup_collection(self, pos: Vec2, color: tuple[int, int, int]):
        self.emit(pos, color, count=16, speed=120.0, life=0.8, size=3.5)

    def add_shield_hit(self, pos: Vec2, amount: int):
        strength = max(4, min(18, int(amount) // 4))
        self.emit(pos, (120, 210, 255), count=strength, speed=90.0, life=0.35, size=2.6)

    def add_dash_effect(self, pos: Vec2, dash_dir: Vec2):
        back = -dash_dir
        self.emit(pos, (160, 220, 255), count=8, speed=140.0, life=0.25, size=2.4, direction=back, spread_angle=0.4)

    def add_laser_beam(self, start: Vec2, end: Vec2, color: tuple[int, int, int]):
        d = (start - end).length()
        steps = max(3, int(d / 15.0))
        delta = (end - start) / float(steps)
        curr = start
        for _ in range(steps):
            self.emit(curr, color, count=2, speed=40.0, life=0.3, size=2.0)
            curr += delta

    def add_vortex_swirl(self, center: Vec2, time: float, radius: float):
        angle = time * 4.0
        offset = Vec2(math.cos(angle) * radius, math.sin(angle) * radius)
        p = Particle(
            pos=center + offset,
            vel=-offset.normalized() * 50.0,
            life=0.4,
            max_life=0.4,
            color=(180, 140, 255),
            size=3.0,
            decay=False
        )
        self.particles.append(p)
    
    def update(self, dt: float):
        if not self.particles:
            return
        keep = []
        for p in self.particles:
            p.life -= dt
            if p.life > 0:
                p.pos = p.pos + p.vel * dt
                if p.decay:
                    p.vel = p.vel * max(0.0, 1.0 - 2.0 * dt)
                keep.append(p)
        self.particles = keep

    def render(self, ctx, shake, to_iso):
        if not self.particles:
            return

        TAU = math.tau
        # Group particles by color key for batching
        buckets: dict[tuple, list] = {}
        for p in self.particles:
            ratio = max(0.0, p.life / p.max_life)
            alpha_i = int(max(0, min(255, ratio * 255)))
            key = (p.color[0], p.color[1], p.color[2], alpha_i)
            if key not in buckets:
                buckets[key] = []
            buckets[key].append((p, ratio))

        for (r, g, b, a_i), group in buckets.items():
            alpha = a_i / 255.0
            # Outer soft glow
            ctx.fillStyle = f"rgba({r}, {g}, {b}, {alpha * 0.3:.2f})"
            ctx.beginPath()
            for p, ratio in group:
                sx, sy = to_iso(p.pos, shake)
                radius = max(0.5, p.size * ratio) * 2.5
                ctx.moveTo(sx + radius, sy)
                ctx.arc(sx, sy, radius, 0, TAU)
            ctx.fill()
            
            # Inner bright core
            ctx.fillStyle = f"rgba({min(255, r + 40)}, {min(255, g + 40)}, {min(255, b + 40)}, {alpha:.2f})"
            ctx.beginPath()
            for p, ratio in group:
                sx, sy = to_iso(p.pos, shake)
                radius = max(0.5, p.size * ratio)
                ctx.moveTo(sx + radius, sy)
                ctx.arc(sx, sy, radius, 0, TAU)
            ctx.fill()
