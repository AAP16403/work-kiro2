"""Soft additive glows: one radial texture built once, a quad bank that draws them, and the dash afterimage.

``QuadBank`` holds a fixed number of textured quads in one pyglet vertex list. Callers edit per-quad values
in Python lists, and ``flush`` copies them to the GPU once per frame. Editing a single pyglet sprite
costs a GPU buffer update each time, so a bank is much cheaper once more than a few dozen glows move.
A quad with zero scale is degenerate and draws nothing.

``GlowPool`` sits on a bank. Its glows are keyed by owner, so a glow keeps its quad while the owner is
emitted each frame. A quad that is not emitted in a frame is hidden and returned to the free list.
The pool never uses more than ``cap`` quads: once it is full, ``emit`` returns False and the glow is skipped.
"""

from __future__ import annotations

import ctypes
import math
from array import array

import pyglet
from pyglet.gl import GL_ONE, GL_SRC_ALPHA, GL_TRIANGLES
from pyglet.graphics import Group
from pyglet.sprite import SpriteGroup, get_default_shader

from utils import Vec2, to_iso

GLOW_TEXTURE_SIZE = 64

_glow_texture = None
_quad_program = None


def glow_texture():
    """Return the shared radial glow texture. It is built on first use and needs a GL context."""
    global _glow_texture
    if _glow_texture is None:
        _glow_texture = _build_glow_texture(GLOW_TEXTURE_SIZE)
    return _glow_texture


def _build_glow_texture(size: int):
    """White RGBA disc whose alpha falls off smoothly from the centre to the edge."""
    half = (size - 1) * 0.5
    data = bytearray(size * size * 4)
    idx = 0
    for y in range(size):
        dy = (y - half) / half
        for x in range(size):
            dx = (x - half) / half
            r = math.sqrt(dx * dx + dy * dy)
            alpha = 0.0 if r >= 1.0 else (1.0 - r) ** 1.8
            data[idx] = 255
            data[idx + 1] = 255
            data[idx + 2] = 255
            data[idx + 3] = int(alpha * 255.0)
            idx += 4
    texture = pyglet.image.ImageData(size, size, "RGBA", bytes(data)).get_texture()
    texture.anchor_x = size // 2
    texture.anchor_y = size // 2
    return texture


def _quad_shader():
    """The sprite shader, compiled once. Pyglet builds a new program on every call, so share this one."""
    global _quad_program
    if _quad_program is None:
        _quad_program = get_default_shader()
    return _quad_program


class QuadBank:
    """Fixed-capacity bank of textured, additive quads drawn through one vertex list.

    Slots are numbered 0 to capacity - 1. ``place`` moves a slot, ``style`` sets its size, rotation and
    colour, and ``hide`` makes it draw nothing. Every edit only changes Python lists. ``flush`` copies the
    used part of those lists to the GPU, so the work is one upload per frame however many quads moved.
    """

    def __init__(self, batch, capacity: int, order: int, texture=None) -> None:
        self._capacity = max(1, int(capacity))
        tex = texture if texture is not None else glow_texture()
        self._texture = tex
        self._program = _quad_shader()
        self._group = SpriteGroup(tex, GL_SRC_ALPHA, GL_ONE, self._program, parent=Group(order=int(order)))

        x1 = -float(tex.anchor_x)
        x2 = x1 + float(tex.width)
        y1 = -float(tex.anchor_y)
        y2 = y1 + float(tex.height)
        corners = (x1, y1, 0.0, x2, y1, 0.0, x2, y2, 0.0, x1, y2, 0.0)
        cap = self._capacity
        indices = []
        for q in range(cap):
            b = 4 * q
            indices.extend((b, b + 1, b + 2, b, b + 2, b + 3))

        self._translate = [0.0] * (12 * cap)
        self._scale = [0.0] * (8 * cap)
        self._rotation = [0.0] * (4 * cap)
        self._colors = [0] * (16 * cap)
        self._style = [None] * cap   # last (dx, dy, rotation, rgba) written to each slot
        self._high = 0               # slots below this index may be non-zero, so flush copies them
        self._style_dirty = False

        self._vertex_list = self._program.vertex_list_indexed(
            4 * cap, GL_TRIANGLES, indices, batch, self._group,
            position=("f", list(corners) * cap),
            colors=("Bn", self._colors),
            translate=("f", self._translate),
            scale=("f", self._scale),
            rotation=("f", self._rotation),
            tex_coords=("f", list(tex.tex_coords) * cap),
        )

    @property
    def capacity(self) -> int:
        return self._capacity

    def place(self, slot: int, x: float, y: float) -> None:
        o = 12 * slot
        self._translate[o:o + 12] = (x, y, 0.0, x, y, 0.0, x, y, 0.0, x, y, 0.0)
        if slot >= self._high:
            self._high = slot + 1

    def style(self, slot: int, dx: float, dy: float, rotation: float, rgba) -> None:
        """Set a slot's scale (``dx``, ``dy``, where 1.0 is the texture size), rotation in degrees and RGBA colour."""
        dx = float(dx)
        dy = float(dy)
        rotation = float(rotation)
        rgba = (int(rgba[0]), int(rgba[1]), int(rgba[2]), int(rgba[3]))
        key = (dx, dy, rotation, rgba)
        if self._style[slot] == key:
            return
        self._style[slot] = key
        o2 = 8 * slot
        self._scale[o2:o2 + 8] = (dx, dy, dx, dy, dx, dy, dx, dy)
        o1 = 4 * slot
        self._rotation[o1:o1 + 4] = (rotation, rotation, rotation, rotation)
        o4 = 16 * slot
        self._colors[o4:o4 + 16] = rgba * 4
        self._style_dirty = True
        if slot >= self._high:
            self._high = slot + 1

    def hide(self, slot: int) -> None:
        self.style(slot, 0.0, 0.0, 0.0, (0, 0, 0, 0))

    def flush(self) -> None:
        """Copy the used slots to the GPU. Call once per frame, after the last edit."""
        n = self._high
        if n <= 0:
            return
        _copy_attribute(self._vertex_list, "translate", self._translate, 12, n, "f")
        if self._style_dirty:
            _copy_attribute(self._vertex_list, "scale", self._scale, 8, n, "f")
            _copy_attribute(self._vertex_list, "rotation", self._rotation, 4, n, "f")
            _copy_attribute(self._vertex_list, "colors", self._colors, 16, n, "B")
            self._style_dirty = False


def _copy_attribute(vertex_list, name: str, values: list, per_slot: int, slots: int, typecode: str) -> None:
    """Write the first ``slots`` slots of one attribute. A bulk array copy is much faster than ctypes item writes.

    Reading the attribute marks its region for upload, which is what makes the copy reach the GPU.
    """
    count = per_slot * slots
    data = array(typecode, values[:count])
    region = getattr(vertex_list, name)
    ctypes.memmove(ctypes.addressof(region), data.buffer_info()[0], data.itemsize * count)


class GlowPool:
    """Keyed glow pool on top of a QuadBank (see the module docstring)."""

    def __init__(self, batch, cap: int = 96, order: int = 14500) -> None:
        self._bank = QuadBank(batch, cap, order)
        self._cap = self._bank.capacity
        self._free: list[int] = []
        self._next_slot = 0
        self._shown: dict = {}    # key -> slot shown last frame
        self._current: dict = {}  # key -> slot claimed this frame

    @property
    def cap(self) -> int:
        return self._cap

    @property
    def sprite_count(self) -> int:
        """Quads handed out so far. This never exceeds ``cap``."""
        return self._next_slot

    @property
    def active_count(self) -> int:
        """Glows emitted in the current frame."""
        return len(self._current)

    def visible_count(self) -> int:
        """Glows shown after the last ``end_frame``."""
        return len(self._shown)

    def begin_frame(self) -> None:
        self._current = {}

    def emit(self, key, x: float, y: float, radius: float, color, opacity: int = 255,
             rotation: float = 0.0, stretch: float = 1.0) -> bool:
        """Show the glow for ``key`` centred on (x, y). ``radius`` is in px.

        Returns False when the pool is full and the key has no quad yet; the glow is then skipped.
        """
        slot = self._current.get(key)
        if slot is None:
            slot = self._shown.pop(key, None)
            if slot is None:
                if self._free:
                    slot = self._free.pop()
                elif self._next_slot < self._cap:
                    slot = self._next_slot
                    self._next_slot += 1
                elif self._shown:
                    # Full: borrow the quad of a last-frame glow that no one has claimed yet this frame. If that
                    # owner shows up later in the frame, it gets another quad, or is skipped when the pool is full.
                    _stale_key, slot = self._shown.popitem()
                else:
                    return False
            self._current[key] = slot

        diameter = 2.0 * float(radius) / GLOW_TEXTURE_SIZE
        rgba = (int(color[0]), int(color[1]), int(color[2]), max(0, min(255, int(opacity))))
        self._bank.place(slot, x, y)
        self._bank.style(slot, diameter * float(stretch), diameter, rotation, rgba)
        return True

    def end_frame(self) -> None:
        """Hide the glows whose keys were not emitted this frame, then upload. Call once per frame."""
        for slot in self._shown.values():
            self._bank.hide(slot)
            self._free.append(slot)
        self._shown = self._current
        self._current = {}
        self._bank.flush()


def projectile_glow(proj) -> tuple[tuple[int, int, int], float, int]:
    """Glow colour, radius and opacity for a projectile head. Colours mirror Visuals.ensure_projectile."""
    ptype = getattr(proj, "projectile_type", "bullet")
    is_enemy = str(getattr(proj, "owner", "player")) == "enemy"
    if bool(getattr(proj, "is_crit", False)):
        return (255, 205, 50), 13.0, 150
    if ptype == "bomb":
        return (255, 145, 90), 12.0, 120
    if ptype == "railgun":
        return (120, 210, 255), 14.0, 150
    if ptype == "flak":
        return (255, 150, 60), 11.0, 130
    if ptype == "missile":
        return ((255, 120, 120) if is_enemy else (255, 150, 100)), 11.0, 120
    if ptype == "plasma":
        return ((255, 90, 180) if is_enemy else (170, 120, 255)), 11.0, 120
    if ptype == "spread":
        return ((255, 110, 90) if is_enemy else (255, 220, 120)), 9.0, 110
    return ((255, 90, 90) if is_enemy else (255, 245, 190)), 9.0, 110


class DashAfterimage:
    """A streak of fading glows left behind a dash.

    ``record`` takes one sample every ``SAMPLE_S`` while the dash is active. Each sample fades out over
    ``FADE_S`` seconds and is then dropped. Times come from the game clock, so a paused game freezes the streak.
    """

    SAMPLE_S = 0.03
    FADE_S = 0.30
    MAX_SAMPLES = 10

    def __init__(self) -> None:
        self._samples: list[tuple[float, float, float, float, float, tuple[int, int, int]]] = []
        self._last_t = -1e9

    @property
    def sample_count(self) -> int:
        return len(self._samples)

    def record(self, t: float, pos: Vec2, direction: Vec2, active: bool, color) -> None:
        """Keep the samples fresh. Call once per frame with the player's current state."""
        self._samples = [s for s in self._samples if t - s[0] < self.FADE_S]
        if not active or t - self._last_t < self.SAMPLE_S:
            return
        self._last_t = t
        # Store the world position and the screen-space direction (a delta, so the view offset cancels);
        # the screen position is taken at emit time so the streak follows the shake.
        origin = to_iso(Vec2(0.0, 0.0), Vec2(0.0, 0.0))
        tip = to_iso(direction, Vec2(0.0, 0.0))
        dx, dy = tip[0] - origin[0], tip[1] - origin[1]
        self._samples.append((t, float(pos.x), float(pos.y), float(dx), float(dy), tuple(color)))
        if len(self._samples) > self.MAX_SAMPLES:
            del self._samples[0]

    def emit(self, pool: GlowPool, t: float, shake: Vec2, thickness: float = 9.0, streak_px: float = 60.0) -> int:
        """Emit the live samples into the pool, newest first. Returns how many glows were emitted.

        Each glow is an ellipse whose front edge sits on its sample and whose tail stretches back along the
        dash direction. It shrinks and fades as it ages.
        """
        emitted = 0
        for stamp, wx, wy, dx, dy, color in reversed(self._samples):
            fade = 1.0 - (t - stamp) / self.FADE_S
            if fade <= 0.0:
                continue
            sx, sy = to_iso(Vec2(wx, wy), shake)
            norm = math.hypot(dx, dy)
            if norm < 1e-6:
                ux, uy = 1.0, 0.0
            else:
                ux, uy = dx / norm, dy / norm
            rotation = -math.degrees(math.atan2(uy, ux))
            length = streak_px * (0.4 + 0.6 * fade)
            thick = thickness * (0.5 + 0.5 * fade)
            # Centre the ellipse half a streak behind the sample, so the front edge sits on the sample.
            cx = sx - ux * length * 0.5
            cy = sy - uy * length * 0.5
            opacity = int(210.0 * (fade ** 1.5))
            if not pool.emit(("dash", stamp), cx, cy, thick, color, opacity, rotation=rotation, stretch=(length * 0.5) / thick):
                break
            emitted += 1
        return emitted
