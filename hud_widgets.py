"""In-run HUD widgets: the radial Ultra gauge, the weapon chip, the skin chip and the toast view.

ToastQueue and ultra_fraction are plain Python with no window, so tests call them directly.
Panels and chips are drawn with ui_theme's helpers. ui_theme and projectile_art are required, so a
missing module fails loudly instead of quietly drawing a different palette.
"""

import math
from collections import deque

import pyglet
from pyglet import shapes

import config
import ui_theme as _ui_theme
import projectile_art as _projectile_art
from menu import UI_FONT_BODY, UI_FONT_HEAD, UI_FONT_META


TOAST_SECONDS = 2.5          # a toast is on screen this long, fades included
TOAST_FADE_IN_S = 0.15
TOAST_FADE_OUT_S = 0.40
TOAST_MAX_PENDING = 8        # toasts waiting behind the one on screen; extra ones are dropped
RING_SEGMENTS = 48
RING_PULSE_HZ = 0.9          # full-charge pulse rate
RING_PULSE_MIN = 170         # opacity range of the full-charge pulse
RING_PULSE_MAX = 255

# HUD token names that differ from ui_theme's names.
_TOKEN_NAMES = {"BG": "BACKGROUND"}


# ----------------------------------------------------------------------
# Text and theme helpers
# ----------------------------------------------------------------------

def set_text(label, text: str) -> None:
    """Assign label text only when it changed (pyglet relayouts on every assignment)."""
    if label.text != text:
        label.text = text


def fit_text(label, text: str, max_w: float) -> None:
    """Set label text, trimmed with '...' so its width stays within max_w pixels."""
    label.text = text
    if max_w <= 0 or label.content_width <= max_w:
        return
    lo, hi = 0, len(text)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        label.text = text[:mid].rstrip() + "..."
        if label.content_width <= max_w:
            lo = mid
        else:
            hi = mid - 1
    label.text = text[:lo].rstrip() + "..."


def token(name: str, theme=None) -> tuple:
    """A colour token from ui_theme (or from ``theme`` when one is given)."""
    source = _ui_theme if theme is None else theme
    return tuple(getattr(source, _TOKEN_NAMES.get(name, name)))


def draw_panel(batch, x, y, w, h, color=None, theme=None) -> list:
    """Background panel from ui_theme.draw_panel; returns the shapes so the caller can delete them."""
    source = _ui_theme if theme is None else theme
    fill = token("PANEL", theme) if color is None else tuple(color)
    return list(source.draw_panel(batch, x, y, w, h, fill=fill))


def weapon_swatch(weapon) -> tuple:
    """Head colour of the weapon's projectile_art style, so the swatch matches the shot it fires."""
    style = _projectile_art.style_for(getattr(weapon, "name", ""), getattr(weapon, "projectile_type", "bullet"))
    return tuple(style.head)[:3]


def set_opacity(shape_list, value: int) -> None:
    for shp in shape_list:
        if shp.opacity != value:
            shp.opacity = value


# ----------------------------------------------------------------------
# Ultra charge gauge fraction
# ----------------------------------------------------------------------

def ultra_fraction(charges, max_charges) -> float:
    """Share of Ultra capacity held: 0 with no charge, 0.5 at half, 1.0 when full."""
    cap = int(max_charges)
    if cap <= 0:
        return 0.0
    return max(0.0, min(1.0, int(charges) / cap))


# ----------------------------------------------------------------------
# Toast queue (pure logic)
# ----------------------------------------------------------------------

class ToastQueue:
    """FIFO of toasts with one on screen at a time.

    push() queues a (title, subtitle) pair. tick(dt) ages the toast on screen; when its age
    reaches `duration` it is removed and the next queued toast starts, carrying over the extra
    time so spacing stays exact. alpha() is 0 at the start, rises over fade_in, holds, and falls
    to 0 over the last fade_out seconds.
    """

    def __init__(self, duration=TOAST_SECONDS, fade_in=TOAST_FADE_IN_S,
                 fade_out=TOAST_FADE_OUT_S, max_pending=TOAST_MAX_PENDING):
        self.duration = float(duration)
        self.fade_in = max(0.0, float(fade_in))
        self.fade_out = max(0.0, float(fade_out))
        self.max_pending = max(0, int(max_pending))
        self._pending = deque()
        self._current = None
        self._age = 0.0
        self.dropped = 0

    @property
    def current(self):
        """(title, subtitle) on screen now, or None."""
        return self._current

    @property
    def queued(self) -> int:
        return len(self._pending)

    @property
    def age(self) -> float:
        return self._age

    def push(self, title, subtitle="") -> bool:
        """Queue a toast. Returns False when the pending list is full and the toast is dropped."""
        item = (str(title), str(subtitle))
        if self._current is None:
            self._current = item
            self._age = 0.0
            return True
        if len(self._pending) >= self.max_pending:
            self.dropped += 1
            return False
        self._pending.append(item)
        return True

    def tick(self, dt: float) -> None:
        if self._current is None:
            return
        self._age += max(0.0, float(dt))
        while self._current is not None and self._age >= self.duration:
            self._age -= self.duration
            if self._pending:
                self._current = self._pending.popleft()
            else:
                self._current = None
                self._age = 0.0

    def alpha(self) -> float:
        if self._current is None:
            return 0.0
        t = self._age
        if self.fade_in > 0.0 and t < self.fade_in:
            return max(0.0, t / self.fade_in)
        left = self.duration - t
        if self.fade_out > 0.0 and left < self.fade_out:
            return max(0.0, left / self.fade_out)
        return 1.0

    def clear(self) -> None:
        self._pending.clear()
        self._current = None
        self._age = 0.0


# ----------------------------------------------------------------------
# Drawn widgets
# ----------------------------------------------------------------------

class RadialGauge:
    """Ring that fills with Ultra charge, with the charge count in its centre.

    The arc is rebuilt only when the fraction changes (pyglet regenerates an Arc's vertices on
    every angle write). The full-charge pulse only changes opacity, and stays still when
    reduce_motion is set.
    """

    def __init__(self, batch, make_label, color=None, theme=None):
        self._batch = batch
        self._theme = theme
        self._color = tuple(config.ULTRA_BEAM_COLOR) if color is None else tuple(color)
        self._track = None
        self._fill = None
        self._geom = None
        self._frac = -1.0
        self._pulse = -1
        self._count = make_label("", UI_FONT_HEAD, 14, ax="center", ay="center",
                                 color=(*token("TEXT", theme), 255), batch=batch)
        self._caption = make_label("ULTRA", UI_FONT_META, 9, ax="left", ay="center",
                                   color=(*self._color, 235), batch=batch)

    @property
    def fraction(self) -> float:
        return max(0.0, self._frac)

    @property
    def count_text(self) -> str:
        return self._count.text

    def place(self, cx: float, cy: float, radius: float, thickness: float, caption_x: float) -> None:
        """Build the ring at a new size and position."""
        for shp in (self._track, self._fill):
            if shp is not None:
                shp.delete()
        track_color = (*token("MUTED", self._theme), 60)
        self._track = shapes.Arc(
            cx, cy, radius, segments=RING_SEGMENTS, angle=360.0, thickness=thickness,
            color=track_color, batch=self._batch,
        )
        self._fill = shapes.Arc(
            cx, cy, radius, segments=RING_SEGMENTS, angle=0.0, start_angle=90.0,
            thickness=thickness, color=self._color, batch=self._batch,
        )
        self._fill.visible = False
        self._frac = -1.0  # force the arc to be re-angled for the new geometry
        self._pulse = -1
        self._geom = (cx, cy, radius)
        self._count.x = round(cx)
        self._count.y = round(cy)
        self._caption.x = round(caption_x)
        self._caption.y = round(cy)

    def update(self, charges, max_charges) -> None:
        cap = max(0, int(max_charges))
        held = max(0, int(charges))
        frac = ultra_fraction(held, cap)
        if self._fill is not None and frac != self._frac:
            self._frac = frac
            self._fill.angle = 360.0 * frac
            self._fill.visible = frac > 0.0
        set_text(self._count, f"{held}/{cap}")

    def animate(self, t: float, reduce_motion: bool = False) -> None:
        """Gentle opacity pulse while full; a steady ring when reduce_motion is set."""
        if self._fill is None:
            return
        if reduce_motion or self._frac < 1.0:
            target = RING_PULSE_MAX
        else:
            wave = 0.5 + 0.5 * math.sin(2.0 * math.pi * RING_PULSE_HZ * float(t))
            target = int(round(RING_PULSE_MIN + (RING_PULSE_MAX - RING_PULSE_MIN) * wave))
        if target != self._pulse:
            self._pulse = target
            self._fill.opacity = target


class Chip:
    """Small rounded-rect style chip: a ui_theme panel with one fitted label inside."""

    def __init__(self, batch, make_label, fill=None, label_color=None, theme=None, frame_batch=None):
        self._batch = batch
        self._frame_batch = frame_batch if frame_batch is not None else batch
        self._theme = theme
        self._fill = fill
        self._frame = []
        self._geom = None
        self._text = ""
        self._fit_key = None
        self._label = make_label("", UI_FONT_META, 9, ax="left", ay="center",
                                 color=(*(label_color or token("ACCENT", theme)), 255), batch=batch)

    @property
    def text(self) -> str:
        return self._text

    def place(self, x: float, y: float, w: float, h: float, pad: float) -> None:
        for shp in self._frame:
            shp.delete()
        self._frame = draw_panel(self._frame_batch, x, y, w, h, color=self._fill or token("BG", self._theme), theme=self._theme)
        set_opacity(self._frame, 235)
        self._geom = (x, y, w, h, pad)
        self._label.x = round(x + pad)
        self._label.y = round(y + h / 2.0)
        self._fit_key = None
        self._fit()

    def set_text(self, text: str) -> None:
        self._text = str(text)
        self._fit()

    def width_for(self, max_w: float, pad: float, min_w: float = 0.0) -> float:
        """Chip width that holds the whole text with `pad` on each side, kept within [min_w, max_w]."""
        self._label.text = self._text.upper()  # measure the untrimmed text
        self._fit_key = None
        natural = self._label.content_width + 2.0 * float(pad)
        return max(float(min_w), min(float(max_w), natural))

    def _fit(self) -> None:
        if self._geom is None:
            return
        x, y, w, h, pad = self._geom
        key = (self._text, w - pad * 2)
        if key == self._fit_key:
            return  # re-assigning label text relayouts it, so only fit when the inputs change
        self._fit_key = key
        fit_text(self._label, self._text.upper(), w - pad * 2)


class WeaponChip:
    """Weapon name with a colour swatch on the left and the crit chance on the right."""

    def __init__(self, batch, make_label, theme=None, frame_batch=None):
        self._batch = batch
        self._frame_batch = frame_batch if frame_batch is not None else batch
        self._theme = theme
        self._frame = []
        self._swatch = shapes.Rectangle(0, 0, 1, 1, color=token("ACCENT", theme), batch=batch)
        self._name = make_label("", UI_FONT_META, 9, ax="left", ay="center",
                                color=(*token("TEXT", theme), 240), batch=batch)
        self._crit = make_label("", UI_FONT_META, 9, ax="right", ay="center",
                                color=(*token("MUTED", theme), 240), batch=batch)
        self._geom = None
        self._name_text = ""
        self._fit_key = None

    @property
    def name_text(self) -> str:
        return self._name_text

    @property
    def crit_text(self) -> str:
        return self._crit.text

    @property
    def swatch_color(self) -> tuple:
        return (self._swatch.color[0], self._swatch.color[1], self._swatch.color[2])

    def place(self, x: float, y: float, w: float, h: float, pad: float, swatch: float, gap: float) -> None:
        for shp in self._frame:
            shp.delete()
        self._frame = draw_panel(self._frame_batch, x, y, w, h, color=token("BG", self._theme), theme=self._theme)
        set_opacity(self._frame, 235)
        sw = max(1.0, float(swatch))
        self._swatch.x = x + pad
        self._swatch.y = y + (h - sw) / 2.0
        self._swatch.width = sw
        self._swatch.height = sw
        self._geom = (x, y, w, h, pad, sw, gap)
        self._crit.x = round(x + w - pad)
        self._crit.y = round(y + h / 2.0)
        self._name.y = round(y + h / 2.0)
        self._name.x = round(x + pad + sw + gap)
        self._fit_key = None
        self._fit_name()

    def set_weapon(self, name_text: str, crit_text: str, swatch_color) -> None:
        """Show the weapon. A None or empty name clears the chip."""
        self._name_text = str(name_text)
        set_text(self._crit, str(crit_text))
        if swatch_color is not None:
            color = tuple(swatch_color)[:3]
            if tuple(self._swatch.color[:3]) != color:
                self._swatch.color = color
        self._fit_name()

    def _fit_name(self) -> None:
        if self._geom is None:
            return
        x, y, w, h, pad, sw, gap = self._geom
        crit_room = self._crit.content_width if self._crit.text else 0.0
        name_max = w - (pad + sw + gap) - pad - crit_room - gap
        key = (self._name_text, name_max)
        if key == self._fit_key:
            return
        self._fit_key = key
        fit_text(self._name, self._name_text, name_max)


class ToastView:
    """Draws the toast on screen: a panel holding the title, a subtitle and the queue count."""

    def __init__(self, batch, make_label, theme=None, frame_batch=None):
        self._batch = batch
        self._frame_batch = frame_batch if frame_batch is not None else batch
        self._theme = theme
        self._frame = []
        self._geom = None
        self._title_text = ""
        self._sub_text = ""
        self._title = make_label("", UI_FONT_BODY, 12, ax="left", ay="baseline",
                                 color=(*token("TEXT", theme), 255), batch=batch)
        self._sub = make_label("", UI_FONT_META, 9, ax="left", ay="baseline",
                               color=(*token("ACCENT", theme), 255), batch=batch)
        self._count = make_label("", UI_FONT_META, 9, ax="right", ay="baseline",
                                 color=(*token("MUTED", theme), 255), batch=batch)
        self._visible = False
        self._alpha = 0.0
        self._applied = -1.0  # last alpha written to the shapes; -1 forces the next write
        self._fit_key = None

    @property
    def visible(self) -> bool:
        return self._visible

    @property
    def title_text(self) -> str:
        return self._title.text

    @property
    def subtitle_text(self) -> str:
        return self._sub.text

    def place(self, x: float, y: float, w: float, h: float, pad: float,
              title_y: float, sub_y: float, edge: float = 2.0) -> None:
        for shp in self._frame:
            shp.delete()
        edge = max(0.0, float(edge))
        edge_shapes = draw_panel(self._frame_batch, x - edge, y - edge, w + 2 * edge, h + 2 * edge,
                                 color=token("ACCENT", self._theme), theme=self._theme)
        fill_shapes = draw_panel(self._frame_batch, x, y, w, h, color=token("PANEL", self._theme), theme=self._theme)
        self._frame = edge_shapes + fill_shapes
        self._geom = (x, y, w, h, pad)
        self._title.x = round(x + pad)
        self._title.y = round(y + title_y)
        self._sub.x = round(x + pad)
        self._sub.y = round(y + sub_y)
        self._count.x = round(x + w - pad)
        self._count.y = round(y + title_y)
        self._fit_key = None
        self._refit()
        self._applied = -1.0  # the new shapes need their opacity written
        self._apply_alpha()

    def show(self, title: str, subtitle: str, queued: int, alpha: float) -> None:
        self._title_text = str(title)
        self._sub_text = str(subtitle)
        self._visible = True
        set_text(self._count, f"+{int(queued)} MORE" if queued > 0 else "")
        self._refit()
        self._alpha = float(alpha)
        self._apply_alpha()

    def hide(self) -> None:
        self._visible = False
        self._apply_alpha()

    def _apply_alpha(self) -> None:
        a = max(0.0, min(1.0, self._alpha)) if self._visible else 0.0
        if a == self._applied:
            return
        self._applied = a
        set_opacity(self._frame, int(round(235 * a)))
        for lbl in (self._title, self._sub, self._count):
            lbl.opacity = int(round(255 * a))

    def _refit(self) -> None:
        if self._geom is None:
            return
        x, y, w, h, pad = self._geom
        count_room = self._count.content_width + pad if self._count.text else 0.0
        key = (self._title_text, self._sub_text, w, count_room)
        if key == self._fit_key:
            return
        self._fit_key = key
        fit_text(self._title, self._title_text, w - pad * 2 - count_room)
        fit_text(self._sub, self._sub_text, w - pad * 2)
