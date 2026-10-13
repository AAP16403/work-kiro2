"""Game map/room and isometric rendering.

The point lists, colours and animation values come from geometry_build.py, which makes no pyglet
calls. This module creates the pyglet shapes from those records on the main thread, in the same order
the old code created them.
"""

import math
import random

from pyglet import shapes
from pyglet.graphics import Group

import config
import geometry_build
import motion
import utils
from config import FLOOR_MAIN, FLOOR_EDGE, FLOOR_GRID


def _set_opacity(shape, value: int) -> None:
    """Write opacity only when it changes. Every opacity write re-uploads the shape's colour buffer."""
    if shape.opacity != value:
        shape.opacity = value


def _worker_enabled() -> bool:
    """config.ARENA_GEOMETRY_WORKER switches the worker on. It is off by default (geometry_build.WORKER_ENABLED_DEFAULT)."""
    return bool(getattr(config, "ARENA_GEOMETRY_WORKER", geometry_build.WORKER_ENABLED_DEFAULT))


def _make_shape(rec, batch, group=None):
    """Create the pyglet shape for one geometry record (see geometry_build for the formats)."""
    kind = rec[0]
    if kind == "circle":
        _, x, y, radius, color, opacity = rec
        shape = shapes.Circle(x, y, radius, color=color, batch=batch, group=group)
    elif kind == "line":
        _, x1, y1, x2, y2, thickness, color, opacity = rec
        shape = shapes.Line(x1, y1, x2, y2, thickness=thickness, color=color, batch=batch, group=group)
    elif kind == "polygon":
        _, vertices, color, opacity = rec
        shape = shapes.Polygon(*vertices, color=color, batch=batch, group=group)
    elif kind == "rect":
        _, x, y, width, height, color, opacity = rec
        shape = shapes.Rectangle(x, y, width, height, color=color, batch=batch, group=group)
    else:
        raise ValueError(f"unknown geometry record: {kind!r}")
    if shape.opacity != opacity:
        shape.opacity = opacity
    return shape


class Room:
    """Game room/map."""

    def __init__(self, batch, width: int, height: int, map_type: str = config.MAP_CIRCLE):
        self.batch = batch
        self.map_type = map_type
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
        self._prefetcher = None

        # Combat intensity overlay (0 = calm cool tint, 1 = boss warm tint).
        self._combat_intensity = 0.0
        self._combat_intensity_target = 0.0
        self._intensity_overlay = None

        # Gradient backdrop via stacked translucent rectangles.
        # The backdrop gets its own draw-order group so the starfield can sit above it and below the floor.
        bg_group = Group(order=int(config.ROOM_BG_LAYER_ORDER))
        for target, rec, _aux in geometry_build.background_ops(width, height, config.BG_TOP, config.BG_BOTTOM):
            shape = _make_shape(rec, batch, bg_group)
            if target == "bg_a":
                self._bg_a = shape
            else:
                self._bg_b = shape

        self._ambient: list[tuple[shapes.Circle, float, float, float]] = []
        self._scanlines: list[tuple[shapes.Line, int, float]] = []
        self._vignette: list[tuple[shapes.Circle, float]] = []
        self._bg_grid: list[tuple[shapes.Line, int, float]] = []
        self._build_ambient()
        self._build_floor()

    def _build_ambient(self):
        for target, rec, aux in geometry_build.ambient_ops(self._w, self._h, random):
            shape = _make_shape(rec, self.batch)
            if target == "ambient":
                vx, vy, phase = aux
                self._ambient.append((shape, vx, vy, phase))
            elif target == "vignette":
                self._vignette.append((shape, aux))
            elif target == "scanline":
                base, phase = aux
                self._scanlines.append((shape, base, phase))
            else:  # bg_grid
                base, phase = aux
                self._bg_grid.append((shape, base, phase))

    def resize(self, width: int, height: int):
        self._w = width
        self._h = height
        self._bg_a.width = width
        self._bg_a.height = height
        self._bg_b.width = width
        self._bg_b.height = height
        self._rebuild_floor()

    def rebuild(self, map_type: str = None) -> None:
        """Rebuild floor visuals (use when arena radius settings change)."""
        if map_type:
            self.map_type = map_type
        self._rebuild_floor()

    def prefetch_arena(self, map_type: str = None, width: int = None, height: int = None) -> bool:
        """Start one arena's floor geometry in a worker process, for the next rebuild to pick up.

        Call it at wave start for the arena that comes next. It does nothing unless
        config.ARENA_GEOMETRY_WORKER is true. A rebuild for exactly this arena uses the worker's result if
        it has finished. Otherwise the rebuild builds the same geometry in-process. Returns True if a request
        was queued.
        """
        if not _worker_enabled():
            return False
        if self._prefetcher is None:
            self._prefetcher = geometry_build.FloorPrefetcher()
        return self._prefetcher.submit(self._arena_spec(map_type, width, height))

    def _arena_spec(self, map_type: str = None, width: int = None, height: int = None):
        return geometry_build.ArenaSpec(
            map_type=self.map_type if map_type is None else map_type,
            radius=float(config.ROOM_RADIUS),
            width=self._w if width is None else width,
            height=self._h if height is None else height,
            view_w=utils.VIEW_W,
            view_h=utils.VIEW_H,
            iso_x=utils.ISO_SCALE_X,
            iso_y=utils.ISO_SCALE_Y,
            floor_main=FLOOR_MAIN,
            floor_edge=FLOOR_EDGE,
            floor_grid=FLOOR_GRID,
        )

    def _rebuild_ops(self):
        """Floor ops for a rebuild. None means build in-process from the module RNG (the default path).

        With the worker on, a request queued by prefetch_arena() for this exact arena is used once it has
        finished. Otherwise the same ops are built in-process from that request's seed, so the result is
        the same whichever path produced it.
        """
        if not _worker_enabled() or self._prefetcher is None:
            return None
        spec = self._arena_spec()
        seed = self._prefetcher.seed_for(spec)
        if seed is None:
            return None
        ops = self._prefetcher.take(spec)
        if ops is None:
            ops = geometry_build.floor_ops(spec, random.Random(seed))
        return ops

    def _rebuild_floor(self):
        # Free the previous floor shapes; otherwise old polygons stay in the batch (ghost floor, GPU leak).
        for poly in getattr(self, "_floor_polys", []):
            poly.delete()
        self._floor_polys = []
        if self._edge is not None:
            self._edge.delete()
            self._edge = None
        for io in getattr(self, "_intensity_overlays", []):
            io.delete()
        self._intensity_overlays = []
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
        # Scanlines and the background grid are built once in _build_ambient; keep them across floor rebuilds.
        self._build_floor(self._rebuild_ops())

    def _build_floor(self, ops=None):
        """Build the isometric floor. ``ops`` comes from geometry_build (see _rebuild_ops). None builds it here."""
        if ops is None:
            ops = geometry_build.floor_ops(self._arena_spec(), random)
        self._floor_polys = []
        self._intensity_overlays = []
        for target, rec, aux in ops:
            shape = _make_shape(rec, self.batch)
            if target == "floor":
                self._floor_polys.append(shape)
            elif target == "edge":
                self._edge = shape
            elif target == "intensity":
                self._intensity_overlays.append(shape)
            elif target == "grid":
                self._grid.append(shape)
            elif target == "boundary":
                self._boundary.append((shape, aux))
            elif target == "decor":
                self._decor.append(shape)
            elif target == "pulse_line":
                base, phase = aux
                self._pulse_lines.append((shape, base, phase))
            elif target == "pulse_node":
                base, phase = aux
                self._pulse_nodes.append((shape, base, phase))
            else:
                raise ValueError(f"unknown floor target: {target!r}")

    def set_combat_intensity(self, target: float) -> None:
        """Set the target combat intensity (0 = calm, 1 = boss fight)."""
        self._combat_intensity_target = max(0.0, min(1.0, float(target)))

    def update(self, dt: float):
        # Animation clock: frozen by reduced motion, which stops the pulses and the orb drift below.
        adt = motion.anim_dt(dt)
        self._t += adt

        # Smoothly lerp combat intensity toward target.
        ci = self._combat_intensity
        ct = self._combat_intensity_target
        if abs(ci - ct) > 0.001:
            speed = 0.8 if ct > ci else 1.5  # Fade in slower, fade out faster
            self._combat_intensity = ci + (ct - ci) * min(1.0, speed * dt)
        else:
            self._combat_intensity = ct

        # Update intensity overlay color and opacity.
        for io in self._intensity_overlays:
            if io is not None:
                ci = self._combat_intensity
                # Blend from cool blue-grey (calm) to alarm red (boss).
                r = int(30 + 100 * ci)
                g = int(35 - 15 * ci)
                b = int(42 - 20 * ci)
                if io.color[:3] != (r, g, b):
                    io.color = (r, g, b)
                _set_opacity(io, int(24 * ci))

        # Ambient background orbs position update
        for orb, vx, vy, phase in self._ambient:
            orb.x += vx * adt
            orb.y += vy * adt
            if orb.x < -60:
                orb.x = self._w + 60
            elif orb.x > self._w + 60:
                orb.x = -60
            if orb.y < -60:
                orb.y = self._h + 60
            elif orb.y > self._h + 60:
                orb.y = -60

        # Performance: Throttle static floor decorative opacity recalculations to every 2nd frame
        self._decor_tick = (getattr(self, "_decor_tick", 0) + 1) % 2
        if self._decor_tick != 0:
            return

        # Subtle pulsing grid opacity for depth.
        pulse = 0.5 + 0.5 * math.sin(self._t * 0.8)
        for ln in self._grid:
            if hasattr(ln, "opacity"):
                base = 110 if getattr(ln, "thickness", 1) >= 1 else 34
                _set_opacity(ln, int(base * (0.72 + 0.28 * pulse)))

        # Boundary glow. With ENABLE_RIM_PULSE, combat intensity adds a pulse that travels around the rim.
        rim = self._combat_intensity if config.ENABLE_RIM_PULSE else 0.0
        rim_step = math.tau * 2.0 / max(1, len(self._boundary))
        for i, (ln, phase) in enumerate(self._boundary):
            if hasattr(ln, "opacity"):
                wave = 0.5 + 0.5 * math.sin(self._t * 3.0 - i * rim_step)
                _set_opacity(ln, min(255, int(110 + 55 * (0.5 + 0.5 * math.sin(self._t * 1.2 + phase)) + 70.0 * rim * wave)))

        # Circuit pulses.
        for ln, base, phase in self._pulse_lines:
            if hasattr(ln, "opacity"):
                _set_opacity(ln, int(base * (0.55 + 0.45 * (0.5 + 0.5 * math.sin(self._t * 2.4 + phase)))))
        for node, base, phase in self._pulse_nodes:
            if hasattr(node, "opacity"):
                _set_opacity(node, int(base * (0.6 + 0.4 * (0.5 + 0.5 * math.sin(self._t * 2.9 + phase)))))

        for orb, _vx, _vy, phase in self._ambient:
            _set_opacity(orb, int(18 + 18 * (0.5 + 0.5 * math.sin(self._t * 0.6 + phase))))

        for ln, base, phase in self._scanlines:
            _set_opacity(ln, int(base * (0.55 + 0.45 * (0.5 + 0.5 * math.sin(self._t * 1.15 + phase)))))

        for ln, base, phase in self._bg_grid:
            _set_opacity(ln, int(base * (0.6 + 0.4 * (0.5 + 0.5 * math.sin(self._t * 0.4 + phase)))))

        for vg, phase in self._vignette:
            _set_opacity(vg, int(28 + 28 * (0.5 + 0.5 * math.sin(self._t * 0.45 + phase))))
