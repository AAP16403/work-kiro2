"""Afterburn drawing: a pool of ground discs that shows the segments of an afterburn.AfterburnTrail.

Each segment slot holds two discs on the iso ground: a soft warm glow (AFTERBURN_HIT_RADIUS, the same reach the
damage uses) and a dark scorch core (AFTERBURN_CORE_RADIUS) on top. A disc is RIM triangles, each running from the
centre to one edge of the rim. The centre carries the alpha and the rim is clear, so the disc fades to nothing at its
edge. Both layers take the run skin's trail colour, the core darkened by AFTERBURN_CORE_SHADE.

Triangles, not fans: pyglet draws every vertex list of one group in one call, so a fan's hub would join its
neighbours' rims. Each triangle is independent, so the discs can share one vertex list each.

The vertex lists are built once in the batch and reused. A frame writes positions and alpha into them in place,
so it creates no shapes or vertex lists. The pool draws in its own Group at AFTERBURN_LAYER_ORDER, so it sits above
the room floor and under the entities.

Fade is linear in age over AFTERBURN_LIFE_SECONDS, in every mode. The glow also flickers, unless REDUCE_MOTION is on.
The flicker phase comes from each segment's drop time, not from a random source, so the frames repeat for a seed.

update() takes the screen origin of the world (the same as utils.to_iso applied to the origin, shake included) and
projects each disc with the iso constants. A world circle projects to an ellipse, so the disc is drawn as one.
"""

from __future__ import annotations

import math

from pyglet import shapes
from pyglet.gl import GL_TRIANGLES

import config
import motion

_RIM = 12                 # rim edges per disc; each edge is one triangle with the centre
_COUNT = 3 * _RIM         # vertices per disc: three per triangle
# Screen offset of the rim point at angle k: a world circle of radius r gives (r * iso_x * UX[k], r * iso_y * UY[k]).
# With cos and sin of the angle, the iso map sends (r cos, r sin) to ((cos - sin) * iso_x, (cos + sin) * iso_y) * r.
_UX = [math.cos(math.tau * k / _RIM) - math.sin(math.tau * k / _RIM) for k in range(_RIM + 1)]
_UY = [math.cos(math.tau * k / _RIM) + math.sin(math.tau * k / _RIM) for k in range(_RIM + 1)]
_PHASE_STEP = 7.0         # flicker phase per second of a segment's drop time, so neighbours do not pulse together


def scorch_rgb(rgb, shade: float | None = None) -> tuple:
    """The dark scorch core colour: the trail colour scaled by AFTERBURN_CORE_SHADE (or ``shade``)."""
    k = float(config.AFTERBURN_CORE_SHADE if shade is None else shade)
    return tuple(max(0, min(255, int(c * k))) for c in rgb[:3])


class _Slot:
    """One segment slot's two discs. ``cx, cy`` is the centre last placed on screen, and ``glow_a, core_a`` the alpha
    last written. A write happens only when one of them changes, so a still, steady frame writes nothing.

    ``glow_pos`` and ``core_pos`` are the position arrays the discs are placed from. The alpha lives only in the
    vertex lists, written in place.
    """

    __slots__ = (
        "glow_vl", "glow_pos", "core_vl", "core_pos", "shown",
        "cx", "cy", "glow_a", "core_a",
    )


class AfterburnPool:
    """A fixed set of ground discs, one pair per segment slot. update() places and fades them each frame.

    ``batch`` holds the vertex lists. ``group`` is the pyglet Group they draw in (its order is the layer). ``colour``
    is the trail colour (visuals.afterburn_color), or None for AFTERBURN_COLOR. ``slots`` defaults to
    AFTERBURN_MAX_SEGMENTS, the same count the trail holds.
    """

    def __init__(self, batch, group=None, colour=None, slots: int | None = None):
        n = int(config.AFTERBURN_MAX_SEGMENTS if slots is None else slots)
        glow_rgb = tuple(int(c) for c in (config.AFTERBURN_COLOR if colour is None else colour)[:3])
        self._glow_rgb = glow_rgb
        self._core_rgb = scorch_rgb(glow_rgb)
        # A probe shape gives the program and the blend group pyglet uses for shapes (SRC_ALPHA blending).
        probe = shapes.Circle(0, 0, 1.0, color=glow_rgb, batch=None, group=group)
        self._program = probe.program
        self._group = probe.get_shape_group()
        probe.delete()
        self._batch = batch
        self._slots: list[_Slot] = []
        for _ in range(max(1, n)):
            slot = _Slot()
            slot.glow_vl, slot.glow_pos = self._make_disc(self._glow_rgb)
            slot.core_vl, slot.core_pos = self._make_disc(self._core_rgb)
            slot.shown = False
            slot.cx = None
            slot.cy = None
            slot.glow_a = 0
            slot.core_a = 0
            self._slots.append(slot)

    def _make_disc(self, rgb):
        """One disc's vertex list: its triangles in ``rgb`` with alpha 0 to start. Built once per slot.

        Returns the vertex list and the position array it is placed from.
        """
        pos = [0.0] * (2 * _COUNT)
        col = []
        r, g, b = rgb
        for _ in range(_COUNT):
            col.extend((r, g, b, 0))
        vl = self._program.vertex_list(
            _COUNT, GL_TRIANGLES, self._batch, self._group,
            position=("f", pos), colors=("Bn", col),
        )
        return vl, pos

    @property
    def size(self) -> int:
        return len(self._slots)

    @property
    def shown_count(self) -> int:
        """How many slots are drawn with alpha above zero this frame."""
        return sum(1 for slot in self._slots if slot.shown)

    @staticmethod
    def _place(pos, cx: float, cy: float, radius: float, iso_x: float, iso_y: float) -> None:
        """Fill one disc's positions. Triangle k is the centre, rim point k and rim point k + 1.

        The centre is repeated in every triangle, so each triangle is complete on its own.
        """
        rx = radius * iso_x
        ry = radius * iso_y
        for k in range(_RIM):
            base = 6 * k
            pos[base] = cx
            pos[base + 1] = cy
            pos[base + 2] = cx + rx * _UX[k]
            pos[base + 3] = cy + ry * _UY[k]
            pos[base + 4] = cx + rx * _UX[k + 1]
            pos[base + 5] = cy + ry * _UY[k + 1]

    @staticmethod
    def _set_alpha(vl, alpha: int) -> None:
        """Write the centre alpha into the vertex list: the first vertex of each triangle. The rim stays clear.

        Writing through the attribute's region touches only the alpha bytes, which is cheaper than copying the whole
        colour array each frame.
        """
        region = vl.colors
        for k in range(_RIM):
            region[12 * k + 3] = alpha

    @staticmethod
    def _hide(slot: _Slot) -> None:
        """Make both discs transparent. The vertex lists stay in the batch, and the positions are left as they are."""
        if slot.glow_a:
            AfterburnPool._set_alpha(slot.glow_vl, 0)
            slot.glow_a = 0
        if slot.core_a:
            AfterburnPool._set_alpha(slot.core_vl, 0)
            slot.core_a = 0
        slot.shown = False

    def update(self, now: float, trail, origin_x: float, origin_y: float) -> None:
        """Place and fade every live segment of ``trail`` at run time ``now``. Hides the rest.

        ``origin_x, origin_y`` is the screen point of the world origin for this frame (utils.to_iso of Vec2(0, 0), with
        the camera shake). With ENABLE_AFTERBURN False nothing is drawn.
        """
        if not config.ENABLE_AFTERBURN:
            self.reset()
            return
        now = float(now)
        trail.expire(now)
        life = float(config.AFTERBURN_LIFE_SECONDS)
        still = motion.reduced()
        flicker_hz = float(config.AFTERBURN_FLICKER_HZ)
        flicker_depth = float(config.AFTERBURN_FLICKER_DEPTH)
        glow_max = int(config.AFTERBURN_GLOW_OPACITY)
        core_max = int(config.AFTERBURN_CORE_OPACITY)
        glow_r = float(config.AFTERBURN_HIT_RADIUS)
        core_r = float(config.AFTERBURN_CORE_RADIUS)
        iso_x = float(config.ISO_SCALE_X)
        iso_y = float(config.ISO_SCALE_Y)
        ox = float(origin_x)
        oy = float(origin_y)
        segments = trail.segments
        slots = self._slots
        n = min(len(segments), len(slots))
        for k in range(n):
            seg = segments[k]
            slot = slots[k]
            if not seg.live:
                if slot.shown:
                    self._hide(slot)
                continue
            fade = 1.0 - (now - seg.t0) / life
            if fade < 0.0:
                fade = 0.0
            elif fade > 1.0:
                fade = 1.0
            if still:
                flick = 1.0
            else:
                wave = 0.5 + 0.5 * math.sin(math.tau * flicker_hz * now + seg.t0 * _PHASE_STEP)
                flick = 1.0 - flicker_depth * wave
            cx = ox + (seg.x - seg.y) * iso_x
            cy = oy + (seg.x + seg.y) * iso_y
            if cx != slot.cx or cy != slot.cy:  # the disc moved on screen (a shake, or a new drop): place it
                self._place(slot.glow_pos, cx, cy, glow_r, iso_x, iso_y)
                slot.glow_vl.position[:] = slot.glow_pos
                self._place(slot.core_pos, cx, cy, core_r, iso_x, iso_y)
                slot.core_vl.position[:] = slot.core_pos
                slot.cx = cx
                slot.cy = cy
            glow_a = int(glow_max * fade * flick)
            if glow_a != slot.glow_a:
                self._set_alpha(slot.glow_vl, glow_a)
                slot.glow_a = glow_a
            core_a = int(core_max * fade)
            if core_a != slot.core_a:
                self._set_alpha(slot.core_vl, core_a)
                slot.core_a = core_a
            slot.shown = True
        for k in range(n, len(slots)):
            if slots[k].shown:
                self._hide(slots[k])

    def reset(self) -> None:
        """Hide every disc at once, e.g. when a run ends or Afterburn is switched off."""
        for slot in self._slots:
            if slot.shown:
                self._hide(slot)
