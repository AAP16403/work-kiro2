"""Game feel v2: enemy hit squash, low-health vignette and Ultra flash.

Every effect reads state the game already keeps (an enemy's hit_flash_timer, the player's
hp, the Ultra trigger time) and works on shapes or sprites that are created once. Per
frame the code only moves, scales, recolours or rewrites an existing body's vertex buffer
from a cache. It never creates a shape.
"""

from __future__ import annotations

import functools
import math

from pyglet import image, shapes
from pyglet.sprite import Sprite

import config
from utils import to_iso, Vec2

# Enemy hit squash. HIT_SQUASH_TIME matches the hit_flash_timer that states.py sets on a hit.
HIT_SQUASH_TIME = 0.12
HIT_SQUASH_AMOUNT = 0.22   # peak width gain; the height drops by the reciprocal, so the area holds
SQUASH_STEP = 0.01         # squash is quantised to this step, so each body needs only a small table of levels

# Low-health vignette: a red edge glow that fades in below LOW_HP_THRESHOLD.
LOW_HP_THRESHOLD = 0.30
LOW_HP_MAX_OPACITY = 0.85
LOW_HP_PULSE_PERIOD = 2.4  # seconds per slow pulse
LOW_HP_PULSE_DEPTH = 0.20  # the pulse dims the vignette by at most this fraction
LOW_HP_COLOR = (150, 12, 22)  # deep red, tinted onto a white texture

# Ultra flash: a short white flash tinted by the variant colour, drawn over the shockwave ring.
ULTRA_FLASH_TIME = 0.22
ULTRA_FLASH_OPACITY = 0.85
ULTRA_FLASH_TINT = 0.60          # 0 is pure white, 1 is the variant colour
ULTRA_FLASH_START_SCALE = 0.6    # the flash starts at this share of its radius and swells to full size

_VIGNETTE_W = 64
_VIGNETTE_H = 36
_FLASH_TEX = 64
_FLASH_HALF = _FLASH_TEX / 2.0


def _clamp01(v: float) -> float:
    if v <= 0.0:
        return 0.0
    if v >= 1.0:
        return 1.0
    return float(v)


# ---------------------------------------------------------------------------
# Enemy hit squash
# ---------------------------------------------------------------------------

_SQUASH_MAX_LEVEL = int(round(HIT_SQUASH_AMOUNT / SQUASH_STEP))


def _squash_amount(timer: float, duration: float = HIT_SQUASH_TIME) -> float:
    """Signed squash amount for a body hit `timer` seconds ago. Zero at rest.

    At impact the body is squashed wide and short. It overshoots into a small stretch and
    the wobble dies out as the timer runs out.
    """
    p = _clamp01(float(timer) / max(1e-6, float(duration)))
    if p <= 0.0:
        return 0.0
    q = 1.0 - p  # 0 at impact, 1 when the timer ends
    return HIT_SQUASH_AMOUNT * p * math.cos(math.tau * q)


def hit_squash_scale(timer: float, duration: float = HIT_SQUASH_TIME) -> tuple[float, float]:
    """Width and height scale for a body hit `timer` seconds ago. Exactly (1.0, 1.0) at rest."""
    s = _squash_amount(timer, duration)
    return 1.0 + s, 1.0 / (1.0 + s)


def squash_level(timer: float) -> int:
    """The hit squash quantised to SQUASH_STEP. Zero means rest."""
    return int(round(_squash_amount(timer) / SQUASH_STEP))


def _squash_vertices(segments: int, radius: float, anchor_x: float, anchor_y: float, level: int) -> tuple:
    """Vertex positions of a pyglet Circle squashed by `level`, in pyglet's triangle-fan layout."""
    s = level * SQUASH_STEP
    sx = 1.0 + s
    sy = 1.0 / sx
    x0 = -anchor_x
    y0 = -anchor_y
    step = math.tau / segments
    pts = [(x0 + radius * sx * math.cos(i * step), y0 + radius * sy * math.sin(i * step)) for i in range(segments)]
    verts: list[float] = []
    for i in range(segments):
        px, py = pts[i - 1]
        cx, cy = pts[i]
        verts.extend((x0, y0, px, py, cx, cy))
    return tuple(verts)


@functools.lru_cache(maxsize=256)
def _squash_table(segments: int, radius: float, anchor_x: float, anchor_y: float) -> tuple:
    """Vertex tuples for every squash level, from -MAX to +MAX. Index with level + _SQUASH_MAX_LEVEL."""
    return tuple(_squash_vertices(segments, radius, anchor_x, anchor_y, level)
                 for level in range(-_SQUASH_MAX_LEVEL, _SQUASH_MAX_LEVEL + 1))


def apply_hit_squash(shape, timer: float) -> None:
    """Squash a pyglet Circle body for the enemy's current hit timer.

    The body's own vertex buffer is rewritten from a per-body table of precomputed levels,
    so a frame does one list index and creates no shape or key. When the squash ends, the
    body goes back through pyglet's radius setter, which rebuilds its rest geometry exactly.
    Shapes that are not circles are left alone.
    """
    current = int(getattr(shape, "_juice_level", 0))
    if current == 0 and timer <= 0.0:
        return  # hot path: most enemies are not being hit
    if not isinstance(shape, shapes.Circle):
        return
    level = squash_level(timer)
    if level == current:
        return
    if level == 0:
        shape._juice_level = 0
        shape.radius = shape._juice_rest_radius
        return
    if not shape._visible:
        return
    table = getattr(shape, "_juice_table", None)
    if table is None:
        rest = float(shape.radius)
        shape._juice_rest_radius = rest
        table = _squash_table(shape._segments, rest, float(shape._anchor_x), float(shape._anchor_y))
        shape._juice_table = table
    shape._vertex_list.position[:] = table[level + _SQUASH_MAX_LEVEL]
    shape._juice_level = level


# ---------------------------------------------------------------------------
# Low-health vignette
# ---------------------------------------------------------------------------

def low_hp_vignette_strength(hp_ratio: float, t: float, reduce_motion: bool | None = None) -> float:
    """Vignette opacity in [0, 1]. Zero at or above 30 percent HP, rising to full at zero HP.

    The slow pulse dims the vignette by up to LOW_HP_PULSE_DEPTH. With reduce motion (by
    default config.REDUCE_MOTION) the pulse is switched off and the vignette holds steady,
    so the warning stays readable.
    """
    hp = _clamp01(hp_ratio)
    if hp >= LOW_HP_THRESHOLD:
        return 0.0
    if reduce_motion is None:
        reduce_motion = bool(getattr(config, "REDUCE_MOTION", False))
    depth = (LOW_HP_THRESHOLD - hp) / LOW_HP_THRESHOLD  # 0 at the threshold, 1 at zero HP
    if reduce_motion:
        pulse = 1.0
    else:
        wave = 0.5 + 0.5 * math.sin(math.tau * float(t) / LOW_HP_PULSE_PERIOD)
        pulse = 1.0 - LOW_HP_PULSE_DEPTH * (1.0 - wave)
    return LOW_HP_MAX_OPACITY * depth * pulse


# ---------------------------------------------------------------------------
# Ultra flash
# ---------------------------------------------------------------------------

def ultra_flash_strength(age: float) -> float:
    """Flash strength in [0, 1]: full at the trigger and gone after ULTRA_FLASH_TIME."""
    if age < 0.0 or age >= ULTRA_FLASH_TIME:
        return 0.0
    prog = age / ULTRA_FLASH_TIME
    return (1.0 - prog) ** 1.2


def ultra_flash_color(variant_color) -> tuple[int, int, int]:
    """A white flash tinted by the Ultra variant colour."""
    r, g, b = (int(c) for c in tuple(variant_color)[:3])
    k = ULTRA_FLASH_TINT
    return (
        int(255 + (r - 255) * k),
        int(255 + (g - 255) * k),
        int(255 + (b - 255) * k),
    )


# ---------------------------------------------------------------------------
# Textures and the overlay that owns the sprites
# ---------------------------------------------------------------------------

def _texture(w: int, h: int, alpha_at, centred: bool):
    """Build a white RGBA texture once. alpha_at(dx, dy) takes normalised coords in [-1, 1]."""
    half_w = w / 2.0
    half_h = h / 2.0
    data = bytearray()
    for row in range(h):
        dy = (row + 0.5 - half_h) / half_h
        for col in range(w):
            dx = (col + 0.5 - half_w) / half_w
            data += bytes((255, 255, 255, int(255 * _clamp01(alpha_at(dx, dy)))))
    img = image.ImageData(w, h, "RGBA", bytes(data))
    if centred:
        img.anchor_x = w // 2
        img.anchor_y = h // 2
    return img.get_texture()


def _vignette_alpha(dx: float, dy: float) -> float:
    """Zero in the middle, rising to full at the corners."""
    r = math.hypot(dx, dy) / math.sqrt(2.0)
    t = _clamp01((r - 0.35) / 0.65)
    return (t * t * (3.0 - 2.0 * t)) ** 1.3


def _flash_alpha(dx: float, dy: float) -> float:
    """Bright core fading into a soft halo."""
    d = math.hypot(dx, dy)
    if d >= 1.0:
        return 0.0
    core = _clamp01(1.0 - d / 0.45) ** 2
    halo = 0.55 * (1.0 - d) ** 2
    return min(1.0, core + halo)


class JuiceOverlay:
    """Owns the low-health vignette sprite and the Ultra flash sprite. Both live in the game batch."""

    def __init__(self, batch, vignette_group, flash_group) -> None:
        self._vignette = Sprite(_texture(_VIGNETTE_W, _VIGNETTE_H, _vignette_alpha, centred=False),
                                batch=batch, group=vignette_group)
        self._vignette.opacity = 0
        self._vignette.color = LOW_HP_COLOR
        self._view = (0, 0)
        self._flash = Sprite(_texture(_FLASH_TEX, _FLASH_TEX, _flash_alpha, centred=True),
                             batch=batch, group=flash_group)
        self._flash.opacity = 0
        self._flash_on = False
        self._flash_pos = Vec2(0.0, 0.0)
        self._flash_t0 = 0.0
        self._flash_radius = 1.0

    def trigger_ultra_flash(self, pos: Vec2, variant_color, radius: float, t: float) -> None:
        """Start the Ultra flash at a world position. It draws over the shockwave ring."""
        self._flash_pos = Vec2(float(pos.x), float(pos.y))
        self._flash_t0 = float(t)
        self._flash_radius = max(1.0, float(radius))
        self._flash.color = ultra_flash_color(variant_color)
        self._flash_on = True

    def sync(self, t: float, shake: Vec2, hp_ratio: float, view_w: int, view_h: int) -> None:
        """Per-frame update. Moves, scales and fades the two sprites. Creates nothing."""
        # Low-health vignette: one sprite stretched over the whole window.
        if (view_w, view_h) != self._view:
            self._view = (view_w, view_h)
            self._vignette.scale_x = max(1, view_w) / float(_VIGNETTE_W)
            self._vignette.scale_y = max(1, view_h) / float(_VIGNETTE_H)
        opacity = int(255 * low_hp_vignette_strength(hp_ratio, t))
        if self._vignette.opacity != opacity:
            self._vignette.opacity = opacity

        # Ultra flash: follows the screen shake like the rest of the world.
        if self._flash_on:
            age = float(t) - self._flash_t0
            strength = ultra_flash_strength(age)
            if strength <= 0.0:
                self._flash_on = False
                self._flash.opacity = 0
            else:
                prog = age / ULTRA_FLASH_TIME
                sx, sy = to_iso(self._flash_pos, shake)
                self._flash.x = sx
                self._flash.y = sy
                swell = ULTRA_FLASH_START_SCALE + (1.0 - ULTRA_FLASH_START_SCALE) * prog
                self._flash.scale = max(0.02, self._flash_radius * swell / _FLASH_HALF)
                self._flash.opacity = int(255 * ULTRA_FLASH_OPACITY * strength)
