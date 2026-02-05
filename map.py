"""Game map/room and isometric rendering."""

import math
import random
from typing import List

import pyglet
from pyglet import shapes

import config
from config import FLOOR_MAIN, FLOOR_EDGE, FLOOR_GRID
from utils import Vec2, to_iso


class Room:
    """Game room/map."""

    def __init__(self, batch, width: int, height: int):
        self.batch = batch
        self._grid: List[object] = []
        self._floor = None
        self._edge = None
        self._t = 0.0
        self._w = width
        self._h = height

        # Gradient backdrop via stacked translucent rectangles.
        self._bg_a = shapes.Rectangle(0, 0, width, height, color=(14, 18, 26), batch=batch)
        self._bg_b = shapes.Rectangle(0, 0, width, height, color=(9, 10, 16), batch=batch)
        self._bg_b.opacity = 120

        self._ambient: List[tuple[shapes.Circle, float, float, float]] = []
        self._build_ambient()
        self._build_floor()

    def _build_ambient(self):
        count = max(8, min(18, int((self._w * self._h) / 140_000)))
        for _ in range(count):
            r = random.uniform(14, 40)
            x = random.uniform(0, self._w)
            y = random.uniform(0, self._h)
            col = random.choice([(40, 80, 140), (90, 50, 120), (60, 110, 160)])
            orb = shapes.Circle(x, y, r, color=col, batch=self.batch)
            orb.opacity = random.randint(18, 40)
            vx = random.uniform(-10, 10)
            vy = random.uniform(-8, 8)
            phase = random.uniform(0, math.tau)
            self._ambient.append((orb, vx, vy, phase))

    def resize(self, width: int, height: int):
        self._w = width
        self._h = height
        self._bg_a.width = width
        self._bg_a.height = height
        self._bg_b.width = width
        self._bg_b.height = height
        self._rebuild_floor()

    def _rebuild_floor(self):
        if self._floor is not None:
            self._floor.delete()
            self._floor = None
        if self._edge is not None:
            self._edge.delete()
            self._edge = None
        for o in self._grid:
            if hasattr(o, "delete"):
                o.delete()
        self._grid.clear()
        self._build_floor()

    def _build_floor(self):
        """Build the isometric floor with enhanced visuals."""
        radius = float(config.ROOM_RADIUS)

        def iso_point(angle):
            p = Vec2(math.cos(angle) * radius, math.sin(angle) * radius)
            return to_iso(p, Vec2(0, 0))

        # Create diamond shape with multiple points for smoother edges
        points = []
        for i in range(8):
            angle = (i / 8) * math.tau
            points.append(iso_point(angle))

        self._floor = shapes.Polygon(*points, color=FLOOR_MAIN, batch=self.batch)
        self._edge = shapes.Polygon(*points, color=FLOOR_EDGE, batch=self.batch)
        self._edge.opacity = 180  # More visible

        # Enhanced grid with multiple densities for better visual clarity
        grid_step = 50
        grid_n = max(5, int(radius // grid_step))
        for i in range(-grid_n, grid_n + 1):
            # Primary grid lines (every 50 units)
            a = Vec2(i * grid_step, -radius)
            b = Vec2(i * grid_step, radius)
            ax, ay = to_iso(a, Vec2(0, 0))
            bx, by = to_iso(b, Vec2(0, 0))
            ln = shapes.Line(ax, ay, bx, by, thickness=1, color=FLOOR_GRID, batch=self.batch)
            ln.opacity = 120
            self._grid.append(ln)

            a = Vec2(-radius, i * grid_step)
            b = Vec2(radius, i * grid_step)
            ax, ay = to_iso(a, Vec2(0, 0))
            bx, by = to_iso(b, Vec2(0, 0))
            ln = shapes.Line(ax, ay, bx, by, thickness=1, color=FLOOR_GRID, batch=self.batch)
            ln.opacity = 120
            self._grid.append(ln)

        # Add secondary finer grid for visual richness
        fine_grid_step = 25
        fine_n = max(16, int(radius // fine_grid_step))
        for i in range(-fine_n, fine_n + 1):
            a = Vec2(i * fine_grid_step, -radius)
            b = Vec2(i * fine_grid_step, radius)
            ax, ay = to_iso(a, Vec2(0, 0))
            bx, by = to_iso(b, Vec2(0, 0))
            ln = shapes.Line(ax, ay, bx, by, thickness=0.5, color=FLOOR_GRID, batch=self.batch)
            ln.opacity = 40
            self._grid.append(ln)

            a = Vec2(-radius, i * fine_grid_step)
            b = Vec2(radius, i * fine_grid_step)
            ax, ay = to_iso(a, Vec2(0, 0))
            bx, by = to_iso(b, Vec2(0, 0))
            ln = shapes.Line(ax, ay, bx, by, thickness=0.5, color=FLOOR_GRID, batch=self.batch)
            ln.opacity = 40
            self._grid.append(ln)

        # Boundary ring for visual containment
        num_boundary_points = 32
        for i in range(num_boundary_points):
            angle1 = (i / num_boundary_points) * math.tau
            angle2 = ((i + 1) / num_boundary_points) * math.tau
            p1 = iso_point(angle1)
            p2 = iso_point(angle2)
            ln = shapes.Line(
                p1[0], p1[1], p2[0], p2[1],
                thickness=2,
                color=(150, 100, 150),  # Purple boundary
                batch=self.batch
            )
            ln.opacity = 150
            self._grid.append(ln)

    def update(self, dt: float):
        self._t += dt

        # Subtle pulsing grid opacity for depth.
        pulse = 0.5 + 0.5 * math.sin(self._t * 0.8)
        for ln in self._grid:
            if hasattr(ln, "opacity"):
                base = 120 if getattr(ln, "thickness", 1) >= 1 else 40
                ln.opacity = int(base * (0.75 + 0.25 * pulse))

        # Ambient background orbs.
        for orb, vx, vy, phase in self._ambient:
            orb.x += vx * dt
            orb.y += vy * dt
            if orb.x < -60:
                orb.x = self._w + 60
            elif orb.x > self._w + 60:
                orb.x = -60
            if orb.y < -60:
                orb.y = self._h + 60
            elif orb.y > self._h + 60:
                orb.y = -60
            orb.opacity = int(18 + 18 * (0.5 + 0.5 * math.sin(self._t * 0.6 + phase)))
