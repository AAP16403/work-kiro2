"""Game map/room and isometric rendering."""

import math
from typing import List

import pyglet
from pyglet import shapes

from config import SCREEN_W, SCREEN_H, ROOM_RADIUS, FLOOR_MAIN, FLOOR_EDGE, FLOOR_GRID
from utils import Vec2, to_iso


class Room:
    """Game room/map."""

    def __init__(self, batch):
        self.batch = batch
        self._grid: List[object] = []
        self._floor = None
        self._edge = None

        # Gradient backdrop via stacked translucent rectangles.
        self._bg_a = shapes.Rectangle(0, 0, SCREEN_W, SCREEN_H, color=(14, 18, 26), batch=batch)
        self._bg_b = shapes.Rectangle(0, 0, SCREEN_W, SCREEN_H, color=(9, 10, 16), batch=batch)
        self._bg_b.opacity = 120

        self._build_floor()

    def _build_floor(self):
        """Build the isometric floor with enhanced visuals."""
        def iso_point(angle):
            p = Vec2(math.cos(angle) * ROOM_RADIUS, math.sin(angle) * ROOM_RADIUS)
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
        for i in range(-5, 6):
            # Primary grid lines (every 50 units)
            a = Vec2(i * grid_step, -ROOM_RADIUS)
            b = Vec2(i * grid_step, ROOM_RADIUS)
            ax, ay = to_iso(a, Vec2(0, 0))
            bx, by = to_iso(b, Vec2(0, 0))
            ln = shapes.Line(ax, ay, bx, by, thickness=1, color=FLOOR_GRID, batch=self.batch)
            ln.opacity = 120
            self._grid.append(ln)

            a = Vec2(-ROOM_RADIUS, i * grid_step)
            b = Vec2(ROOM_RADIUS, i * grid_step)
            ax, ay = to_iso(a, Vec2(0, 0))
            bx, by = to_iso(b, Vec2(0, 0))
            ln = shapes.Line(ax, ay, bx, by, thickness=1, color=FLOOR_GRID, batch=self.batch)
            ln.opacity = 120
            self._grid.append(ln)

        # Add secondary finer grid for visual richness
        fine_grid_step = 25
        for i in range(-16, 17):
            a = Vec2(i * fine_grid_step, -ROOM_RADIUS)
            b = Vec2(i * fine_grid_step, ROOM_RADIUS)
            ax, ay = to_iso(a, Vec2(0, 0))
            bx, by = to_iso(b, Vec2(0, 0))
            ln = shapes.Line(ax, ay, bx, by, thickness=0.5, color=FLOOR_GRID, batch=self.batch)
            ln.opacity = 40
            self._grid.append(ln)

            a = Vec2(-ROOM_RADIUS, i * fine_grid_step)
            b = Vec2(ROOM_RADIUS, i * fine_grid_step)
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
