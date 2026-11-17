"""Skin preview: one skin's character, drawn the way the run draws it, for the Hangar cards and any other screen.

CharacterPreview is the helper the Hangar uses. It draws the same look Visuals draws in a run: PlayerArt
when config.USE_PLAYER_ART is on (the pod robot), and the legacy ship when it is off. The palette goes
through skin_apply.complete_palette, the same path read_run_skin takes, so a card and the next run show one
palette.

SkinPreview / draw_skin_preview draw the legacy ship with pyglet shapes, facing right. ``size`` 1.0 matches
the in-run legacy ship. Keep that geometry in step with Visuals.make_player. CharacterPreview uses it for
the legacy look.
"""

from __future__ import annotations

from pyglet import shapes

import config
from player import Player
from player_art import PlayerArt
from skin_apply import aura_outer, complete_palette
from utils import Vec2, to_iso

_WING = ((8, 0), (-12, 18), (-16, 18), (-10, 6), (-18, 8), (-18, -8), (-10, -6), (-16, -18), (-12, -18))
_BODY = ((18, 0), (-4, 10), (-12, 8), (-8, 0), (-12, -8), (-4, -10))
_COCKPIT = ((10, 0), (2, 4), (-6, 3), (-6, -3), (2, -4))
_WING_COLOR = (15, 22, 36)
_BARREL_COLOR = (230, 230, 240)


def _bar(x1, y1, x2, y2, half):
    """Axis-aligned bar from (x1, y1) to (x2, y2) with half-thickness ``half``."""
    return ((x1, y1 - half), (x2, y2 - half), (x2, y2 + half), (x1, y1 + half))


def _scaled(points, s):
    return tuple((px * s, py * s) for px, py in points)


def _layout(size: float, pal: dict) -> list:
    """Shape specs as (kind, (dx, dy), data, colour, opacity), drawn back to front."""
    s = size
    return [
        ("ellipse", (0.0, -19.0 * s), (30.0 * s, 12.0 * s), (0, 0, 0), 130),
        ("circle", (0.0, 0.0), 22.0 * s, pal["glow"], 65),
        ("circle", (0.0, 1.0 * s), 28.0 * s, aura_outer(pal), 28),
        ("poly", (0.0, 0.0), _scaled(_WING, s), _WING_COLOR, 255),
        ("poly", (0.0, 0.0), _scaled(_BODY, s), pal["body"], 255),
        ("poly", (0.0, 0.0), _scaled(_COCKPIT, s), pal["accent"], 255),
        ("circle", (-10.0 * s, 0.0), 4.0 * s, pal["glow"], 255),
        ("poly", (0.0, 0.0), _scaled(_bar(8.0, 0.0, 26.0, 0.0, 1.5), s), _BARREL_COLOR, 210),
        ("poly", (0.0, 0.0), _scaled(_bar(8.0, 0.0, 26.0, 0.0, 0.5), s), pal["eye"], 220),
        ("poly", (0.0, 0.0), _scaled(_bar(-9.0, 4.0, -19.0, 4.0, 2.0), s), pal["trail"], 110),
        ("poly", (0.0, 0.0), _scaled(_bar(-9.0, -4.0, -19.0, -4.0, 2.0), s), pal["trail"], 110),
    ]


class SkinPreview:
    """One skin's character drawn into ``batch``. Call ``set`` to move or recolour it, ``delete`` to remove it.

    Keep a reference to the handle while the preview should stay on screen: pyglet deletes a shape's
    vertex data when the shape object is garbage-collected, so a dropped handle makes the preview vanish.
    """

    def __init__(self, batch, x: float = 0.0, y: float = 0.0, size: float = 1.0, palette: dict | None = None, group=None):
        self._batch = batch
        self._group = group
        self._shapes: list = []
        self._specs: list = []
        self._key = None
        self._x = 0.0
        self._y = 0.0
        self.set(x, y, size, palette)

    def set(self, x: float, y: float, size: float = 1.0, palette: dict | None = None) -> None:
        """Place the character centre at (x, y) at ``size``. A size or palette change rebuilds the shapes."""
        size = max(0.05, float(size))
        pal = complete_palette(palette)
        key = (size, tuple(sorted(pal.items())))
        if key != self._key:
            self._key = key
            self._rebuild(size, pal)
        self._x = float(x)
        self._y = float(y)
        for shape, (_kind, (dx, dy), _data, _color, _opacity) in zip(self._shapes, self._specs):
            shape.x = self._x + dx
            shape.y = self._y + dy

    def _rebuild(self, size: float, pal: dict) -> None:
        self._clear()
        self._specs = _layout(size, pal)
        for kind, _offset, data, color, opacity in self._specs:
            if kind == "poly":
                shape = shapes.Polygon(*data, color=color, batch=self._batch, group=self._group)
            elif kind == "circle":
                shape = shapes.Circle(0, 0, data, color=color, batch=self._batch, group=self._group)
            else:
                shape = shapes.Ellipse(0, 0, data[0], data[1], color=color, batch=self._batch, group=self._group)
            shape.opacity = opacity
            self._shapes.append(shape)

    def _clear(self) -> None:
        for shape in self._shapes:
            shape.delete()
        self._shapes = []
        self._specs = []

    def delete(self) -> None:
        self._clear()
        self._key = None

    @property
    def shape_count(self) -> int:
        return len(self._shapes)


def draw_skin_preview(batch, x: float, y: float, size: float = 1.0, palette: dict | None = None, group=None) -> SkinPreview:
    """Draw the legacy ship centred at (x, y) at ``size`` (1.0 = in-run legacy ship). Returns the handle."""
    return SkinPreview(batch, x, y, size=size, palette=palette, group=group)


class CharacterPreview:
    """One skin's character for a Hangar card: the in-run look, fixed in place, in that skin's palette.

    The look follows config.USE_PLAYER_ART, the switch Visuals.make_player reads at build time. The
    palette is resolved once here, through skin_apply.complete_palette, so the card and read_run_skin agree.

    ``place`` sets the character's centre on screen; call it when the card layout changes. ``update``
    poses the character for the Hangar's clock ``t``; call it every frame. Neither allocates per frame.
    """

    def __init__(self, batch, group=None, palette: dict | None = None):
        self._player = Player(pos=Vec2(0.0, 0.0))  # the fixed dummy character every card shows
        self._aim = Vec2(1.0, 0.0)
        self._shake = Vec2(0.0, 0.0)
        self._palette = complete_palette(palette)  # one dict object, so PlayerArt resolves it only once
        self._art = PlayerArt(batch, group) if config.USE_PLAYER_ART else None
        self._legacy = None if self._art is not None else SkinPreview(batch, group=group, palette=self._palette)

    @property
    def palette(self) -> dict:
        """The palette this card draws, as a copy."""
        return dict(self._palette)

    @property
    def uses_player_art(self) -> bool:
        """True when the card draws the pod robot, False when it draws the legacy ship."""
        return self._art is not None

    @property
    def art(self) -> PlayerArt | None:
        """The PlayerArt behind the card, or None for the legacy look."""
        return self._art

    @property
    def legacy(self) -> SkinPreview | None:
        """The legacy ship behind the card, or None for the pod look."""
        return self._legacy

    def place(self, x: float, y: float) -> None:
        """Put the character's centre at screen point (x, y)."""
        # The dummy character sits at the world origin, so the shake offset carries it to (x, y).
        ox, oy = to_iso(Vec2(0.0, 0.0), Vec2(0.0, 0.0))
        self._shake = Vec2(x - ox, y - oy)
        if self._legacy is not None:
            self._legacy.set(x, y, 1.0, self._palette)

    def update(self, t: float) -> None:
        """Pose the pod robot for clock time ``t``. The legacy ship is static, so this does nothing for it."""
        if self._art is not None:
            self._art.sync(self._player, self._shake, t=t, aim_dir=self._aim, palette=self._palette)

    def delete(self) -> None:
        """Remove the card's shapes from the batch."""
        if self._art is not None:
            self._art.delete()
        if self._legacy is not None:
            self._legacy.delete()
