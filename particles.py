"""Particle system for visual effects and animations.

This module is intentionally self-contained and uses a persistent Batch to avoid
allocating new Shapes every frame.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Tuple
import math
import random

import pyglet
from pyglet import shapes

from utils import Vec2, to_iso


Color = Tuple[int, int, int]


@dataclass
class Particle:
    """Particle with simple physics and pre-created render objects."""

    pos: Vec2
    vel: Vec2
    ttl: float
    max_ttl: float
    size: float
    color: Color
    particle_type: str
    drag: float = 0.0

    # Optional orientation for streak-like particles.
    angle: float = 0.0

    # Render objects created once and then updated/reused.
    objs: List[object] = field(default_factory=list)


class ParticleSystem:
    """Manages particles and renders them with a dedicated Batch."""

    def __init__(self):
        self.particles: List[Particle] = []
        self.batch = pyglet.graphics.Batch()

    # ----------------------------
    # Particle creation helpers
    # ----------------------------
    def _add_flash(self, pos: Vec2, radius: float, color: Color, ttl: float):
        p = Particle(pos=pos, vel=Vec2(0, 0), ttl=ttl, max_ttl=ttl, size=radius, color=color, particle_type="flash")
        outer = shapes.Circle(0, 0, radius * 1.3, color=color, batch=self.batch)
        outer.opacity = 120
        core = shapes.Circle(0, 0, max(1, radius * 0.55), color=(255, 255, 255), batch=self.batch)
        core.opacity = 220
        p.objs.extend([outer, core])
        self.particles.append(p)

    def _add_smoke(self, pos: Vec2, vel: Vec2, radius: float, color: Color, ttl: float, drag: float = 1.0):
        p = Particle(pos=pos, vel=vel, ttl=ttl, max_ttl=ttl, size=radius, color=color, particle_type="smoke", drag=drag)
        blob = shapes.Circle(0, 0, radius, color=color, batch=self.batch)
        blob.opacity = 60
        p.objs.append(blob)
        self.particles.append(p)

    def _add_spark(self, pos: Vec2, vel: Vec2, length: float, color: Color, ttl: float, drag: float = 2.5):
        angle = math.atan2(vel.y, vel.x) if abs(vel.x) + abs(vel.y) > 1e-6 else 0.0
        p = Particle(
            pos=pos,
            vel=vel,
            ttl=ttl,
            max_ttl=ttl,
            size=length,
            color=color,
            particle_type="spark",
            drag=drag,
            angle=angle,
        )
        outer = shapes.Line(0, 0, 0, 0, thickness=3, color=color, batch=self.batch)
        outer.opacity = 180
        core = shapes.Line(0, 0, 0, 0, thickness=1, color=(255, 255, 255), batch=self.batch)
        core.opacity = 200
        p.objs.extend([outer, core])
        self.particles.append(p)

    def _add_ring(self, pos: Vec2, radius: float, color: Color, ttl: float, thickness: float = 3.0):
        p = Particle(pos=pos, vel=Vec2(0, 0), ttl=ttl, max_ttl=ttl, size=radius, color=color, particle_type="ring")
        arc = shapes.Arc(0, 0, radius, segments=48, thickness=thickness, color=color, batch=self.batch)
        arc.opacity = 160
        p.objs.append(arc)
        self.particles.append(p)

    def _add_debris(self, pos: Vec2, vel: Vec2, size: float, color: Color, ttl: float):
        p = Particle(pos=pos, vel=vel, ttl=ttl, max_ttl=ttl, size=size, color=color, particle_type="debris", drag=1.2)
        rect = shapes.Rectangle(0, 0, size * 2, size * 2, color=color, batch=self.batch)
        rect.anchor_x = size
        rect.anchor_y = size
        rect.opacity = 180
        p.objs.append(rect)
        self.particles.append(p)

    # ----------------------------
    # Public VFX entrypoints
    # ----------------------------
    def add_muzzle_flash(self, pos: Vec2, direction: Vec2, color: Color = (255, 200, 100)):
        self._add_flash(pos, radius=14, color=(255, 255, 255), ttl=0.06)

        base_angle = math.atan2(direction.y, direction.x)
        for _ in range(10):
            angle = base_angle + random.uniform(-0.45, 0.45)
            speed = random.uniform(180, 520)
            vel = Vec2(math.cos(angle) * speed, math.sin(angle) * speed)
            self._add_spark(pos, vel, length=random.uniform(10, 18), color=color, ttl=random.uniform(0.10, 0.22), drag=3.5)

        for _ in range(5):
            angle = base_angle + random.uniform(-0.7, 0.7)
            speed = random.uniform(25, 110)
            vel = Vec2(math.cos(angle) * speed, math.sin(angle) * speed)
            self._add_smoke(pos, vel, radius=random.uniform(5, 10), color=(190, 190, 200), ttl=random.uniform(0.35, 0.65), drag=1.2)

    def add_hit_particles(self, pos: Vec2, color: Color = (255, 100, 100)):
        self._add_flash(pos, radius=11, color=(255, 255, 255), ttl=0.08)
        for _ in range(8):
            angle = random.uniform(0, math.tau)
            speed = random.uniform(90, 260)
            vel = Vec2(math.cos(angle) * speed, math.sin(angle) * speed)
            self._add_spark(pos, vel, length=random.uniform(8, 14), color=color, ttl=random.uniform(0.14, 0.26), drag=2.8)

    def add_death_explosion(self, pos: Vec2, color: Color, enemy_type: str = "chaser"):
        scale = 1.0
        mult = 1.0
        if enemy_type == "tank":
            scale = 1.8
            mult = 2.2
        elif enemy_type == "swarm":
            scale = 0.6
            mult = 0.6
        elif enemy_type == "flyer":
            scale = 1.2
            mult = 1.3
        elif enemy_type == "engineer":
            scale = 1.1
            mult = 1.1

        self._add_ring(pos, radius=18 * scale, color=color, ttl=0.28, thickness=4.0)
        self._add_flash(pos, radius=26 * scale, color=(255, 255, 255), ttl=0.14)

        count = int(18 * mult)
        for _ in range(count):
            angle = random.uniform(0, math.tau)
            speed = random.uniform(120, 420) * scale
            vel = Vec2(math.cos(angle) * speed, math.sin(angle) * speed)
            if random.random() < 0.45:
                self._add_debris(pos, vel, size=random.uniform(2.5, 5.5) * scale, color=(110, 110, 120), ttl=random.uniform(0.55, 1.0))
            else:
                self._add_spark(pos, vel, length=random.uniform(10, 20) * scale, color=color, ttl=random.uniform(0.18, 0.5), drag=2.4)

        for _ in range(int(6 * mult)):
            vel = Vec2(random.uniform(-40, 40), random.uniform(20, 90))
            self._add_smoke(pos, vel, radius=random.uniform(10, 18) * scale, color=(110, 110, 120), ttl=random.uniform(0.65, 1.0), drag=0.5)

    def add_powerup_collection(self, pos: Vec2, color: Color):
        self._add_ring(pos, radius=10, color=color, ttl=0.3, thickness=3.0)
        for _ in range(18):
            angle = random.uniform(0, math.tau)
            speed = random.uniform(160, 320)
            vel = Vec2(math.cos(angle) * speed, math.sin(angle) * speed)
            self._add_spark(pos, vel, length=random.uniform(10, 16), color=color, ttl=0.35, drag=1.4)

    def add_step_dust(self, pos: Vec2, direction: Vec2):
        # Subtle dust behind moving player.
        back = Vec2(-direction.x, -direction.y)
        for _ in range(2):
            vel = back * random.uniform(40, 80) + Vec2(random.uniform(-30, 30), random.uniform(-30, 30))
            self._add_smoke(pos, vel, radius=random.uniform(4, 7), color=(120, 120, 140), ttl=random.uniform(0.25, 0.45), drag=1.8)

    def add_shield_hit(self, pos: Vec2, strength: float):
        c = (120, 220, 255)
        self._add_flash(pos, radius=12 + strength * 0.06, color=c, ttl=0.07)
        self._add_ring(pos, radius=18 + strength * 0.08, color=c, ttl=0.18, thickness=4.0)
        for _ in range(6):
            angle = random.uniform(0, math.tau)
            speed = random.uniform(120, 260)
            vel = Vec2(math.cos(angle) * speed, math.sin(angle) * speed)
            self._add_spark(pos, vel, length=random.uniform(10, 16), color=c, ttl=random.uniform(0.12, 0.22), drag=3.0)

    def add_vortex_swirl(self, pos: Vec2, t: float, radius: float, color: Color = (180, 140, 255)):
        # Emit a couple of orbiting sparks each frame while active.
        for i in range(3):
            ang = t * 7.0 + i * (math.tau / 3)
            p = pos + Vec2(math.cos(ang), math.sin(ang)) * radius
            tang = Vec2(-math.sin(ang), math.cos(ang))
            vel = tang * random.uniform(120, 180) + Vec2(random.uniform(-35, 35), random.uniform(-35, 35))
            self._add_spark(p, vel, length=random.uniform(12, 18), color=color, ttl=0.12, drag=6.0)
        self._add_ring(pos, radius=radius * 0.45, color=color, ttl=0.18, thickness=3.0)

    def add_laser_beam(self, start: Vec2, end: Vec2, color: Color = (255, 120, 255)):
        # A few sparks along the beam for energy feel.
        dx = end.x - start.x
        dy = end.y - start.y
        for _ in range(10):
            t = random.uniform(0.05, 0.95)
            p = Vec2(start.x + dx * t, start.y + dy * t)
            angle = random.uniform(0, math.tau)
            speed = random.uniform(80, 220)
            vel = Vec2(math.cos(angle) * speed, math.sin(angle) * speed)
            self._add_spark(p, vel, length=random.uniform(8, 14), color=color, ttl=random.uniform(0.08, 0.16), drag=5.0)

    # ----------------------------
    # Update and render
    # ----------------------------
    def update(self, dt: float):
        if not self.particles:
            return

        i = 0
        n = len(self.particles)
        while i < n:
            p = self.particles[i]
            p.ttl -= dt
            if p.ttl <= 0:
                for o in p.objs:
                    if hasattr(o, "delete"):
                        o.delete()
                # Remove without allocating/copying lists.
                last = self.particles[n - 1]
                self.particles[i] = last
                self.particles.pop()
                n -= 1
                continue

            # Drag
            if p.drag > 0:
                p.vel = p.vel * max(0.0, 1.0 - p.drag * dt)

            # Type-based forces
            if p.particle_type == "debris":
                p.vel.y -= 420 * dt
            elif p.particle_type == "smoke":
                p.vel.y += 45 * dt
            elif p.particle_type == "spark":
                p.vel.y -= 160 * dt

            p.pos = p.pos + p.vel * dt
            i += 1

    def render(self, shake: Vec2):
        if not self.particles:
            return

        for p in self.particles:
            alpha_ratio = max(0.0, min(1.0, p.ttl / p.max_ttl))
            sx, sy = to_iso(p.pos, shake)

            if p.particle_type == "flash":
                outer, core = p.objs
                outer.x, outer.y = sx, sy
                core.x, core.y = sx, sy
                outer.radius = p.size * (0.8 + 0.2 * alpha_ratio)
                core.radius = max(1.0, p.size * 0.45 * alpha_ratio)
                outer.opacity = int(140 * alpha_ratio)
                core.opacity = int(255 * alpha_ratio)

            elif p.particle_type == "smoke":
                (blob,) = p.objs
                blob.x, blob.y = sx, sy
                blob.radius = p.size * (1.0 + (1.0 - alpha_ratio) * 1.1)
                blob.opacity = int(70 * alpha_ratio)

            elif p.particle_type == "ring":
                (arc,) = p.objs
                arc.x, arc.y = sx, sy
                arc.radius = p.size + (1.0 - alpha_ratio) * 80
                arc.opacity = int(170 * alpha_ratio)

            elif p.particle_type == "spark":
                outer, core = p.objs
                length = p.size * (0.45 + 0.55 * alpha_ratio)
                dirv = p.vel.normalized()
                if dirv.length() <= 1e-6:
                    dirv = Vec2(math.cos(p.angle), math.sin(p.angle))
                x2 = sx - dirv.x * length
                y2 = sy - dirv.y * length
                outer.x, outer.y, outer.x2, outer.y2 = sx, sy, x2, y2
                core.x, core.y, core.x2, core.y2 = sx, sy, x2, y2
                outer.opacity = int(200 * alpha_ratio)
                core.opacity = int(230 * alpha_ratio)

            elif p.particle_type == "debris":
                (rect,) = p.objs
                rect.x, rect.y = sx, sy
                rect.opacity = int(220 * alpha_ratio)
                rect.rotation = (p.ttl / p.max_ttl) * 360.0

        self.batch.draw()
