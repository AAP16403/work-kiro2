"""Game map/room and isometric rendering."""

import math
import random

from pyglet import shapes

import config
from config import FLOOR_MAIN, FLOOR_EDGE, FLOOR_GRID
from utils import Vec2, to_iso


class Room:
    """Game room/map."""

    def __init__(self, batch, width: int, height: int):
        self.batch = batch
        self._grid: list[object] = []
        self._boundary: list[tuple[object, float]] = []
        self._pulse_lines: list[tuple[object, int, float]] = []
        self._pulse_nodes: list[tuple[object, int, float]] = []
        self._decor: list[object] = []
        self._floor = None
        self._edge = None
        self._t = 0.0
        self._w = width
        self._h = height

        # Gradient backdrop via stacked translucent rectangles.
        self._bg_a = shapes.Rectangle(0, 0, width, height, color=config.BG_TOP, batch=batch)
        self._bg_b = shapes.Rectangle(0, 0, width, height, color=config.BG_BOTTOM, batch=batch)
        self._bg_b.opacity = 120

        self._ambient: List[tuple[shapes.Circle, float, float, float]] = []
        self._scanlines: List[tuple[shapes.Line, int, float]] = []
        self._vignette: List[tuple[shapes.Circle, float]] = []
        self._bg_grid: List[tuple[shapes.Line, int, float]] = []
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

        # Subtle filmic vignette.
        corners = (
            (0, 0),
            (self._w, 0),
            (0, self._h),
            (self._w, self._h),
        )
        for cx, cy in corners:
            vr = min(self._w, self._h) * random.uniform(0.32, 0.46)
            c = shapes.Circle(cx, cy, vr, color=(6, 7, 12), batch=self.batch)
            c.opacity = random.randint(34, 54)
            phase = random.uniform(0.0, math.tau)
            self._vignette.append((c, phase))

        # Very soft moving scanlines for synthwave vibe.
        scan_count = max(12, min(24, int(self._h / 42)))
        for i in range(scan_count):
            y = (i / max(1, scan_count - 1)) * self._h
            ln = shapes.Line(0, y, self._w, y, thickness=1, color=(90, 120, 180), batch=self.batch)
            base = random.randint(9, 20)
            ln.opacity = base
            phase = random.uniform(0.0, math.tau)
            self._scanlines.append((ln, base, phase))
        
        # New background grid
        bg_grid_count = max(10, min(20, int(self._w / 50)))
        for i in range(bg_grid_count):
            x = (i / max(1, bg_grid_count - 1)) * self._w
            ln = shapes.Line(x, 0, x, self._h, thickness=1, color=(100, 120, 160), batch=self.batch)
            base = random.randint(5, 15)
            ln.opacity = base
            phase = random.uniform(0.0, math.tau)
            self._bg_grid.append((ln, base, phase))

    def resize(self, width: int, height: int):
        self._w = width
        self._h = height
        self._bg_a.width = width
        self._bg_a.height = height
        self._bg_b.width = width
        self._bg_b.height = height
        self._rebuild_floor()

    def rebuild(self) -> None:
        """Rebuild floor visuals (use when arena radius settings change)."""
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
        for o, _phase in self._boundary:
            if hasattr(o, "delete"):
                o.delete()
        self._boundary.clear()
        for o, _base, _phase in self._pulse_lines:
            if hasattr(o, "delete"):
                o.delete()
        self._pulse_lines.clear()
        for o, _base, _phase in self._pulse_nodes:
            if hasattr(o, "delete"):
                o.delete()
        self._pulse_nodes.clear()
        for o in self._decor:
            if hasattr(o, "delete"):
                o.delete()
        self._decor.clear()
        for ln, _base, _phase in self._scanlines:
            if hasattr(ln, "delete"):
                ln.delete()
        self._scanlines.clear()
        for ln, _base, _phase in self._bg_grid:
            if hasattr(ln, "delete"):
                ln.delete()
        self._bg_grid.clear()
        self._build_floor()

    def _build_floor(self):
        """Build the isometric floor with enhanced visuals."""
        radius = float(config.ROOM_RADIUS)

        def iso_point(angle, r=radius):
            p = Vec2(math.cos(angle) * float(r), math.sin(angle) * float(r))
            return to_iso(p, Vec2(0, 0))

        # Create diamond shape with multiple points for smoother edges
        points = [iso_point((i / 8) * math.tau, radius) for i in range(8)]
        edge_points = [iso_point((i / 8) * math.tau, radius * 1.03) for i in range(8)]

        self._floor = shapes.Polygon(*points, color=FLOOR_MAIN, batch=self.batch)
        self._edge = shapes.Polygon(*edge_points, color=FLOOR_EDGE, batch=self.batch)
        self._edge.opacity = 150  # Border glow

        # Soft central lighting (screen-space; low opacity so it "just adds depth").
        cx = self._w * 0.5
        cy = self._h * 0.5
        light_a = shapes.Circle(cx, cy, min(self._w, self._h) * 0.30, color=(60, 80, 125), batch=self.batch)
        light_a.opacity = 18
        light_b = shapes.Circle(cx, cy, min(self._w, self._h) * 0.18, color=(140, 95, 190), batch=self.batch)
        light_b.opacity = 12
        self._decor.extend([light_a, light_b])

        # Enhanced grid with multiple densities for better visual clarity
        grid_step = max(52, int(radius * 0.14))
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
        fine_grid_step = max(28, int(radius * 0.075))
        fine_n = max(10, int(radius // fine_grid_step))
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

        # Boundary ring for visual containment (static-ish, separate pulse).
        num_boundary_points = 40
        for i in range(num_boundary_points):
            angle1 = (i / num_boundary_points) * math.tau
            angle2 = ((i + 1) / num_boundary_points) * math.tau
            p1 = iso_point(angle1, radius * 1.01)
            p2 = iso_point(angle2, radius * 1.01)
            ln = shapes.Line(
                p1[0],
                p1[1],
                p2[0],
                p2[1],
                thickness=2,
                color=(155, 110, 180),
                batch=self.batch,
            )
            ln.opacity = 135
            self._boundary.append((ln, random.uniform(0.0, math.tau)))

        self._build_floor_decor(radius)

    def _build_floor_decor(self, radius: float) -> None:
        """Add panels + glowing circuit lines for a more detailed floor."""
        # Panel "tiles" (isometric diamonds) within the room.
        panel_count = max(26, min(70, int(radius * 0.20)))
        for _ in range(panel_count):
            ang = random.uniform(0.0, math.tau)
            r = (random.random() ** 0.65) * (radius * 0.82)
            center = Vec2(math.cos(ang) * r, math.sin(ang) * r)

            sx = random.uniform(18.0, 46.0)
            sy = random.uniform(12.0, 34.0)

            p1 = center + Vec2(sx, 0.0)
            p2 = center + Vec2(0.0, sy)
            p3 = center + Vec2(-sx, 0.0)
            p4 = center + Vec2(0.0, -sy)
            x1, y1 = to_iso(p1, Vec2(0, 0))
            x2, y2 = to_iso(p2, Vec2(0, 0))
            x3, y3 = to_iso(p3, Vec2(0, 0))
            x4, y4 = to_iso(p4, Vec2(0, 0))

            col = random.choice([(52, 60, 82), (38, 44, 62), (58, 66, 90), (44, 50, 72)])
            poly = shapes.Polygon((x1, y1), (x2, y2), (x3, y3), (x4, y4), color=col, batch=self.batch)
            poly.opacity = random.randint(22, 46)
            self._decor.append(poly)

            # Occasional panel seams (subtle outlines).
            if random.random() < 0.22 and sx * sy > 700:
                seam_col = random.choice([(110, 140, 180), (160, 120, 190), (120, 180, 170)])
                base = random.randint(28, 55)
                ln1 = shapes.Line(x1, y1, x2, y2, thickness=1, color=seam_col, batch=self.batch)
                ln1.opacity = base
                ln2 = shapes.Line(x2, y2, x3, y3, thickness=1, color=seam_col, batch=self.batch)
                ln2.opacity = base
                ln3 = shapes.Line(x3, y3, x4, y4, thickness=1, color=seam_col, batch=self.batch)
                ln3.opacity = base
                ln4 = shapes.Line(x4, y4, x1, y1, thickness=1, color=seam_col, batch=self.batch)
                ln4.opacity = base
                self._decor.extend([ln1, ln2, ln3, ln4])

            # New: Add a chance for a smaller inner diamond
            if random.random() < 0.3:
                p1_inner = center + Vec2(sx * 0.5, 0.0)
                p2_inner = center + Vec2(0.0, sy * 0.5)
                p3_inner = center + Vec2(-sx * 0.5, 0.0)
                p4_inner = center + Vec2(0.0, -sy * 0.5)
                x1_inner, y1_inner = to_iso(p1_inner, Vec2(0, 0))
                x2_inner, y2_inner = to_iso(p2_inner, Vec2(0, 0))
                x3_inner, y3_inner = to_iso(p3_inner, Vec2(0, 0))
                x4_inner, y4_inner = to_iso(p4_inner, Vec2(0, 0))
                inner_col = random.choice([(60, 70, 90), (45, 55, 75)])
                inner_poly = shapes.Polygon((x1_inner, y1_inner), (x2_inner, y2_inner), (x3_inner, y3_inner), (x4_inner, y4_inner), color=inner_col, batch=self.batch)
                inner_poly.opacity = random.randint(30, 50)
                self._decor.append(inner_poly)

            # New: Add a chance for a central glow
            if random.random() < 0.15:
                cx, cy = to_iso(center, Vec2(0, 0))
                glow = shapes.Circle(cx, cy, radius=random.uniform(3, 6), color=(150, 180, 220), batch=self.batch)
                glow.opacity = random.randint(20, 40)
                self._decor.append(glow)

        # Circuit lines (pulse in update).
        circuit_count = max(14, min(26, int(radius * 0.07)))
        dirs = [Vec2(1, 0), Vec2(0, 1), Vec2(1, 1), Vec2(1, -1)]
        for _ in range(circuit_count):
            for _attempt in range(10):
                ang = random.uniform(0.0, math.tau)
                r = (random.random() ** 0.7) * (radius * 0.72)
                start = Vec2(math.cos(ang) * r, math.sin(ang) * r)
                d = random.choice(dirs).normalized()
                length = random.uniform(radius * 0.18, radius * 0.42)
                end = start + d * length
                if start.length() <= radius * 0.88 and end.length() <= radius * 0.88:
                    break
            else:
                continue

            x1, y1 = to_iso(start, Vec2(0, 0))
            x2, y2 = to_iso(end, Vec2(0, 0))
            col = random.choice([(90, 200, 255), (200, 120, 255), (120, 240, 200)])
            thickness = random.choice([2, 2, 3])
            ln = shapes.Line(x1, y1, x2, y2, thickness=thickness, color=col, batch=self.batch)
            base = random.randint(42, 70)
            ln.opacity = base
            phase = random.uniform(0.0, math.tau)
            self._pulse_lines.append((ln, base, phase))

            # End nodes.
            for x, y in ((x1, y1), (x2, y2)):
                node = shapes.Circle(x, y, radius=3.2, color=col, batch=self.batch)
                node.opacity = min(110, base + 45)
                self._pulse_nodes.append((node, node.opacity, phase + random.uniform(-0.8, 0.8)))

        # Beacon lights around the edge.
        for i in range(10):
            a = (i / 10) * math.tau + (math.tau / 20)
            wp = Vec2(math.cos(a) * (radius * 0.985), math.sin(a) * (radius * 0.985))
            x, y = to_iso(wp, Vec2(0, 0))
            col = random.choice([(170, 200, 255), (255, 120, 255), (120, 240, 200)])
            glow = shapes.Circle(x, y, radius=10.5, color=col, batch=self.batch)
            glow.opacity = 26
            core = shapes.Circle(x, y, radius=4.0, color=(255, 255, 255), batch=self.batch)
            core.opacity = 120
            phase = random.uniform(0.0, math.tau)
            self._pulse_nodes.append((glow, glow.opacity, phase))
            self._pulse_nodes.append((core, core.opacity, phase + 0.7))

    def update(self, dt: float):
        self._t += dt

        # Subtle pulsing grid opacity for depth.
        pulse = 0.5 + 0.5 * math.sin(self._t * 0.8)
        for ln in self._grid:
            if hasattr(ln, "opacity"):
                base = 110 if getattr(ln, "thickness", 1) >= 1 else 34
                ln.opacity = int(base * (0.72 + 0.28 * pulse))

        # Boundary glow.
        for ln, phase in self._boundary:
            if hasattr(ln, "opacity"):
                ln.opacity = int(110 + 55 * (0.5 + 0.5 * math.sin(self._t * 1.2 + phase)))

        # Circuit pulses.
        for ln, base, phase in self._pulse_lines:
            if hasattr(ln, "opacity"):
                ln.opacity = int(base * (0.55 + 0.45 * (0.5 + 0.5 * math.sin(self._t * 2.4 + phase))))
        for node, base, phase in self._pulse_nodes:
            if hasattr(node, "opacity"):
                node.opacity = int(base * (0.6 + 0.4 * (0.5 + 0.5 * math.sin(self._t * 2.9 + phase))))

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

        for ln, base, phase in self._scanlines:
            ln.opacity = int(base * (0.55 + 0.45 * (0.5 + 0.5 * math.sin(self._t * 1.15 + phase))))

        for ln, base, phase in self._bg_grid:
            ln.opacity = int(base * (0.6 + 0.4 * (0.5 + 0.5 * math.sin(self._t * 0.4 + phase))))

        for vg, phase in self._vignette:
            vg.opacity = int(28 + 28 * (0.5 + 0.5 * math.sin(self._t * 0.45 + phase)))
