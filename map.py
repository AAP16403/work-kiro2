"""Panda3D map room visuals."""

from __future__ import annotations

import math

from panda3d.core import CardMaker, LineSegs, NodePath

import config


class Room:
    """Simple arena floor + boundary visuals."""

    def __init__(self, batch, width: int, height: int, map_type: str = config.MAP_CIRCLE, parent: NodePath | None = None):
        self.map_type = map_type
        self.combat_intensity = 0.0
        self.safe_zone = None
        self._t = 0.0

        self._parent = parent
        if self._parent is None:
            from direct.showbase import ShowBaseGlobal

            self._parent = getattr(ShowBaseGlobal, "render", None)
        self.root = self._parent.attachNewNode("room") if self._parent is not None else NodePath("room")
        self.floor = None
        self.boundary = None
        self.width = int(width)
        self.height = int(height)
        self._build()

    def _build(self) -> None:
        if not self.root:
            return

        if self.floor:
            self.floor.removeNode()
            self.floor = None
        if self.boundary:
            self.boundary.removeNode()
            self.boundary = None

        radius = float(config.ROOM_RADIUS)
        cm = CardMaker("room_floor")
        cm.setFrame(-radius, radius, -radius, radius)
        self.floor = self.root.attachNewNode(cm.generate())
        self.floor.setP(-90)
        self.floor.setZ(-0.1) # Slight offset to avoid z-fighting if any
        self.floor.setTransparency(True)
        # Gradient or Grid simulation via vertex colors?
        # For now, just a better base color.
        self.floor.setColor(0.11, 0.14, 0.18, 1.0)
        self.floor.setTwoSided(True)
        self.floor.setColorScaleOff(1)
        
        # Add a grid overlay
        self._add_grid(radius)

        self.boundary = self.root.attachNewNode("room_boundary")
        self._append_boundary(self.boundary, radius, self.map_type, z=0.6, color=(0.34, 0.46, 0.58, 0.86), thickness=2.6)
        if str(self.map_type) == config.MAP_DONUT:
            self._append_boundary(self.boundary, radius * 0.4, config.MAP_CIRCLE, z=0.62, color=(0.48, 0.58, 0.7, 0.8), thickness=2.0)
        self.boundary.setTransparency(True)

    def _boundary_points(self, radius: float, map_type: str) -> list[tuple[float, float]]:
        m = str(map_type or config.MAP_CIRCLE)
        if m == config.MAP_DIAMOND:
            d = radius * 0.707
            return [(0, d), (d, 0), (0, -d), (-d, 0)]
        if m == config.MAP_CROSS:
            arm = radius
            w = radius * 0.35
            return [(-w, arm), (w, arm), (w, w), (arm, w), (arm, -w), (w, -w), (w, -arm), (-w, -arm), (-w, -w), (-arm, -w), (-arm, w), (-w, w)]
        if m == config.MAP_DONUT:
            return self._circle_points(radius, 52)
        return self._circle_points(radius, 64)

    def _append_boundary(self, parent: NodePath, radius: float, map_type: str, z: float, color, thickness: float) -> None:
        ls = LineSegs("room_boundary_ring")
        ls.setThickness(float(thickness))
        ls.setColor(float(color[0]), float(color[1]), float(color[2]), float(color[3]))
        points = self._boundary_points(radius, map_type)
        if not points:
            return
        first = points[0]
        ls.moveTo(first[0], first[1], float(z))
        for px, py in points[1:]:
            ls.drawTo(px, py, float(z))
        ls.drawTo(first[0], first[1], float(z))
        parent.attachNewNode(ls.create())

    @staticmethod
    def _circle_points(radius: float, segments: int) -> list[tuple[float, float]]:
        return [(math.cos(i / segments * math.tau) * radius, math.sin(i / segments * math.tau) * radius) for i in range(segments)]

    def update(self, dt: float):
        self._t += float(dt)
        if not self.floor:
            return
        pulse = 0.06 * self.combat_intensity * (0.5 + 0.5 * math.sin(self._t * 6.0))
        self.floor.setColor(0.1 + pulse * 0.65, 0.125 + pulse * 0.72, 0.16 + pulse * 0.76, 1.0)

    def resize(self, width: int, height: int):
        self.width = int(width)
        self.height = int(height)

    def rebuild(self, map_type: str):
        self.map_type = str(map_type or config.MAP_CIRCLE)
        self._build()

    def set_combat_intensity(self, intensity: float):
        self.combat_intensity = max(0.0, min(1.0, float(intensity)))

    def _add_grid(self, radius: float):
        # Create a simple grid drawing
        ls = LineSegs("room_grid")
        ls.setThickness(1.0)
        ls.setColor(0.22, 0.28, 0.34, 0.24)
        
        step = 56.0
        r = radius
        # Horizontal lines
        y = -r
        while y <= r:
            ls.moveTo(-r, y, 0.1)
            ls.drawTo(r, y, 0.1)
            y += step
            
        # Vertical lines
        x = -r
        while x <= r:
            ls.moveTo(x, -r, 0.1)
            ls.drawTo(x, r, 0.1)
            x += step
            
        self.root.attachNewNode(ls.create())

    def set_safe_zone(self, enabled: bool, radius: float = 0.0):
        if not enabled:
            if self.safe_zone:
                self.safe_zone.removeNode()
                self.safe_zone = None
            return

        if not self.safe_zone:
            self.safe_zone = self.root.attachNewNode("safe_zone")
            self._append_boundary(self.safe_zone, radius, config.MAP_CIRCLE, z=1.0, color=(0.2, 1.0, 0.4, 0.6), thickness=2.0)
            cm = CardMaker("safe_zone_floor")
            cm.setFrame(-radius, radius, -radius, radius)
            floor = self.safe_zone.attachNewNode(cm.generate())
            floor.setP(-90)
            floor.setZ(0.2)
            floor.setColor(0.2, 1.0, 0.4, 0.15)
            floor.setTransparency(True)
        else:
            # Rebuild if radius changed significantly? For now static.
            pass

    def destroy(self) -> None:
        if self.root:
            self.root.removeNode()
