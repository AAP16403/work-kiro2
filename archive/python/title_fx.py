"""Title-screen effects: a shimmering wordmark, a parallax starfield and a horizon line.

shimmer_levels() is pure, so tests can check the sweep without a window. The classes
draw only shapes, label styling or a vertex list into a batch that the Menu owns. Each
update takes reduced=True (from ui_theme.reduce_motion()) to freeze its motion.
"""

from __future__ import annotations

import math
import random

import pyglet
import pyglet.text.document  # noqa: F401  (FormattedDocument is used by ShimmerText)
from pyglet import sprite
from pyglet.gl import GL_BLEND, GL_ONE_MINUS_SRC_ALPHA, GL_SRC_ALPHA, GL_TRIANGLES, glBlendFunc, glDisable, glEnable
from pyglet.shapes import get_default_shader

from ui_theme import ACCENT, TEXT, mix_rgb

SHIMMER_PERIOD = 5.0  # seconds per sweep cycle
SHIMMER_ACTIVE = 0.34  # share of each cycle spent sweeping; the rest rests
SHIMMER_SIGMA = 0.9  # band width, in letters
SHIMMER_PEAK = (255, 255, 255)

# Starfield layers: (stars per 980x620 of area, drift in px/s, star size in px, opacity).
STAR_LAYERS = (
    (60, 5.0, 1.0, 96),
    (30, 14.0, 1.5, 150),
    (12, 30.0, 2.0, 220),
)
_STAR_REF_AREA = 980.0 * 620.0
_STAR_CAP = 400  # per layer, so a huge window cannot blow up the vertex count


def shimmer_levels(
    count: int,
    t: float,
    *,
    period: float = SHIMMER_PERIOD,
    active: float = SHIMMER_ACTIVE,
    sigma: float = SHIMMER_SIGMA,
) -> list[float]:
    """Brightness 0..1 for each of count letters while a light band sweeps left to right.

    The band starts just left of the first letter and ends just right of the last one,
    then rests for the rest of the cycle, so the function returns all zeros in that rest.
    """
    if count <= 0:
        return []
    phase = (float(t) % period) / period
    if phase >= active:
        return [0.0] * count
    progress = phase / active
    centre = -1.0 + progress * (count + 1.0)
    out = []
    for i in range(count):
        d = (i - centre) / sigma
        out.append(math.exp(-0.5 * d * d))
    return out


class ShimmerText:
    """Sweeps a light band across the letters of a label by restyling each character."""

    def __init__(self, label, base: tuple = ACCENT, peak: tuple = SHIMMER_PEAK):
        self.label = label
        self._base = tuple(base)[:3]
        self._peak = tuple(peak)[:3]
        text = label.text
        if not isinstance(label.document, pyglet.text.document.FormattedDocument):
            # A plain label has one style for all of its text, so swap in a formatted
            # document that keeps the same font and size and can colour each letter.
            doc = pyglet.text.document.FormattedDocument(text)
            doc.set_style(0, len(text), {
                "font_name": label.font_name,
                "font_size": label.font_size,
                "color": (*self._base, 255),
            })
            label.document = doc
        self._letters = [i for i, ch in enumerate(text) if not ch.isspace()]
        self._applied: tuple | None = None
        self.update(0.0, reduced=True)

    @property
    def colours(self) -> tuple:
        """RGB colour of each letter as last applied, in text order."""
        return self._applied or ()

    def update(self, t: float, reduced: bool = False) -> None:
        count = len(self._letters)
        levels = [0.0] * count if reduced else shimmer_levels(count, t)
        colours = tuple(mix_rgb(self._base, self._peak, lv) for lv in levels)
        if colours == self._applied:
            return
        doc = self.label.document
        for idx, rgb in zip(self._letters, colours):
            doc.set_style(idx, idx + 1, {"color": (rgb[0], rgb[1], rgb[2], 255)})
        self._applied = colours


class _StarGroup(pyglet.graphics.Group):
    """Alpha blending for star quads, set and unset the same way pyglet's shape groups do."""

    def __init__(self, program, parent=None):
        # order=-1 draws the stars before every default-group shape and label in the menu batch.
        super().__init__(order=-1, parent=parent)
        self.program = program

    def set_state(self) -> None:
        self.program.bind()
        glEnable(GL_BLEND)
        glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)

    def unset_state(self) -> None:
        glDisable(GL_BLEND)
        self.program.unbind()


class Starfield:
    """Three layers of stars drifting left at different speeds, drawn in screen space.

    Each layer is one vertex list of small quads that uses the default shape shader. update()
    writes a layer's positions in a single slice assignment, which is much cheaper than
    moving each star as its own shape.
    """

    def __init__(self, batch, width: int, height: int, seed: int = 7):
        self._batch = batch
        self._seed = int(seed)
        self._program = get_default_shader()
        self._group = _StarGroup(self._program)
        self._w = 0
        self._h = 0
        self._layers: list[dict] = []
        self.resize(width, height)

    @property
    def star_count(self) -> int:
        return sum(len(layer["xs"]) for layer in self._layers)

    def positions(self) -> list[tuple[float, float]]:
        """Current (x, y) of every star, layer by layer."""
        return [pos for layer in self._layers for pos in zip(layer["xs"], layer["ys"])]

    def resize(self, width: int, height: int) -> None:
        """Rebuild the stars for a new window size. A call with the same size changes nothing."""
        w = max(1, int(width))
        h = max(1, int(height))
        if (w, h) == (self._w, self._h) and self._layers:
            return
        for layer in self._layers:
            layer["vl"].delete()
        self._w, self._h = w, h
        rng = random.Random(self._seed)  # local RNG: the title's stars never touch global random
        # Star count grows with the square root of the area, so a 4K window does not get 6x the stars.
        scale = math.sqrt((w * h) / _STAR_REF_AREA)
        self._layers = []
        for count, speed, size, opacity in STAR_LAYERS:
            n = max(4, min(_STAR_CAP, round(count * scale)))
            xs = [rng.uniform(0.0, float(w)) for _ in range(n)]
            ys = [rng.uniform(0.0, float(h)) for _ in range(n)]
            vl = self._program.vertex_list(
                6 * n,
                GL_TRIANGLES,
                self._batch,
                self._group,
                position=("f", (0.0,) * (12 * n)),
                colors=("Bn", (*TEXT, opacity) * (6 * n)),
                translation=("f", (0.0, 0.0) * (6 * n)),
                rotation=("f", (0.0,) * (6 * n)),
            )
            layer = {"speed": float(speed), "size": float(size), "xs": xs, "ys": ys, "vl": vl}
            vl.position[:] = _quad_positions(xs, ys, layer["size"])
            self._layers.append(layer)

    def update(self, dt: float, reduced: bool = False) -> None:
        """Drift each layer left by its speed. Nothing moves when reduced is True."""
        if reduced:
            return
        step = max(0.0, min(float(dt), 0.1))
        w = float(self._w)
        for layer in self._layers:
            move = layer["speed"] * step
            xs = layer["xs"]
            for i, x in enumerate(xs):
                x -= move
                if x < 0.0:
                    x += w
                xs[i] = x
            layer["vl"].position[:] = _quad_positions(xs, layer["ys"], layer["size"])


def _quad_positions(xs: list[float], ys: list[float], size: float) -> list[float]:
    """Two triangles per star, as a flat x, y list for a position2f vertex list."""
    out: list[float] = []
    for x, y in zip(xs, ys):
        x1 = x + size
        y1 = y + size
        out.extend((x, y, x1, y, x1, y1, x, y, x1, y1, x, y1))
    return out


HORIZON_TEX_W = 256
HORIZON_TEX_H = 32


def horizon_texture(colour: tuple = ACCENT) -> pyglet.image.ImageData:
    """RGBA strip for the horizon: a bright core with a soft glow, fading to nothing at both ends.

    Built once per Horizon with plain bytes, so it costs no per-frame work.
    """
    w, h = HORIZON_TEX_W, HORIZON_TEX_H
    r, g, b = int(colour[0]), int(colour[1]), int(colour[2])
    peak = 150 / 255.0
    buf = bytearray(w * h * 4)
    for row in range(h):
        d = (row + 0.5) / h * 2.0 - 1.0  # -1 at the bottom edge, +1 at the top edge
        vertical = 0.85 * math.exp(-((d / 0.07) ** 2)) + 0.30 * math.exp(-((d / 0.35) ** 2))
        for col in range(w):
            across = math.sin(math.pi * (col + 0.5) / w) ** 0.8
            a = int(max(0.0, min(1.0, peak * across * vertical)) * 255)
            i = (row * w + col) * 4
            buf[i:i + 4] = bytes((r, g, b, a))
    return pyglet.image.ImageData(w, h, "RGBA", bytes(buf))


class Horizon:
    """A thin accent line across the width, brightest at the centre and fading toward both edges."""

    def __init__(self, batch, width: int, y: float, colour: tuple = ACCENT):
        self._sprite = sprite.Sprite(horizon_texture(colour), x=0, y=0, batch=batch)
        self.place(width, y)

    def place(self, width: float, y: float) -> None:
        """Lay the line across the full width, centred on height y."""
        self._sprite.scale_x = max(1.0, float(width)) / HORIZON_TEX_W
        self._sprite.scale_y = 1.0
        self._sprite.x = 0
        self._sprite.y = float(y) - HORIZON_TEX_H / 2.0
