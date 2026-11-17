"""Pyglet drawing for arena events that the trap and laser code does not already draw.

Meteor zones are Trap objects (visuals.py draws them) and the flare beam is a LaserBeam
(visuals.sync_laser draws it). This module draws the flare sector and the nebula cloud.
Shapes are created once per event. Each sync writes a shape only when its screen position
or opacity has changed, because every pyglet property write rebuilds a vertex list. The
projection uses plain floats, so a sync creates no shapes or lists per frame.
"""

import math

from pyglet import shapes

import config
import events
import utils

FLARE_SEGMENTS = 10
_FLARE_FILL = (255, 170, 70)
_FLARE_EDGE = (255, 215, 140)
_NEBULA_FILL = (120, 170, 255)
_NEBULA_EDGE = (190, 215, 255)
_NEBULA_CORE = (235, 215, 255)
# Floor-level effects sit above the room floor (order 0) and below entity depth buckets (order 60+).
_FLOOR_ORDER = 2


def _sx(wx: float, wy: float, shake) -> float:
    """Screen x of a world point. Same projection as utils.to_iso, on floats."""
    return (wx - wy) * utils.ISO_SCALE_X + utils.VIEW_W / 2 + shake.x


def _sy(wx: float, wy: float, shake) -> float:
    """Screen y of a world point. Same projection as utils.to_iso, on floats."""
    return (wx + wy) * utils.ISO_SCALE_Y + utils.VIEW_H / 2 + shake.y


class _FlareFx:
    def __init__(self, fan, edges, units):
        self.fan = fan  # FLARE_SEGMENTS triangles that fill the sector
        self.edges = edges  # two radial edges, then one edge per arc segment
        self.units = units  # unit vectors along the arc, from the sweep start to its end
        self.px = [0.0] * len(units)  # screen x of each arc point
        self.py = [0.0] * len(units)
        self.key_x = None  # shake offset the geometry was last written for
        self.key_y = None
        self.fill_op = None
        self.edge_op = None
        self.shapes = list(fan) + list(edges)


class _CloudFx:
    def __init__(self, fill, ring, core):
        self.fill = fill
        self.ring = ring
        self.core = core
        self.shapes = [fill, ring, core]
        self.key_x = None
        self.key_y = None
        self.ops = None  # last (fill, ring, core) opacities written


class ArenaEventFx:
    """Draws the sector and cloud for the running event. Meteor and beam drawing stay in visuals.py."""

    def __init__(self, batch, group_cache):
        self.batch = batch
        self.group = group_cache.get(_FLOOR_ORDER)
        self._handles: dict[int, object] = {}

    def sync(self, ev, shake) -> None:
        if ev.kind == events.EVENT_FLARE:
            fx = self._handles.get(id(ev))
            if fx is None:
                fx = self._handles[id(ev)] = self._build_flare(ev)
            self._sync_flare(ev, fx, shake)
        elif ev.kind == events.EVENT_NEBULA:
            fx = self._handles.get(id(ev))
            if fx is None:
                fx = self._handles[id(ev)] = self._build_cloud()
            self._sync_cloud(ev, fx, shake)

    def drop(self, ev) -> None:
        fx = self._handles.pop(id(ev), None)
        if fx is not None:
            for shape in fx.shapes:
                shape.delete()

    # Flare sector

    def _build_flare(self, ev) -> _FlareFx:
        fan = [
            shapes.Triangle(0, 0, 0, 0, 0, 0, color=_FLARE_FILL, batch=self.batch, group=self.group)
            for _ in range(FLARE_SEGMENTS)
        ]
        edges = [
            shapes.Line(0, 0, 0, 0, thickness=2, color=_FLARE_EDGE, batch=self.batch, group=self.group)
            for _ in range(FLARE_SEGMENTS + 2)
        ]
        units = []
        for i in range(FLARE_SEGMENTS + 1):
            ang = ev.angle_start + (ev.angle_end - ev.angle_start) * i / FLARE_SEGMENTS
            units.append((math.cos(ang), math.sin(ang)))
        return _FlareFx(fan, edges, units)

    def _sync_flare(self, ev, fx: _FlareFx, shake) -> None:
        # The sector is fixed in the world, so its geometry only changes when the screen shakes.
        if shake.x != fx.key_x or shake.y != fx.key_y:
            fx.key_x, fx.key_y = shake.x, shake.y
            self._write_flare_geometry(ev, fx, shake)

        warn = float(config.EVENT_FLARE_WARN)
        if ev.t < warn:
            # The sector fills in over the warning, so it reads as a countdown.
            prog = 0.0 if events.reduce_motion() else min(1.0, ev.t / warn)
            fill_op, edge_op = int(55 + 60 * prog), 170
        else:
            fill_op, edge_op = 34, 120  # the beam is sweeping: keep the sector faint underneath
        if fill_op != fx.fill_op:
            fx.fill_op = fill_op
            for tri in fx.fan:
                tri.opacity = fill_op
        if edge_op != fx.edge_op:
            fx.edge_op = edge_op
            for seg in fx.edges:
                seg.opacity = edge_op

    def _write_flare_geometry(self, ev, fx: _FlareFx, shake) -> None:
        reach = float(ev.reach)
        cx = _sx(0.0, 0.0, shake)
        cy = _sy(0.0, 0.0, shake)
        last = len(fx.units) - 1
        for i, (ux, uy) in enumerate(fx.units):
            wx = ux * reach
            wy = uy * reach
            fx.px[i] = _sx(wx, wy, shake)
            fx.py[i] = _sy(wx, wy, shake)

        # Triangle vertices are absolute: the anchor is the centre, the other two are arc points.
        for i, tri in enumerate(fx.fan):
            tri.x, tri.y = cx, cy
            tri.x2, tri.y2 = fx.px[i], fx.py[i]
            tri.x3, tri.y3 = fx.px[i + 1], fx.py[i + 1]

        e = fx.edges
        e[0].x, e[0].y, e[0].x2, e[0].y2 = cx, cy, fx.px[0], fx.py[0]
        e[1].x, e[1].y, e[1].x2, e[1].y2 = cx, cy, fx.px[last], fx.py[last]
        for i in range(last):
            seg = e[2 + i]
            seg.x, seg.y, seg.x2, seg.y2 = fx.px[i], fx.py[i], fx.px[i + 1], fx.py[i + 1]

    # Nebula cloud

    def _build_cloud(self) -> _CloudFx:
        radius = float(config.EVENT_NEBULA_RADIUS)
        # Segment counts are kept low: a pyglet opacity write rebuilds the colour buffer, which scales with vertices.
        fill = shapes.Circle(0, 0, radius, segments=48, color=_NEBULA_FILL, batch=self.batch, group=self.group)
        ring = shapes.Arc(0, 0, radius, segments=48, thickness=3, color=_NEBULA_EDGE, batch=self.batch, group=self.group)
        core = shapes.Circle(0, 0, radius * 0.3, segments=24, color=_NEBULA_CORE, batch=self.batch, group=self.group)
        return _CloudFx(fill, ring, core)

    def _sync_cloud(self, ev, fx: _CloudFx, shake) -> None:
        if shake.x != fx.key_x or shake.y != fx.key_y:
            fx.key_x, fx.key_y = shake.x, shake.y
            x = _sx(ev.center.x, ev.center.y, shake)
            y = _sy(ev.center.x, ev.center.y, shake)
            for shape in fx.shapes:
                shape.x = x
                shape.y = y
        still = events.reduce_motion()
        warn = float(config.EVENT_NEBULA_WARN)
        if ev.t < warn:
            # Warning: the outline and a faint body appear before the cloud starts shielding.
            prog = 0.0 if still else min(1.0, ev.t / warn)
            ops = (int(22 + 26 * prog), 110, 0)
        else:
            # Pulse in eighths: opacity is only rewritten when a step changes, not every frame.
            pulse = 0.5 if still else round((0.5 + 0.5 * math.sin((ev.t - warn) * 2.6)) * 8) / 8
            ops = (int(44 + 30 * pulse), int(150 + 70 * pulse), int(70 + 70 * pulse))
        if ops != fx.ops:
            fx.ops = ops
            fx.fill.opacity, fx.ring.opacity, fx.core.opacity = ops
